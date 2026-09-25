"""Assemble the submitted prompt from the motion plan; no model or API calls."""
import re
from pathlib import Path


DIRECTIONS = ('up', 'upper-right', 'right', 'lower-right', 'down', 'lower-left', 'left', 'upper-left', 'up')
BACKGROUND_MODES = {'scene-preserve', 'chroma-key', 'alpha-matte'}
PLACEHOLDER = re.compile(r'\{\{[^}]+\}\}|\[(?:ACTUAL|ALLOWED|PATH|OBSERVABLE|DESIRED|TASK|SUBJECT|FIXED|ENDING|RELEVANT)[A-Z _-]*\]|replace-with-', re.I)


def prose(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} needs a concrete description')
    if PLACEHOLDER.search(value):
        raise ValueError(f'{name} contains an unfinished placeholder')
    return value.strip()


def checkpoints(plan, prompt_spec):
    """Fractions describe intended pacing, never observed frame labels."""
    kind = plan.get('kind')
    timing = prompt_spec.get('timing', {})
    if not isinstance(timing, dict):
        raise ValueError('promptSpec.timing must be an object')
    if kind == 'entry-orbit':
        if set(timing) - {'entryEnd', 'cycleEnd'}:
            raise ValueError('entry-orbit timing supports only entryEnd and cycleEnd')
        start, end = timing.get('entryEnd', .12), timing.get('cycleEnd', .88)
        if any(type(v) not in (int, float) for v in (start, end)) or not 0 < start < end <= 1:
            raise ValueError('entry timing must satisfy 0 < entryEnd < cycleEnd <= 1')
        return [(0, 'neutral')] + [(start+(end-start)*i/8, d) for i,d in enumerate(DIRECTIONS)] + ([(1, 'neutral')] if end < 1 else [])
    if timing:
        raise ValueError('timing overrides apply only to entry-orbit')
    if kind == 'closed-orbit':
        return [(i/8, d) for i,d in enumerate(DIRECTIONS)]
    if kind == 'upper-arc':
        return [(0, 'upper-left'), (.5, 'up'), (1, 'upper-right')]
    if kind == 'segment':
        return [(0, prose(plan.get('startDirection'), 'startDirection')),
                (.5, prose(plan.get('via'), 'via')),
                (1, prose(plan.get('endDirection'), 'endDirection'))]
    if kind in ('reference-motion', 'diagnostic'):
        return []
    raise ValueError('unknown motionPlan.kind')


