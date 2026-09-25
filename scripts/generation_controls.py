"""Offline request controls. Reviews are human observations, never semantic certificates."""
import base64
import hashlib
import io
import json
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image
from submission_budget import request_hash


PROFILE_DATE = '2026-09-24'
PROFILES = {
    'minimax/minimax-h3-max': {'resolutions': ('480p', '768p'), 'duration': (5, 15), 'expansion': True},
    'minimax/minimax-h3': {'resolutions': ('768p', '2K'), 'duration': (4, 15), 'expansion': False},
}
CHECKS = ('subjectIsolation', 'identity', 'inputPose', 'motionRange', 'featureVisibility', 'framing',
          'fixedParts', 'promptImageAgreement', 'endpointCompatibility', 'motionReference')
REQUIREMENTS = ('identity', 'motion', 'range', 'gaze', 'fixedParts', 'loop', 'rest')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def profile_for(model):
    if not isinstance(model, str) or model not in PROFILES:
        raise ValueError('unprofiled model: add a documented provider/mode adapter before submitting')
    return PROFILES[model]


def request_options(spec, content, ratio):
    model = spec.get('model', 'minimax/minimax-h3-max')
    profile = profile_for(model)
    raw_resolution = str(spec.get('resolution', '768p'))
    resolution = next((r for r in profile['resolutions'] if r.lower() == raw_resolution.lower()), None)
    if resolution is None:
        raise ValueError(f'{model} supports {profile["resolutions"]}; do not reuse another model profile')
    duration = spec.get('duration')
    if spec.get('frames') is not None:
        raise ValueError('these model profiles use duration, not frames')
    if type(duration) is not int or not profile['duration'][0] <= duration <= profile['duration'][1]:
        raise ValueError(f'{model} duration must be an integer in {profile["duration"]}')
    body = dict(model=model, content=content, ratio=ratio, duration=duration,
                resolution=resolution, generate_audio=False, watermark=False, return_last_frame=True)
    if spec.get('seed') is not None:
        if type(spec['seed']) is not int:
            raise ValueError('seed must be an integer')
        body['seed'] = spec['seed']
    extra = spec.get('extra', {})
    if not isinstance(extra, dict) or set(extra) - {'prompt_expansion_mode'}:
        raise ValueError('extra is native nested options; only prompt_expansion_mode is profiled')
    if profile['expansion']:
        mode = extra.get('prompt_expansion_mode')
        if mode not in ('disabled', 'balanced', 'quality'):
            raise ValueError('choose explicit extra.prompt_expansion_mode: disabled, balanced or quality')
        body['extra'] = {'prompt_expansion_mode': mode}
    elif extra:
        raise ValueError('prompt_expansion_mode is not profiled for this model')
    return body


