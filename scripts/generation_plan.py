"""Local production-plan checks, independent of API calls and submission budget."""
from pathlib import Path
import hashlib


def validate_plan(spec, content, base_dir):
    plan=spec.get('motionPlan')
    if not isinstance(plan,dict):
        raise ValueError('motionPlan is required: closed-orbit, entry-orbit, upper-arc or diagnostic')
    kind=plan.get('kind')
    if kind not in {'closed-orbit','entry-orbit','upper-arc','diagnostic'}:
        raise ValueError('unknown motionPlan.kind')
    if spec.get('duration') is None and spec.get('frames') is None:
        raise ValueError('choose an explicit supported duration or frame count; no implicit 5-second production plan')
    roles={item.get('role'):item for item in content if item.get('role') in {'first_frame','last_frame'}}
    if kind in {'closed-orbit','entry-orbit','upper-arc'}:
        if plan.get('coordinateSystem')!='screen' or plan.get('path')!='clockwise':
            raise ValueError('use screen-relative clockwise motion, not a horizontal head spin')
        if 'first_frame' not in roles:
            raise ValueError('this motion plan needs an actual first frame')
    if kind=='closed-orbit':
        if plan.get('seamDirection')!='up' or plan.get('seamPoseVerified') is not True:
            raise ValueError('closed-orbit needs a reviewed UP seam pose; neutral is not UP')
        if 'last_frame' not in roles:
            raise ValueError('closed-orbit needs an actual last_frame constraint; return_last_frame is not one')
        if roles['first_frame']['image_url']['url']!=roles['last_frame']['image_url']['url']:
            raise ValueError('closed-orbit must submit the same seam reference as first and last frame')
    if kind=='entry-orbit' and (plan.get('firstPose')!='neutral' or plan.get('cycleStart')!='up'
                                or plan.get('cycleEnd')!='up' or plan.get('excludeEntry') is not True):
        raise ValueError('entry-orbit must declare neutral entry separately from a complete UP-to-UP internal cycle')
    if kind=='upper-arc':
        if 'last_frame' not in roles or plan.get('startDirection')!='upper-left' or plan.get('endDirection')!='upper-right':
            raise ValueError('upper-arc requires actual upper-left / upper-right endpoint references')
    evidence=plan.get('evidence')
    if not isinstance(evidence,str) or not (base_dir/evidence).is_file():
        raise ValueError('motionPlan.evidence must name a local input/pose review file')
    if not str(plan.get('durationReason','')).strip():
        raise ValueError('record why the chosen duration covers the planned movement')
    return dict(**plan,evidenceSha256=hashlib.sha256((base_dir/evidence).read_bytes()).hexdigest(),
                validation='input-contract-only-not-motion-guarantee')
