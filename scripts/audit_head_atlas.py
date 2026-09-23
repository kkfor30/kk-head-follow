"""Audit a candidate, bind review evidence, optionally enable the runtime."""
import argparse
import json
from pathlib import Path
from atlas_quality import read, digest, assess, review_template
from validate_head_manifest import validate


def audit(path, root, output, review_path=None, approve=False):
    m = read(path)
    protected=[path, root/m['baseImage'], *[path.parent/p for p in m['sheets']],
               *[root/p for p in m.get('sourceHashes',{})]]
    if m.get('cleanPlate'):protected.append(root/m['cleanPlate']['path'])
    if review_path:protected.append(review_path)
    if output.resolve() in {p.resolve() for p in protected}:
        raise ValueError('quality report cannot overwrite the manifest, review input or media')
    def revoke(issues):
        if m.get('quality', {}).get('status') == 'reviewed':
            m['quality'] = dict(status='blocked', circular=False, issues=issues)
            path.write_text(json.dumps(m, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    try:
        validate(root, path)
        report = assess(m, path, root, read(review_path) if review_path else None)
    except Exception as exc:
        revoke(['recheck-error: ' + str(exc)])
        raise
    if report['status'] != 'reviewed':
        revoke(report['issues'])
    output.parent.mkdir(parents=True, exist_ok=True)
    # The certificate stays adjacent to the manifest so a browser can verify it.
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    if approve:
        if report['status'] != 'reviewed':
            raise ValueError('approval refused: ' + ', '.join(report['issues']))
        import os
        m['quality'] = dict(status='reviewed', circular=True, binding=report['binding'],
                            report=os.path.relpath(output, path.parent).replace('\\', '/'), reportSha256=digest(output))
        path.write_text(json.dumps(m, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('manifest', type=Path)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output', type=Path)
    p.add_argument('--review', type=Path)
    p.add_argument('--write-review-template', type=Path)
    p.add_argument('--approve', action='store_true')
    a = p.parse_args()
    path, root = a.manifest.resolve(), a.root.resolve()
    if a.write_review_template:
        if a.write_review_template.exists():
            p.error('refusing to overwrite existing observations')
        a.write_review_template.parent.mkdir(parents=True, exist_ok=True)
        a.write_review_template.write_text(json.dumps(review_template(read(path), path, root), indent=2)+'\n', encoding='utf-8')
    r = audit(path, root, a.output or path.with_name('quality-report.json'), a.review, a.approve)
    print(json.dumps(dict(status=r['status'], issues=r['issues']), indent=2))