def media_inventory(content):
    """Inspect the exact local bytes that will be submitted, including video geometry."""
    inventory = []
    counts = {}
    seconds = {'reference_video': 0., 'reference_audio': 0.}
    for item in content:
        if item['type'] == 'text':
            continue
        role = item['role']
        uri = item[item['type']]['url']
        if not uri.startswith('data:') or ';base64,' not in uri:
            raise ValueError('new input reviews require local inspected media; download remote inputs first')
        try:
            raw = base64.b64decode(uri.split(',', 1)[1], validate=True)
        except Exception as exc:
            raise ValueError('invalid media data URI') from exc
        mime = uri[5:].split(';', 1)[0].lower()
        size_limit = {'image_url': 30, 'video_url': 50, 'audio_url': 15}[item['type']] * 1024**2
        if len(raw) > size_limit:
            raise ValueError(f'{role} exceeds its per-file size limit')
        entry = dict(role=role, index=counts.get(role, 0), sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        counts[role] = entry['index'] + 1
        if item['type'] == 'image_url':
            with Image.open(io.BytesIO(raw)) as im:
                formats = {'JPEG': {'image/jpeg'}, 'PNG': {'image/png'}, 'WEBP': {'image/webp'},
                           'HEIF': {'image/heif', 'image/heic'}, 'HEIC': {'image/heic', 'image/heif'}}
                if im.format not in formats or mime not in formats[im.format]:
                    raise ValueError('unsupported image format or MIME mismatch; use JPEG, PNG, WEBP or a locally decodable HEIC/HEIF')
                width, height = im.size
                im.verify()
            entry['size'] = [width, height]
        else:
            with tempfile.TemporaryDirectory(prefix='head-follow-probe-') as folder:
                source = Path(folder) / ('input.mp4' if item['type'] == 'video_url' else 'input.audio')
                source.write_bytes(raw)
                try:
                    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                                            '-of', 'json', str(source)], capture_output=True, text=True,
                                           check=True, timeout=30)
                    info = json.loads(probe.stdout)
                    stream = next(s for s in info['streams'] if s['codec_type'] ==
                                  ('video' if item['type'] == 'video_url' else 'audio'))
                    duration = float(info['format']['duration'])
                except (OSError, subprocess.SubprocessError, ValueError, KeyError, StopIteration) as exc:
                    raise ValueError(f'cannot probe {role}; install ffprobe and provide decodable media') from exc
                containers = set(info['format'].get('format_name', '').split(','))
                if item['type'] == 'video_url':
                    if not containers.intersection({'mov', 'mp4'}) or mime not in {'video/mp4', 'video/quicktime'}:
                        raise ValueError('reference video must be MP4/MOV with matching MIME')
                    if any(s.get('codec_name') not in {'aac', 'mp3'} for s in info['streams'] if s.get('codec_type') == 'audio'):
                        raise ValueError('reference video audio must use AAC or MP3')
                elif not ((containers == {'wav'} and mime in {'audio/wav', 'audio/x-wav', 'audio/vnd.wave'})
                          or (containers == {'mp3'} and mime in {'audio/mpeg', 'audio/mp3'})):
                    raise ValueError('reference audio must be WAV/MP3 with matching MIME')
                if not 2 <= duration <= 15:
                    raise ValueError(f'{role} must last 2–15 seconds')
                seconds[role] += duration
                entry['duration'] = duration
                if item['type'] == 'video_url':
                    if stream.get('codec_name') not in ('h264', 'hevc'):
                        raise ValueError('reference video must use H.264 or HEVC')
                    try:
                        n, d = stream['avg_frame_rate'].split('/')
                        fps = float(n) / float(d)
                    except (KeyError,ValueError,TypeError,ZeroDivisionError) as exc:
                        raise ValueError('reference video frame rate is unavailable') from exc
                    if not 23.975 <= fps <= 60:
                        raise ValueError('reference video frame rate must be 23.976–60')
                    width, height = stream['width'], stream['height']
                    entry.update(size=[width, height], fps=fps)
        if 'size' in entry:
            width, height = entry['size']
            if not (256 <= width <= 5760 and 256 <= height <= 5760 and .4 <= width/height <= 2.5):
                raise ValueError(f'{role} size/ratio outside the documented input range')
        inventory.append(entry)
    for role, maximum in [('first_frame', 1), ('last_frame', 1), ('reference_image', 9),
                          ('reference_video', 3), ('reference_audio', 3)]:
        if counts.get(role, 0) > maximum:
            raise ValueError(f'too many {role} inputs')
    if sum(v for k, v in counts.items() if k.startswith('reference_')) > 12:
        raise ValueError('reference media total exceeds 12')
    if any(v > 15.001 for v in seconds.values()):
        raise ValueError('reference video/audio aggregate duration exceeds 15 seconds per modality')
    if counts.get('reference_audio') and not (counts.get('reference_image') or counts.get('reference_video')):
        raise ValueError('reference audio needs a visual reference')
    return inventory


def plan_hash(plan):
    return request_hash({k: v for k, v in plan.items() if k != 'evidence'})


def review_template(spec, body, base_dir, identity, output):
    identity = Path(identity).resolve()
    if not identity.is_file():
        raise ValueError('identity baseline must exist')
    inventory = media_inventory(body['content'])
    if len(json.dumps(body).encode()) > 64 * 1024**2:
        raise ValueError('encoded request exceeds 64 MB')
    import os
    return dict(schemaVersion=1, requestSha256=request_hash(body),
                planSha256=plan_hash(spec['motionPlan']),
                identityBaseline=dict(path=os.path.relpath(identity, output.parent), sha256=digest(identity)),
                media=inventory, checks={name: dict(status='unreviewed', notes='') for name in CHECKS},
                interpretation='human-input-review-only-not-generated-motion-proof')


