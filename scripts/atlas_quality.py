"""Content-bound quality reports. Metrics screen defects; observations judge semantics."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter
from inspect_atlas_seams import transition_metrics

DIRECTIONS = ['up', 'upper-right', 'right', 'lower-right', 'down', 'lower-left', 'left', 'upper-left']
CHECKS = ['directionCoverage', 'gaze', 'loop', 'background', 'contours', 'synthetic', 'interaction']


def validate_phases(samples, count, anchors=None):
    import math
    if (not isinstance(samples, list) or len(samples) < 8 or samples[0] != [0, 0]
            or any(not isinstance(p, list) or len(p) != 2 or type(p[0]) is not int
                   or not 0 <= p[0] < count or type(p[1]) not in (int, float)
                   or not math.isfinite(p[1]) or not 0 <= p[1] < 360 for p in samples)
            or any(a[0] >= b[0] or a[1] >= b[1] for a,b in zip(samples,samples[1:]))):
        raise ValueError('phaseSamples require increasing [atlasFrame, observedDegrees], starting at [0,0]')
    if anchors and any([frame, i*45] not in samples for i,frame in enumerate(anchors)):
        raise ValueError('phaseSamples must agree with the eight direction anchors')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def contract(m):
    return {k: v for k, v in m.items() if k != 'quality'}


def binding(m, path, root):
    records = []
    resources = [('root', m['baseImage']), *[('manifest', p) for p in m['sheets']]]
    if m.get('cleanPlate'):
        resources.append(('root', m['cleanPlate']['path']))
    if m.get('frameLineage'):
        resources.append(('root', m['frameLineage']['path']))
    for scope, name in resources:
        records.append(dict(scope=scope, path=name, sha256=digest((root if scope == 'root' else path.parent) / name)))
    return dict(contract=contract(m), assets=records)


def load_frames(m, path):
    w, h = m['crop'][2:]
    sheets = []
    for name in m['sheets']:
        with Image.open(path.parent / name) as im:
            sheets.append(im.convert('RGBA'))
    frames = []
    for i in range(m['frameCount']):
        sheet, cell = divmod(i, m['framesPerSheet'])
        x, y = cell % m['columns'] * w, cell // m['columns'] * h
        frames.append(np.array(sheets[sheet].crop((x, y, x+w, y+h))))
    return frames


def composite_frames(m, path, root):
    x, y, w, h = m['crop']
    plate = m['cleanPlate']['path'] if m['background']['owner'] == 'page' else m['baseImage']
    with Image.open(root / plate) as im:
        under = im.convert('RGBA').crop((x, y, x+w, y+h))
    result = []
    for frame in load_frames(m, path):
        out = under.copy()
        out.alpha_composite(Image.fromarray(frame))
        result.append(np.array(out.convert('RGB')))
    return result


def mask(path, size):
    with Image.open(path) as im:
        if im.size != tuple(size):
            raise ValueError(f'mask dimensions mismatch: {path}')
        a = np.array(im.convert('L'))
    if not np.isin(a, [0, 255]).all():
        raise ValueError('QA masks must be binary (0 / 255)')
    return a == 255


def background_metrics(frames, reference, static, motion):
    if static.shape != reference.shape[:2] or motion.shape != static.shape:
        raise ValueError('mask size mismatch')
    expanded = np.array(Image.fromarray((motion*255).astype('uint8')).filter(ImageFilter.MaxFilter(5))) > 0
    if (static & expanded).any() or static.sum() < max(16, static.size * .02) or not motion.any():
        raise ValueError('static mask must exclude the full motion union plus padding and cover enough background')
    # Include local edge differences: an equal mean color cannot hide shifted texture.
    edge_mask = static[:-1, :-1] & static[1:, :-1] & static[:-1, 1:]
    if edge_mask.sum() < 8:
        raise ValueError('static mask needs contiguous regions for structural QA')
    def edge(a):
        a = a.astype(float)
        return np.abs(a[1:, :-1]-a[:-1, :-1]) + np.abs(a[:-1, 1:]-a[:-1, :-1])
    ref_edge = edge(reference)
    rows = []
    for i, frame in enumerate(frames):
        delta = np.abs(frame.astype(float) - reference.astype(float))[static]
        rows.append(dict(frame=i, mae=float(delta.mean()), p95=float(np.percentile(delta, 95)),
                         edgeError=float(np.abs(edge(frame)-ref_edge)[edge_mask].mean())))
    return dict(framesChecked=len(rows), samples=rows,
                passed=all(r['mae'] <= 5 and r['p95'] <= 15 and r['edgeError'] <= 5 for r in rows),
                thresholds=dict(mae=5, p95=15, edgeError=5),
                scope='reviewed static mask only; contours and occlusion require separate review')


def review_template(m, path, root):
    return dict(schemaVersion=1, binding=binding(m, path, root),
                observations=[dict(frame=f, head=d, gaze='unknown', evidence=[], notes='')
                              for f, d in zip(m['directionFrames'], DIRECTIONS)],
                checks={name: dict(status='unreviewed', evidence=[], notes='') for name in CHECKS},
                backgroundMasks=None, resolvedTransitions=[])


def evidence_files(item, root):
    files = item.get('evidence', [])
    if not isinstance(files, list) or not files or not str(item.get('notes', '')).strip():
        return None
    if any(not isinstance(p, str) or not (root/p).is_file() for p in files):
        return None
    return {p: digest(root/p) for p in files}


def assess(m, path, root, review=None):
    actual = binding(m, path, root)
    frames = composite_frames(m, path, root)
    metrics = transition_metrics(frames)
    problems, evidence = [], {}
    r = review or {}
    if r.get('binding') != actual:
        problems.append('missing-or-stale-review-binding')
    for name in CHECKS:
        item = r.get('checks', {}).get(name, {})
        files = evidence_files(item, root)
        if item.get('status') != 'pass' or files is None:
            problems.append('unreviewed-or-failed:' + name)
        else:
            evidence.update(files)
    observations = r.get('observations', [])
    if len(observations) != 8:
        problems.append('eight-observed-directions-required')
    else:
        for item, frame, direction in zip(observations, m['directionFrames'], DIRECTIONS):
            files = evidence_files(item, root)
            if item.get('frame') != frame or item.get('head') != direction or item.get('gaze') != direction or files is None:
                problems.append('missing-head-or-gaze-evidence:' + direction)
            elif files:
                evidence.update(files)
    # A quiet pixel seam is NOT a semantic pass; an alert needs an explicit explanation.
    resolved = {}
    for item in r.get('resolvedTransitions', []):
        files = evidence_files(item, root)
        if files and item.get('status') == 'pass':
            resolved[item.get('afterFrame')] = True
            evidence.update(files)
    for index in metrics['suspectTransitions']:
        if index not in resolved:
            problems.append(f'unresolved-transition:{index}')
    background = dict(passed=None, framesChecked=0)
    masks = r.get('backgroundMasks')
    if not isinstance(masks, dict):
        problems.append('static-and-motion-masks-required')
    else:
        try:
            size = m['crop'][2:]
            static = mask(root/masks['static'], size)
            motion = mask(root/masks['motionUnion'], size)
            x, y, w, h = m['crop']
            with Image.open(root/m['baseImage']) as im:
                base = np.array(im.convert('RGB').crop((x,y,x+w,y+h)))
            background = background_metrics(frames, base, static, motion)
            if not background['passed']:
                problems.append('background-residual')
            for name in [masks['static'], masks['motionUnion']]:
                evidence[name] = digest(root/name)
        except (OSError, ValueError, KeyError) as exc:
            problems.append('invalid-background-masks:' + str(exc))
    # Neutral entry/exit, old contour removal and internal pose reversals cannot be
    # certified from these numbers. The separate checks above remain mandatory.
    return dict(schemaVersion=1, status='reviewed' if not problems else 'blocked',
                circular=not problems, binding=actual, issues=problems,
                transitions=metrics, background=background, evidenceHashes=evidence,
                limitations=['Agent evidence is required for pose, gaze, occlusion and interaction.',
                             'A reviewed result is not a promise of user visual acceptance.'])


def verify_certificate(m, path, root):
    q = m.get('quality', {})
    if q.get('status') != 'reviewed' or q.get('circular') is not True or q.get('binding') != binding(m, path, root):
        raise ValueError('atlas is unreviewed, blocked or changed; run audit_head_atlas.py')
    report_path = path.parent / q['report']
    if digest(report_path) != q['reportSha256']:
        raise ValueError('quality report changed')
    report = read(report_path)
    if report.get('status') != 'reviewed' or report.get('issues') or report.get('binding') != q['binding']:
        raise ValueError('quality report does not approve this atlas')
    for name, sha in report['evidenceHashes'].items():
        if digest(root/name) != sha:
            raise ValueError('review evidence changed: ' + name)


def write_sheets(m, frames, output):
    w, h = m['crop'][2:]
    names = []
    for start in range(0, len(frames), m['framesPerSheet']):
        batch = frames[start:start+m['framesPerSheet']]
        atlas = Image.new('RGBA', (m['columns']*w, ((len(batch)+m['columns']-1)//m['columns'])*h))
        for i, a in enumerate(batch):
            atlas.paste(Image.fromarray(a), ((i%m['columns'])*w, (i//m['columns'])*h))
        name = f'sheet-{len(names)}.png'
        atlas.save(output/name)
        names.append(name)
    m['sheets'], m['frameCount'] = names, len(frames)
