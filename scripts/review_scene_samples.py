"""Composite a few native video frames into the actual scene before full processing.

Uses compiler coordinates and background operations. Optional sample mattes and a
foreground overlay are prototypes, not automatically installed runtime assets.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw
from compile_head_atlas import patch_with_background, fit_light_background, feather_patch, parse_key_color, sample_border_key


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024*1024), b''):
            value.update(chunk)
    return value.hexdigest()


def read_image(path):
    with Image.open(path) as image:
        return image.convert('RGBA')


def rect(value, size, name):
    if not isinstance(value, (list, tuple)) or len(value) != 4 or any(type(v) is not int for v in value):
        raise ValueError(f'{name} must be integer x y width height')
    x,y,w,h = value
    if min(x,y) < 0 or min(w,h) <= 0 or x+w > size[0] or y+h > size[1]:
        raise ValueError(f'{name} is outside its coordinate space')
    return x,y,w,h


def extract(video, indices, size, output):
    info = json.loads(subprocess.run(['ffprobe','-v','error','-select_streams','v:0',
        '-show_frames','-show_entries','stream=width,height:frame=best_effort_timestamp_time',
        '-of','json',str(video)], check=True, capture_output=True, text=True).stdout)
    stream = info['streams'][0]
    if abs(stream['width']/stream['height']-size[0]/size[1]) > .005:
        raise ValueError('renderSize must preserve the native video aspect ratio')
    if indices[-1] >= len(info['frames']):
        raise ValueError('sample frame is outside the native video')
    select = '+'.join(f'eq(n\\,{i})' for i in indices)
    subprocess.run(['ffmpeg','-v','error','-noautorotate','-i',str(video),'-map','0:v:0','-vf',
        f'select={select},scale={size[0]}:{size[1]}:flags=lanczos','-fps_mode','passthrough',
        '-start_number','0',str(output/'%06d.png')], check=True, capture_output=True)
    paths = sorted(output.glob('*.png'))
    if len(paths) != len(indices):
        raise ValueError('selected decode count differs from source indices')
    return paths, [info['frames'][i].get('best_effort_timestamp_time') for i in indices]


def review(spec, root, output, indices):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('preserve existing scene samples; choose a new output')
    if not isinstance(indices, (list, tuple)) or not 1 <= len(indices) <= 12 or any(type(i) is not int or i < 0 for i in indices) or len(set(indices)) != len(indices):
        raise ValueError('choose 1..12 unique native source frame indices')
    indices = sorted(indices)
    base = read_image(root/spec['baseImage'])
    if list(base.size) != spec['sourceSize']:
        raise ValueError('base dimensions differ from sourceSize')
    x,y,w,h = rect(spec['crop'], base.size, 'crop')
    size = spec['renderSize']
    if type(size) is int:
        size = [size,size]
    if not isinstance(size, list) or len(size) != 2 or any(type(v) is not int or v < 1 for v in size):
        raise ValueError('renderSize must be positive integer or [width,height]')
    mx,my,mw,mh = rect(spec.get('motionCrop', [0,0,w,h]), size, 'motionCrop')
    if (mw,mh) != (w,h):
        raise ValueError('motionCrop must match crop cell dimensions')
    owner, mode = spec.get('backgroundOwner'), spec.get('backgroundMode')
    if owner not in ('scene','page') or mode not in ('preserve','fit-edge-light','chroma-key'):
        raise ValueError('choose scene/preserve, scene/fit-edge-light or page/preserve/chroma-key')
    if (mode=='chroma-key' and owner!='page') or (mode=='fit-edge-light' and owner!='scene'):
        raise ValueError('background mode and owner disagree')
    mattes = spec.get('sampleMattes', {})
    if not isinstance(mattes, dict) or any(k not in {str(i) for i in indices} for k in mattes):
        raise ValueError('sampleMattes keys must correspond to selected source frame indices')
    if mattes and (owner,mode) != ('page','preserve'):
        raise ValueError('sampleMattes require page/preserve and a cleanPlate')
    paths = {spec['baseImage'], spec['sourceVideo'], *mattes.values()}
    plate = base
    if owner == 'page':
        if not spec.get('cleanPlate'):
            raise ValueError('page mode needs a cleanPlate with the old subject removed')
        paths.add(spec['cleanPlate']); plate = read_image(root/spec['cleanPlate'])
        if plate.size != base.size:
            raise ValueError('cleanPlate dimensions must match the scene')
    overlay = None
    if spec.get('foregroundOverlay'):
        paths.add(spec['foregroundOverlay']); overlay = read_image(root/spec['foregroundOverlay'])
        if overlay.size != base.size or overlay.getchannel('A').getextrema() == (255,255):
            raise ValueError('foregroundOverlay must be scene-sized with actual transparency')
    hashes = {name:digest(root/name) for name in sorted(paths)}
    base_crop = np.asarray(base.crop((x,y,x+w,y+h)).convert('RGB'))
    if mode == 'fit-edge-light':
        base_crop = fit_light_background(base_crop)
    low, high = spec.get('transparentThreshold',12), spec.get('opaqueThreshold',220)
    if any(type(v) is not int for v in (low,high)) or not 0 <= low < high <= 255:
        raise ValueError('key thresholds must satisfy 0 <= transparent < opaque <= 255')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.'+output.name+'-', dir=output.parent) as folder:
        work=Path(folder); decoded=work/'decoded'; decoded.mkdir(); staged=work/'samples'; staged.mkdir()
        # Auto color is sampled at source frame zero, exactly as the compiler does.
        extraction = sorted(set(indices+[0])) if mode=='chroma-key' and spec.get('keyColor')=='auto' else indices
        decoded_paths, timestamps = extract(root/spec['sourceVideo'], extraction, size, decoded)
        decoded_map = dict(zip(extraction,decoded_paths)); time_map = dict(zip(extraction,timestamps))
        key = None
        if mode == 'chroma-key':
            color = spec.get('keyColor')
            if not isinstance(color,str):
                raise ValueError('chroma-key requires keyColor')
            key = sample_border_key(np.asarray(read_image(decoded_map[0]))) if color=='auto' else parse_key_color(color)
        entries=[]; previews=[]
        for i in indices:
            frame = read_image(decoded_map[i])
            if str(i) in mattes:
                with Image.open(root/mattes[str(i)]) as matte:
                    if matte.size != tuple(size) or matte.mode != 'L':
                        raise ValueError('sample matte must be grayscale L at renderSize; no implicit resize')
                    alpha = np.asarray(matte).astype(np.uint16)*np.asarray(frame.getchannel('A')).astype(np.uint16)//255
                    frame.putalpha(Image.fromarray(alpha.astype(np.uint8)))
            if owner=='page' and mode=='preserve' and frame.getchannel('A').getextrema() == (255,255):
                raise ValueError(f'source frame {i} has no alpha; supply an inspected sample matte')
            patch = patch_with_background(np.asarray(frame)[my:my+h,mx:mx+w],base_crop,mode,key,low,high)
            if owner == 'scene':
                patch = feather_patch(patch,spec)
            scene = base.copy()
            scene.paste(plate.crop((x,y,x+w,y+h)),(x,y))
            scene.alpha_composite(patch,(x,y))
            if overlay is not None:
                scene.alpha_composite(overlay)
            prefix=f'source-{i:06}'
            patch.save(staged/(prefix+'-patch.png'))
            scene.save(staged/(prefix+'-scene.png'))
            bounds=(max(0,x-24),max(0,y-24),min(base.width,x+w+24),min(base.height,y+h+24))
            scene.crop(bounds).save(staged/(prefix+'-detail.png'))
            thumb=scene.convert('RGB'); thumb.thumbnail((480,360)); previews.append((i,thumb))
            entries.append(dict(sourceFrame=i,timestamp=time_map[i],scene=prefix+'-scene.png',detail=prefix+'-detail.png',
                patch=prefix+'-patch.png',head='unknown',gaze='unknown',neck='unknown',oldOutline='unknown',
                background='unknown',occlusion='unknown',notes=''))
        cw,ch=previews[0][1].size; board=Image.new('RGB',(cw*3,(ch+24)*((len(previews)+2)//3)), '#dddddd')
        draw=ImageDraw.Draw(board)
        for j,(i,thumb) in enumerate(previews):
            px,py=j%3*cw,j//3*(ch+24); board.paste(thumb,(px,py+24)); draw.text((px+4,py+4),f'source {i} / UNREVIEWED',fill='black')
        board.save(staged/'contact.jpg',quality=93)
        base.save(staged/'original.png')
        limitations = ['Representative composites are not full-frame, gaze, browser or interaction acceptance.',
                      'No automatic segmentation, clean-plate reconstruction or semantic judgment.',
                      'Sample mattes must be extended and checked over all used frames before production.',
                      'foregroundOverlay requires an equivalent foreground layer above the runtime canvases.']
        report=dict(schemaVersion=1,status='unreviewed',source=spec['sourceVideo'],inputs=hashes,recipe=spec,
                    samples=entries,limitations=limitations,contactSheet='contact.jpg',original='original.png',
                    decision=dict(nextAction='unreviewed',reason=''),browserInteraction='not-tested')
        (staged/'scene-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if any(digest(root/name)!=sha for name,sha in hashes.items()):
            raise ValueError('input changed during sample export')
        if output.exists():
            raise ValueError('output appeared during export')
        staged.rename(output)
    return report


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('spec',type=Path); p.add_argument('--root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--frames',type=int,nargs='+',required=True)
    a=p.parse_args()
    report=review(json.loads(a.spec.read_text(encoding='utf-8')),a.root,a.output,a.frames)
    print(json.dumps(dict(status=report['status'],samples=len(report['samples']))))
