"""Build reproducible static/clean plates for non-overlapping full subjects.

No image generation, neck blending, semantic approval or video API calls.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
from PIL import Image


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def local(root, name):
    if not isinstance(name, str) or not name:
        raise ValueError('asset path must be a non-empty project-relative string')
    path = (root / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError('asset path must stay within project root')
    return path


def overlap(a, b):
    return a[0] < b[0]+b[2] and b[0] < a[0]+a[2] and a[1] < b[1]+b[3] and b[1] < a[1]+a[3]


def prepare(spec_path, root):
    spec = json.loads(spec_path.read_text(encoding='utf-8-sig'))
    if not isinstance(spec.get('sceneId'), str) or not spec['sceneId'].strip():
        raise ValueError('sceneId is required')
    bg_path = local(root, spec['background'])
    with Image.open(bg_path) as im:
        bg = im.convert('RGBA')
    if bg.getchannel('A').getextrema() != (255, 255):
        raise ValueError('background must be opaque')
    inputs = [{'path': spec['background'], 'sha256': digest(bg_path)}]
    layers, subjects, ids = [], [], set()
    for item in spec.get('layers', []):
        name, kind = item.get('id'), item.get('kind')
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9-]*', name) or name in ids:
            raise ValueError('layer ids must be unique lowercase names')
        if kind not in {'underlay', 'subject'}:
            raise ValueError('only underlay and subject supported; foreground needs a scene renderer')
        if kind == 'underlay' and subjects:
            raise ValueError('underlays must precede all subjects')
        ids.add(name)
        rect = item.get('rect')
        if not isinstance(rect, list) or len(rect) != 4 or any(type(v) is not int for v in rect):
            raise ValueError('rect requires integer [x,y,width,height]')
        x, y, w, h = rect
        if min(x, y) < 0 or min(w, h) <= 0 or x+w > bg.width or y+h > bg.height:
            raise ValueError('layer must fit inside scene; do not clip the motion margin')
        path = local(root, item['image'])
        with Image.open(path) as im:
            rgba = im.convert('RGBA')
        lo, hi = rgba.getchannel('A').getextrema()
        if lo == 255 or hi == 0:
            raise ValueError('layer needs visible pixels and real transparency')
        if abs((w/h)/(rgba.width/rgba.height)-1) > .01:
            raise ValueError('rect must preserve source aspect ratio')
        if kind == 'subject':
            if any(overlap(rect, other['rect']) for other in subjects):
                raise ValueError('subject canvas rectangles overlap; shared scene renderer required')
            subjects.append(item)
        # Pillow RGBA resize uses premultiplied alpha, avoiding hidden RGB fringes.
        layers.append((item, rgba.resize((w, h), Image.Resampling.LANCZOS)))
        inputs.append({'path': item['image'], 'sha256': digest(path)})
    if not subjects:
        raise ValueError('at least one subject layer is required')
    return spec, bg, layers, subjects, inputs


def render(bg, layers, exclude=None):
    canvas = bg.copy()
    for item, image in layers:
        if item['id'] != exclude:
            canvas.alpha_composite(image, tuple(item['rect'][:2]))
    return canvas.convert('RGB')


def build(spec_path, root, output):
    root, spec_path, output = Path(root).resolve(), Path(spec_path).resolve(), Path(output).resolve()
    if not spec_path.is_relative_to(root):
        raise ValueError('spec must be inside project root')
    if output.exists():
        raise ValueError('output already exists; choose a new candidate directory')
    spec, bg, layers, subjects, inputs = prepare(spec_path, root)
    output.mkdir(parents=True)
    render(bg, layers).save(output/'static.png')
    artifacts = ['static.png']
    for subject in subjects:
        name = f"clean-{subject['id']}.png"
        render(bg, layers, exclude=subject['id']).save(output/name)
        artifacts.append(name)
    contract = dict(schemaVersion=1, sceneId=spec['sceneId'], sourceSize=list(bg.size),
                    spec=dict(path=spec_path.relative_to(root).as_posix(), sha256=digest(spec_path)),
                    inputs=inputs, subjects=subjects,
                    outputs=[dict(path=name, sha256=digest(output/name)) for name in artifacts],
                    visualAcceptance='unreviewed',
                    scope='static composition only; no motion, gaze, lighting or occlusion certification')
    (output/'scene.json').write_text(json.dumps(contract, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return contract


def verify(contract_path, root):
    root, contract_path = Path(root).resolve(), Path(contract_path).resolve()
    data = json.loads(contract_path.read_text(encoding='utf-8'))
    spec_path = local(root, data['spec']['path'])
    for record in [data['spec'], *data['inputs']]:
        if digest(local(root, record['path'])) != record['sha256']:
            raise ValueError('input changed; recompose static scene')
    spec, bg, layers, subjects, inputs = prepare(spec_path, root)
    if data['subjects'] != subjects or data['inputs'] != inputs or data['sceneId'] != spec['sceneId'] or data['sourceSize'] != list(bg.size):
        raise ValueError('contract geometry differs from source spec')
    expected = ['static.png', *[f"clean-{s['id']}.png" for s in subjects]]
    if [r['path'] for r in data['outputs']] != expected:
        raise ValueError('incomplete static/clean plate outputs')
    for record in data['outputs']:
        if digest(local(contract_path.parent, record['path'])) != record['sha256']:
            raise ValueError('output changed; old composition record is stale')
    return dict(valid=True, sceneId=data['sceneId'], visualAcceptance='not-evaluated')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('build')
    create.add_argument('spec', type=Path)
    create.add_argument('--root', type=Path, required=True)
    create.add_argument('--output', type=Path, required=True)
    check = sub.add_parser('verify')
    check.add_argument('contract', type=Path)
    check.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'build':
        result = build(args.spec, args.root, args.output)
        print(json.dumps(dict(sceneId=result['sceneId'], subjects=len(result['subjects']), visualAcceptance='unreviewed')))
    else:
        print(json.dumps(verify(args.contract, args.root)))
