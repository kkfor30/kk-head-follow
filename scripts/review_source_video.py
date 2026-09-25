"""Cheap native-frame evidence before atlas compilation or repair.

All original decoded frame indices are retained, including VFR clips. The
thumbnails help an observer find usable motion; they never infer gaze or poses.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageDraw


def run(args):
    return subprocess.run([str(v) for v in args], check=True, capture_output=True, text=True)


def review(video, output, crop=None, max_side=240):
    video, output = Path(video).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('preserve existing source review; choose a new output')
    if type(max_side) is not int or not 64 <= max_side <= 640:
        raise ValueError('max-side must be 64..640; inspect original pixels for fine detail')
    info = json.loads(run(['ffprobe','-v','error','-select_streams','v:0','-show_frames',
                          '-show_entries','stream=width,height:frame=best_effort_timestamp_time',
                          '-of','json',video]).stdout)
    stream = info['streams'][0]
    source_size = [int(stream['width']), int(stream['height'])]
    crop = list(crop) if crop is not None else [0,0,*source_size]
    if len(crop) != 4 or any(type(v) is not int for v in crop):
        raise ValueError('crop must be integer x y width height in native video coordinates')
    x,y,w,h = crop
    if min(x,y) < 0 or min(w,h) <= 0 or x+w > source_size[0] or y+h > source_size[1]:
        raise ValueError('crop is outside native video')
    scale = min(1, max_side/max(w,h))
    size = (max(1, round(w*scale)), max(1, round(h*scale)))
    source_hash = hashlib.sha256(video.read_bytes()).hexdigest()
    times = [float(f['best_effort_timestamp_time']) if 'best_effort_timestamp_time' in f else None
             for f in info['frames']]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.'+output.name+'-', dir=output.parent) as td:
        work = Path(td); decoded=work/'decoded'; staged=work/'review'
        decoded.mkdir(); staged.mkdir()
        run(['ffmpeg','-v','error','-noautorotate','-i',video,'-map','0:v:0','-vf',
             f'crop={w}:{h}:{x}:{y},scale={size[0]}:{size[1]}:flags=lanczos',
             '-fps_mode','passthrough','-start_number','0',decoded/'%06d.png'])
        paths = sorted(decoded.glob('*.png'))
        if not paths or len(paths) != len(times):
            raise ValueError('decoded frames and source timestamps disagree')
        images = []
        pages = []
        for start in range(0,len(paths),12):
            batch=paths[start:start+12]; cw,ch=size[0],size[1]+26
            board=Image.new('RGB',(cw*4,ch*((len(batch)+3)//4)),'#eeeeee')
            draw=ImageDraw.Draw(board)
            for j,path in enumerate(batch):
                with Image.open(path) as im:
                    thumb=im.convert('RGB')
                images.append(thumb)
                index=start+j; px,py=(j%4)*cw,(j//4)*ch
                label=f'source {index}'+(f' / {times[index]:.3f}s' if times[index] is not None else '')
                draw.text((px+3,py+3),label,fill='black');board.paste(thumb,(px,py+26))
            name=f'contact-{start//12:03}.jpg';board.save(staged/name,quality=92)
            pages.append(dict(path=name,sourceFrames=list(range(start,start+len(batch)))))
        # Back-and-forth playback does not pretend that the endpoints form a loop.
        overview_indices=sorted({round(i*(len(images)-1)/max(1,min(24,len(images))-1))
                                 for i in range(min(24,len(images)))})
        cw,ch=size[0],size[1]+26
        overview=Image.new('RGB',(cw*6,ch*((len(overview_indices)+5)//6)),'#eeeeee')
        draw=ImageDraw.Draw(overview)
        for j,index in enumerate(overview_indices):
            px,py=(j%6)*cw,(j//6)*ch
            draw.text((px+3,py+3),f'source {index}',fill='black')
            overview.paste(images[index],(px,py+26))
        overview.save(staged/'overview.jpg',quality=92)
        sequence=list(range(len(images)))+list(range(len(images)-2,0,-1))
        images[0].save(staged/'source-sweep.webp',save_all=True,
                       append_images=[images[i] for i in sequence[1:]],duration=80,loop=0,lossless=True)
        report=dict(schemaVersion=1,source=str(video),sourceSha256=source_hash,
                    sourceSize=source_size,crop=crop,thumbnailSize=list(size),frameCount=len(paths),
                    sourceTimes=times,contactSheets=pages,sweepFrameIndices=sequence,
                    overview=dict(path='overview.jpg',sourceFrames=overview_indices,
                                  purpose='coarse triage only; does not replace full-frame review'),
                    sweepTiming='fixed 80ms for inspection, not original speed; endpoints are not joined',
                    observations=dict(directions=[],identity='unknown',gaze='unknown',expression='unknown',
                                      headAndGazeByDirection=[dict(direction=d,sourceFrame=None,head='unknown',
                                          gaze='unknown',eyeVisibility='unknown') for d in
                                          ('up','upper-right','right','lower-right','down','lower-left','left','upper-left')],
                                      bodyAndBackground='unknown',loop='unknown',entryAndExit='unknown',
                                      neutralCompatibility='unknown'),
                    decision=dict(mode='unreviewed',reason=''),
                    limitations='Thumbnails locate motion only. Verify unclear gaze and contours in original pixels; no automatic pose judgment.')
        (staged/'source-review.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        if hashlib.sha256(video.read_bytes()).hexdigest() != source_hash:
            raise ValueError('source changed during review export')
        if output.exists():
            raise ValueError('output appeared during export; preserve it')
        staged.rename(output)
    return report


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--crop',type=int,nargs=4)
    p.add_argument('--max-side',type=int,default=240)
    a=p.parse_args();r=review(a.video,a.output,a.crop,a.max_side)
    print(json.dumps(dict(frameCount=r['frameCount'],pages=len(r['contactSheets']),decision=r['decision'])))
