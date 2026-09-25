"""Export the exact offline prompt used by generate_zenmux_video.py."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from generate_zenmux_video import prepare_request
from motion_prompt import resolve_prompt


def build(spec_path, output):
    spec_path, output = Path(spec_path).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('preserve existing prompt bundle; choose a new output')
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    # Reuse actual request validation (including real referenced files), without an input approval or API call.
    body, _, controls = prepare_request(spec, spec_path.parent, require_review=False)
    prompt, assembly = resolve_prompt(spec, spec_path.parent)
    if body['content'][0]['text'] != prompt:
        raise ValueError('prompt export and request disagree')
    report = dict(**assembly, promptSha256=hashlib.sha256(prompt.encode()).hexdigest(),
                  characters=len(prompt), warnings=controls['warnings'], status='unreviewed',
                  requirements=spec['motionPlan']['requirements'])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.'+output.name+'-', dir=output.parent) as folder:
        staged = Path(folder)/'bundle'; staged.mkdir()
        (staged/'prompt.txt').write_text(prompt, encoding='utf-8')
        (staged/'prompt-plan.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        if output.exists():
            raise ValueError('output appeared during export')
        staged.rename(output)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('spec', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    report = build(a.spec, a.output)
    print(json.dumps({k:report[k] for k in ('characters','promptSha256','status')}))
