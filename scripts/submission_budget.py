"""Local submission accounting. A reservation is never refunded automatically."""
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def write_atomic(path, value):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def request_hash(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def check_limits(data, body):
    """Seconds are request accounting, not a currency quote or decoded length."""
    limits = data.get('limits', {})
    if not isinstance(limits, dict):
        raise ValueError('limits must be an object')
    seconds = body.get('duration')
    if type(seconds) not in (int, float) or not 0 < seconds < float('inf'):
        raise ValueError('seconds budget requires a finite positive duration; frame-count requests need a separately implemented cost contract')
    per = limits.get('maxSecondsPerSubmission', 5)
    total = limits.get('maxTotalSeconds', data['maxSubmissions'] * 5)
    if any(type(v) not in (int, float) or not 0 < v < float('inf') for v in (per, total)):
        raise ValueError('duration limits must be finite positive numbers')
    models = limits.get('models', ['minimax/minimax-h3-max'])
    resolutions = limits.get('resolutions', ['768p'])
    if not isinstance(models, list) or not models or not all(isinstance(v,str) and v for v in models):
        raise ValueError('limits.models must be a nonempty model list')
    if not isinstance(resolutions, list) or not resolutions or not all(isinstance(v,str) and v for v in resolutions):
        raise ValueError('limits.resolutions must be a nonempty resolution list')
    if body.get('model') not in models or body.get('resolution') not in resolutions:
        raise ValueError('model or resolution outside the recorded budget')
    if seconds > per:
        raise ValueError('duration exceeds maxSecondsPerSubmission (default 5); do not silently enlarge the budget')
    used = 0
    for attempt in data['attempts']:
        prior = attempt.get('requestedSeconds') if isinstance(attempt,dict) else None
        if type(prior) not in (int,float) or not 0 < prior < float('inf'):
            raise ValueError('prior attempt has no trustworthy requestedSeconds; reconcile its original request before submitting')
        used += prior
    if used + seconds > total:
        raise ValueError('total requested seconds budget exhausted')
    if (per > 5 or total > data['maxSubmissions'] * 5 or models != ['minimax/minimax-h3-max']
            or resolutions != ['768p']) and not str(limits.get('changeReason','')).strip():
        raise ValueError('expanded cost limits require an explicit changeReason backed by user scope')
    references = [v for v in body.get('content',[]) if v.get('role') in ('reference_video','reference_audio')]
    if references and (limits.get('allowReferenceMedia') is not True or not str(limits.get('changeReason','')).strip()):
        raise ValueError('reference video/audio can incur input costs; record limits.allowReferenceMedia and changeReason within user scope')
    return dict(requestedSeconds=seconds, model=body['model'], resolution=body['resolution'],
                referenceMediaCount=len(references))


def check_stage(context, base_dir, attempts, body=None, budget_dir=None):
    context = context or {'stage': 'pilot'}
    stage = context.get('stage')
    if stage == 'pilot':
        if attempts:
            raise ValueError('pilot already attempted; use repair or a verified expansion, not another pilot')
    elif stage == 'expansion':
        from validate_head_manifest import validate
        root = (base_dir / context['root']).resolve()
        manifest = (root / context['pilotManifest']).resolve()
        validate(root, manifest, require_ready=True)
        manifest_data=json.loads(manifest.read_text(encoding='utf-8'))
        prior_budget=budget_dir or base_dir
        records=attempts
        if context.get('pilotBudget'):
            prior_path=(base_dir/context['pilotBudget']).resolve()
            prior_budget=prior_path.parent
            records=json.loads(prior_path.read_text(encoding='utf-8'))['attempts']
        matches=[r for r in records if r.get('requestSha256')==context.get('pilotRequestSha256') and r.get('stage')=='pilot']
        if len(matches)!=1:
            raise ValueError('expansion must reference one recorded pilotRequestSha256')
        pilot=matches[0]
        source=(prior_budget/pilot['outputDir']/'result.mp4').resolve()
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() not in manifest_data.get('sourceHashes',{}).values():
            raise ValueError('approved manifest does not contain the recorded pilot video')
        if not context.get('sceneId') or context['sceneId']!=manifest_data.get('sceneId'):
            raise ValueError('expansion sceneId must match the reviewed pilot scene')
        return dict(stage=stage, pilotManifestSha256=hashlib.sha256(manifest.read_bytes()).hexdigest())
    elif stage == 'repair':
        source = (base_dir / context['sourceVideo']).resolve()
        evidence = (base_dir / context['defectEvidence']).resolve()
        if not source.is_file() or not evidence.is_file() or not evidence.stat().st_size:
            raise ValueError('repair needs an existing sourceVideo and nonempty defectEvidence')
        policy = context.get('inputPolicy','source-frames')
        if policy == 'source-frames':
            verify_repair_inputs(source, context, body)
        elif policy == 'reviewed-replacement':
            # Reusing a failed frame is not mandatory when it carries the defect.
            from generation_controls import validate_review
            if not str(context.get('changeReason','')).strip() or not context.get('inputReview'):
                raise ValueError('replacement repair needs changeReason and request-bound inputReview')
            validate_review(base_dir/context['inputReview'], body)
            from validate_head_manifest import source_frame_count
            source_frame_count(str(source), hashlib.sha256(source.read_bytes()).hexdigest())
        else:
            raise ValueError('repair inputPolicy must be source-frames or reviewed-replacement')
        return dict(stage=stage, sourceSha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    defectSha256=hashlib.sha256(evidence.read_bytes()).hexdigest(), inputPolicy=policy)
    elif stage == 'segment':
        # A subsequent arc is not an expansion to another subject; it can precede full-loop approval.
        from generation_controls import validate_review
        source = (base_dir/context['previousVideo']).resolve()
        if not source.is_file() or not context.get('inputReview'):
            raise ValueError('segment needs previousVideo and a request-bound inputReview')
        validate_review(base_dir/context['inputReview'],body)
        first = [v for v in body.get('content',[]) if v.get('role')=='first_frame']
        if len(first)!=1 or not any(v.get('role')=='last_frame' for v in body.get('content',[])):
            raise ValueError('segment requires first and last frames')
        verify_repair_inputs(source, {'sourceInputs':[dict(role='first_frame',frame=context.get('previousFrame'))]},
                             {'content':first})
        return dict(stage=stage, sourceSha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    previousFrame=context['previousFrame'])
    else:
        raise ValueError('production.stage must be pilot, repair, segment or expansion')
    return dict(stage=stage)


def verify_repair_inputs(source, context, body):
    """Repair endpoints must be actual frames, not unrelated replacement portraits."""
    import base64
    import io
    import cv2
    import numpy as np
    from PIL import Image
    links=context.get('sourceInputs', [])
    roles={v.get('role'):v for v in (body or {}).get('content',[]) if v.get('type')=='image_url'}
    if not links or 'first_frame' not in roles or {v.get('role') for v in links}!=set(roles):
        raise ValueError('repair sourceInputs must bind every actual first/last image to a decoded source frame')
    cap=cv2.VideoCapture(str(source))
    try:
        if not cap.isOpened():raise ValueError('repair sourceVideo is not decodable')
        for link in links:
            index=link.get('frame')
            if type(index) is not int or not 0<=index<int(cap.get(cv2.CAP_PROP_FRAME_COUNT)):
                raise ValueError('repair source frame out of bounds')
            cap.set(cv2.CAP_PROP_POS_FRAMES,index);ok,pixels=cap.read()
            if not ok:raise ValueError('repair source frame decode failed')
            ref=Image.fromarray(cv2.cvtColor(pixels,cv2.COLOR_BGR2RGB))
            if link.get('renderSize'):ref=ref.resize(tuple(link['renderSize']),Image.Resampling.LANCZOS)
            if link.get('crop'):
                x,y,w,h=link['crop']
                if min(x,y)<0 or min(w,h)<=0 or x+w>ref.width or y+h>ref.height:raise ValueError('repair crop outside source')
                ref=ref.crop((x,y,x+w,y+h))
            uri=roles[link['role']]['image_url']['url']
            if not uri.startswith('data:image/') or ';base64,' not in uri:raise ValueError('repair uses local image inputs')
            actual=Image.open(io.BytesIO(base64.b64decode(uri.split(',',1)[1]))).convert('RGB')
            if actual.size!=ref.size:raise ValueError('repair input size does not match source transform')
            delta=np.abs(np.asarray(actual).astype(float)-np.asarray(ref).astype(float))
            if delta.mean()>2 or np.percentile(delta,95)>8:raise ValueError('repair image does not match declared source frame')
    finally:cap.release()


def submission_preflight(data, output_dir, body, context, base_dir, budget_dir):
    """Shared by dry-run and the locked reservation; has no side effects."""
    maximum, attempts = data.get('maxSubmissions'), data.get('attempts')
    if data.get('schemaVersion') != 1 or not isinstance(data.get('purpose'),str) or not data['purpose'].strip():
        raise ValueError('budget requires schemaVersion: 1 and a non-empty purpose')
    if type(maximum) is not int or maximum < 1 or not isinstance(attempts,list):
        raise ValueError('budget requires positive integer maxSubmissions and attempts array')
    if len(attempts) >= maximum:
        raise ValueError('submission budget exhausted; polling does not consume another submission')
    if any((output_dir/name).exists() for name in ('job.json','submission.json','result.mp4')):
        raise ValueError('output already has a submission or result; resume its job instead')
    if any(not isinstance(item,dict) or item.get('requestSha256')==request_hash(body) for item in attempts):
        raise ValueError('duplicate request or invalid attempt record; inspect the existing attempt')
    return check_limits(data,body), check_stage(context,base_dir,attempts,body,budget_dir)


def reserve(budget_path, output_dir, body, context=None, base_dir=None):
    budget_path = budget_path.resolve()
    output_dir = output_dir.resolve()
    lock = budget_path.with_name(budget_path.name + '.lock')
    try:
        lock.mkdir()
    except FileExistsError:
        raise ValueError('budget is locked; inspect an interrupted or concurrent submission before recovery')
    try:
        data = json.loads(budget_path.read_text(encoding='utf-8'))
        attempts = data.get('attempts')
        digest = request_hash(body)
        cost,stage = submission_preflight(data,output_dir,body,context,base_dir or budget_path.parent,budget_path.parent)
        record = dict(requestSha256=digest, state='reserved', createdAt=datetime.now(timezone.utc).isoformat(), **cost, **stage)
        # Exclusive marker also prevents two different budgets targeting the same output.
        with (output_dir / 'submission.json').open('x', encoding='utf-8') as stream:
            json.dump(record, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        attempts.append({**record, 'outputDir': os.path.relpath(output_dir, budget_path.parent)})
        write_atomic(budget_path, data)
        return record
    finally:
        lock.rmdir()