def assemble_prompt(spec):
    plan = spec.get('motionPlan', {})
    if not isinstance(plan, dict):
        raise ValueError('motionPlan must be an object')
    ps = plan.get('promptSpec')
    if not isinstance(ps, dict):
        raise ValueError('motionPlan.promptSpec must be an object')
    fields = {'subjectDescription', 'startPose', 'endPose', 'allowedMotion', 'framing', 'background', 'staticContext', 'timing'}
    if set(ps) - fields:
        raise ValueError(f'unknown promptSpec fields: {sorted(set(ps)-fields)}')
    values = {name: prose(ps.get(name), 'promptSpec.'+name) for name in
              ('subjectDescription', 'startPose', 'endPose', 'allowedMotion', 'framing')}
    subjects = plan.get('subjects')
    if not isinstance(subjects, list) or len(subjects) != 1:
        raise ValueError('motionPlan.subjects must name exactly one animated subject')
    prose(subjects[0], 'motionPlan.subjects[0]')
    bg = ps.get('background')
    if not isinstance(bg, dict) or bg.get('mode') not in BACKGROUND_MODES or set(bg)-{'mode','description','keyColor'}:
        raise ValueError('promptSpec.background needs mode and description: scene-preserve, chroma-key or alpha-matte')
    description = prose(bg.get('description'), 'background.description')
    if bg['mode'] == 'chroma-key':
        color = bg.get('keyColor', '')
        if not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise ValueError('chroma-key needs the actual six-digit keyColor used in the input image')
        background = f'Keep the supplied uniform {color} color-key backdrop uniform, with no new scenery or cast shadows on it. {description}'
    else:
        if 'keyColor' in bg:
            raise ValueError('keyColor applies only to chroma-key')
        background = ('Preserve the supplied scene and lighting. ' if bg['mode']=='scene-preserve' else
                      'Keep the supplied background and foreground boundaries stable for later foreground extraction. ') + description
    kind = plan.get('kind')
    points = checkpoints(plan, ps)
    lines = [f"One continuous fixed-camera shot. Animate only {values['subjectDescription']}.",
             f"Starting appearance and pose: {values['startPose']}.",
             f"Allowed motion: {values['allowedMotion']}. Framing: {values['framing']}."]
    if ps.get('staticContext'):
        lines.append('Other visible context stays still: '+prose(ps['staticContext'], 'staticContext')+'.')
    if kind == 'reference-motion':
        lines.append(prose(plan.get('referenceRoles'), 'referenceRoles')+'. Transfer the demonstrated movement, not the reference performer, background or camera movement.')
    elif points:
        route = ' -> '.join(f'{fraction*100:g}% {direction}' for fraction,direction in points)
        lines += ['Directions refer to the viewer\'s screen, not the subject\'s anatomical left/right. The subject follows one unseen target; the camera does not orbit.',
                  'Intended continuous path: '+route+'. Timing is approximate; pass smoothly through the intermediate directions without posing or holding at each one.']
    if kind in ('closed-orbit', 'entry-orbit', 'segment'):
        lines.append('Horizontal target movement produces a readable face turn, changing nose direction and cheek exposure. Vertical target movement raises or lowers the chin. A sideways head lean must not substitute for those directions.')
    if kind == 'closed-orbit':
        lines.append('Begin moving from the supplied upward pose immediately. Complete exactly one full direction cycle back to that same pose; no neutral introduction or closing pose. Approach the end with motion that can continue into the beginning.')
    elif kind == 'entry-orbit':
        lines.append('The neutral entry is separate from the complete UP-to-UP cycle. Complete that entire cycle before any return to neutral; do not replace the upper arc with a nod toward the camera.')
    elif kind == 'upper-arc':
        lines.append('Use the entire shot for one upper sweep: upper-left through up to upper-right. Maintain the lifted-chin intention while turning horizontally. No lower arc, neutral excursion, loop or reversal.')
    elif kind == 'segment':
        lines.append('Make only this continuous segment, not an additional full circle. The via state identifies the route, not a held middle keyframe.')
    requirements = plan.get('requirements', {})
    if not isinstance(requirements, dict):
        raise ValueError('motionPlan.requirements must be an object')
    included = []
    for name, rule in requirements.items():
        if not isinstance(rule, dict) or not isinstance(rule.get('controls'), list):
            raise ValueError(f'requirements.{name} needs actual control sources')
        if 'prompt' in rule['controls']:
            lines.append(f'{name}: '+prose(rule.get('expected'), f'requirements.{name}.expected')+'.')
            included.append(name)
    lines += ['Background: '+background,
              'End appearance and pose: '+values['endPose']+'.',
              'Keep identity, expression and mouth state consistent with the supplied identity reference. Where eyes are visible, distinguish changing gaze direction from changing expression. Face visibility does not mean continuous eye contact with the camera.',
              'The frames will be stopped and traversed in either direction. Keep intended eye and mouth details readable during the usable motion, without an unrelated blink, speech or expression event. Do not render arrows, labels, text or a motion diagram.']
    return '\n'.join(lines), dict(mode='structured', recipe=kind, checkpoints=[dict(fraction=f, direction=d) for f,d in points],
                                  requirementsIncluded=included,
                                  requirementsNotSent=[k for k in requirements if k not in included],
                                  semanticAgreement='requires-input-review', timing='intent-not-observed-frames')


def resolve_prompt(spec, base_dir):
    plan = spec.get('motionPlan')
    structured = isinstance(plan, dict) and 'promptSpec' in plan
    manual = [key for key in ('prompt', 'prompt_file') if spec.get(key) is not None]
    if structured:
        if manual:
            raise ValueError('choose promptSpec or manual prompt/prompt_file; do not silently override either')
        return assemble_prompt(spec)
    if len(manual) != 1:
        raise ValueError('provide exactly one prompt, prompt_file or motionPlan.promptSpec')
    value = spec[manual[0]]
    if manual[0] == 'prompt_file':
        value = (Path(base_dir)/value).read_text(encoding='utf-8')
    return prose(value, 'prompt'), dict(mode='manual', semanticAgreement='requires-input-review')