def validate_review(path, body, plan=None):
    review = json.loads(path.read_text(encoding='utf-8'))
    if review.get('schemaVersion') != 1 or review.get('requestSha256') != request_hash(body):
        raise ValueError('input review is missing or stale for the actual request; regenerate and inspect changed inputs')
    if plan is not None and review.get('planSha256') != plan_hash(plan):
        raise ValueError('input review is stale for the motion plan')
    baseline = review.get('identityBaseline', {})
    target = path.parent / baseline.get('path', '')
    if not target.is_file() or digest(target) != baseline.get('sha256'):
        raise ValueError('identity baseline changed or is missing')
    if review.get('media') != media_inventory(body['content']):
        raise ValueError('input media inventory does not match submitted bytes')
    limitations = []
    for name in CHECKS:
        check = review.get('checks', {}).get(name, {})
        state, notes = check.get('status'), check.get('notes')
        if state not in ('pass', 'limited', 'not-applicable') or not isinstance(notes, str) or not notes.strip():
            raise ValueError(f'input check {name} needs an observation; fail/unreviewed cannot authorize generation')
        if name == 'subjectIsolation' and state != 'pass':
            raise ValueError('subjectIsolation must pass: inspect one animated target, clarity and motion room; static context is allowed')
        if state == 'limited':
            limitations.append(dict(check=name, notes=notes))
    return dict(inputReviewSha256=digest(path), limitations=limitations,
                validation='binding-and-recorded-observations-only')


def validate_requirements(plan, content):
    requirements = plan.get('requirements')
    if not isinstance(requirements, dict) or set(requirements) != set(REQUIREMENTS):
        raise ValueError('motionPlan.requirements must cover identity, motion, range, gaze, fixedParts, loop and rest')
    roles = {i.get('role') for i in content}
    warnings = []
    for name, rule in requirements.items():
        if not isinstance(rule, dict) or any(not isinstance(rule.get(k), str) or not rule[k].strip()
                                             for k in ('expected', 'verify')):
            raise ValueError(f'{name} needs observable expected and verify descriptions')
        controls = rule.get('controls')
        if not isinstance(controls, list) or not controls:
            raise ValueError(f'{name} needs actual control sources')
        for control in controls:
            if control not in ('prompt', 'compositing', 'runtime', 'not-requested') and control not in roles:
                raise ValueError(f'{name} claims an unavailable control: {control}')
        if controls == ['prompt']:
            warnings.append(f'{name}: text-only guidance, no visual/path control')
    return warnings


def archive_inputs(output_dir, body, review_path, expected_review_hash):
    """Keep exact submitted bytes so later edits cannot erase the input evidence."""
    review_bytes=review_path.read_bytes()
    review=json.loads(review_bytes)
    if (hashlib.sha256(review_bytes).hexdigest()!=expected_review_hash
            or review.get('requestSha256')!=request_hash(body)):
        raise ValueError('input review changed before submission')
    baseline=review_path.parent/review['identityBaseline']['path']
    identity=baseline.read_bytes()
    if hashlib.sha256(identity).hexdigest()!=review['identityBaseline']['sha256']:
        raise ValueError('identity baseline changed before submission')
    folder=output_dir/'inputs'
    folder.mkdir(exist_ok=False)
    def save(name,raw):
        with (folder/name).open('xb') as stream:stream.write(raw)
        return dict(path='inputs/'+name,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
    records=[];counts={}
    for item in body['content']:
        if item['type']=='text':continue
        uri=item[item['type']]['url'];header,encoded=uri.split(',',1)
        mime=header[5:].split(';')[0]
        suffix={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp','video/mp4':'.mp4',
                'video/quicktime':'.mov','audio/mpeg':'.mp3','audio/wav':'.wav'}.get(mime,'.bin')
        role=item['role'];index=counts.get(role,0);counts[role]=index+1
        records.append(dict(role=role,index=index,mimeType=mime,
                            **save(f'{role}-{index}{suffix}',base64.b64decode(encoded,validate=True))))
    # The verbatim review baseline path was relative to its original location.
    # The explicit identity record locates the archived copy.
    return dict(media=records,identityBaseline=save('identity-baseline'+baseline.suffix,identity),
                inputReview=save('input-review.snapshot.json',review_bytes),
                reviewOriginalPath=str(review_path.resolve()),requestSha256=request_hash(body))


def provider_observation(response, previous=None):
    """An absent expanded prompt does not mean the original was used unchanged."""
    result = dict(previous or {})
    result.setdefault('effectivePromptStatus', 'not-returned-or-undisclosed')
    candidates = [response]
    if isinstance(response.get('content'), dict):
        candidates.append(response['content'])
    for candidate in candidates:
        expanded = candidate.get('expanded_prompt')
        if isinstance(expanded, str) and expanded.strip():
            result.update(effectivePromptStatus='provider-returned',
                          expandedPromptSha256=hashlib.sha256(expanded.encode()).hexdigest(),
                          expandedPrompt=re.sub(r'https?://\S+|data:[^\s]+', '[media address omitted]', expanded))
        if type(candidate.get('seed')) is int:
            result['returnedSeed'] = candidate['seed']
    return result
