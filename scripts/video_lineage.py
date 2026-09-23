"""Bind resampled video indices back to original native frames."""
import hashlib
import json
from densify_head_video import sample_sources


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def load_lineage(root, path, original, processed):
    report=json.loads((root/path).read_text(encoding='utf-8'))
    if report.get('sourceSha256')!=sha(root/original) or report.get('processedSha256')!=sha(root/processed):
        raise ValueError('lineage media hashes mismatch')
    expected=sample_sources(report['nativeCount'])
    rows=report.get('frames',[])
    if len(rows)!=len(expected) or report.get('frameCount')!=len(rows):
        raise ValueError('lineage frame count mismatch')
    for i,(row,wanted) in enumerate(zip(rows,expected)):
        if row.get('index')!=i or any(row.get(k)!=v for k,v in wanted.items()):
            raise ValueError('lineage contains inconsistent native/interpolated parents')
    return report,dict(path=path,sha256=sha(root/path),source=original,sourceSha256=sha(root/original),
                       processedSource=processed,processedSha256=sha(root/processed))


def annotate(origins, rows, original, processed):
    for item in origins:
        if item['source']!=processed:continue
        row=rows[item['frame']]
        item['nativeProvenance']=dict(source=original,parents=row['parents'],fraction=row['fraction'])
        if row['kind']=='interpolated':item['synthesized']=True


def validate_lineage(root,m):
    meta=m.get('frameLineage')
    if not meta:return
    report,actual=load_lineage(root,meta['path'],meta['source'],meta['processedSource'])
    if meta!=actual:raise ValueError('lineage binding changed')
    for item in m['frameSources']:
        if item['source']!=meta['processedSource']:continue
        row=report['frames'][item['frame']]
        expected=dict(source=meta['source'],parents=row['parents'],fraction=row['fraction'])
        if item.get('nativeProvenance')!=expected or (row['kind']=='interpolated' and item.get('synthesized') is not True):
            raise ValueError('derived atlas lost native/interpolated provenance')
