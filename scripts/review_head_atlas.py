"""Build exhaustive scene-composited evidence; never certify visual quality."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from inspect_atlas_seams import transition_metrics


def sweep_indices(count):
    # Exercise both wrap directions, rather than bouncing at the last frame.
    return list(range(count))*2 + [0] + list(range(count-1,-1,-1))*2


def review(manifest_path, root, output):
    m = json.loads(manifest_path.read_text(encoding='utf-8'))
    base = Image.open(root / m['baseImage']).convert('RGBA')
    if hashlib.sha256((root / m['baseImage']).read_bytes()).hexdigest() != m['baseImageSha256']:
        raise ValueError('Base image hash mismatch')
    x, y, w, h = m['crop']
    plate = base
    if m.get('background', {}).get('owner') == 'page':
        name = (m.get('cleanPlate') or {}).get('path')
        if not name:
            raise ValueError('page mode requires cleanPlate')
        plate = Image.open(root / name).convert('RGBA')
    if plate.size != base.size:
        raise ValueError('Plate size mismatch')
    sheets = [Image.open(manifest_path.parent / s).convert('RGBA') for s in m['sheets']]
    frames, scenes = [], []
    margin = 24
    bounds = (max(0,x-margin), max(0,y-margin), min(base.width,x+w+margin), min(base.height,y+h+margin))
    for i in range(m['frameCount']):
        sheet, cell = divmod(i,m['framesPerSheet'])
        sx, sy = cell % m['columns']*w, cell // m['columns']*h
        patch = sheets[sheet].crop((sx,sy,sx+w,sy+h))
        scene = base.copy()
        scene.paste(plate.crop((x,y,x+w,y+h)), (x,y))
        scene.alpha_composite(patch,(x,y))
        frames.append(scene.crop(bounds).convert('RGB'))
        scene.thumbnail((900,675))
        scenes.append(scene.convert('RGB'))
    output.mkdir(parents=True,exist_ok=True)
    provenance = m.get('frameSources', [])
    synthetic = [i for i,s in enumerate(provenance) if s.get('synthesized')]
    selected = sorted({j % len(frames) for i in synthetic for j in (i-1,i,i+1)})
    def contact(ids, prefix):
        cw,ch = frames[0].size
        for page,start in enumerate(range(0,len(ids),12)):
            batch=ids[start:start+12]
            grid=Image.new('RGB',(cw*4,(ch+28)*((len(batch)+3)//4)),'white')
            draw=ImageDraw.Draw(grid)
            for pos,i in enumerate(batch):
                px,py=pos%4*cw,pos//4*(ch+28)
                src=provenance[i] if provenance else {}
                draw.text((px+3,py+5),f"atlas {i} / source {src.get('frame','?')} / {'SYNTH' if i in synthetic else 'native'}",fill='black')
                grid.paste(frames[i],(px,py+28))
            grid.save(output/f'{prefix}-{page:02}.png')
    contact(list(range(len(frames))),'all')
    contact(selected,'repair')
    # Deterministic frame sweeps test asset continuity, not browser events/performance.
    path=sweep_indices(len(frames))
    scenes[path[0]].save(output/'scene-sweep.webp',save_all=True,
        append_images=[scenes[i] for i in path[1:]],duration=55,loop=0,lossless=True)
    frames[path[0]].save(output/'detail-sweep.webp',save_all=True,
        append_images=[frames[i] for i in path[1:]],duration=80,loop=0,lossless=True)
    metrics=transition_metrics([np.asarray(f) for f in frames])
    report=dict(manifestSha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        frameCount=len(frames),syntheticFrames=synthetic,metrics=metrics,
        inspectionRequired=['all repair sheets','all native sheets','scene and detail sweeps'],
        status='evidence-ready-not-visually-reviewed',browserInteraction='not-tested',sweepFrameIndices=path,
        limitations=['Metrics do not identify gaze, ghosting, roll or motion direction.',
                      'Frame sweeps do not exercise the pointer controller.'])
    (output/'review.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('manifest',type=Path)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    r=review(a.manifest.resolve(),a.root.resolve(),a.output.resolve())
    print(json.dumps({k:v for k,v in r.items() if k!='metrics'},indent=2))
