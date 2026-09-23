"""Double the sampling of an already reviewed CFR motion clip, without looping it.

Native decoded pixels are retained exactly. FFmpeg motion compensation supplies
only odd (half-time) samples; no interpolation across the last-to-first edge.
Numeric success is not semantic or visual approval.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw


def run(argv):
    return subprocess.run([str(x) for x in argv], check=True, capture_output=True, text=True)


def sample_sources(count):
    if type(count) is not int or count < 3:
        raise ValueError('at least three native frames are required')
    return [dict(kind='native', parents=[i//2], fraction=0) if i%2 == 0
            else dict(kind='interpolated', parents=[i//2, i//2+1], fraction=.5)
            for i in range(count*2-1)]


def constant_rate(times, fps):
    if len(times)<3 or not np.isfinite(times).all() or not np.isfinite(fps) or fps<=0:
        raise ValueError('invalid timestamps or frame rate')
    if not np.allclose(np.diff(times), 1/fps, atol=max(.00002, .005/fps), rtol=0):
        raise ValueError('variable frame rate: normalize explicitly before densifying')


def densify(source, output, ffmpeg='ffmpeg', ffprobe='ffprobe', max_side=None):
    source,output=Path(source).resolve(),Path(output).resolve()
    if not source.is_file():raise ValueError('source video missing')
    if output.exists():raise ValueError('output must be new; preserve prior candidates')
    probe=json.loads(run([ffprobe,'-v','error','-select_streams','v:0','-show_frames',
                         '-show_entries','frame=best_effort_timestamp_time','-of','json',source]).stdout)
    times=np.array([float(f['best_effort_timestamp_time']) for f in probe['frames']])
    cap=cv2.VideoCapture(str(source))
    fps=cap.get(cv2.CAP_PROP_FPS)
    try:constant_rate(times,fps)
    except Exception:cap.release();raise
    if max_side is not None and (type(max_side) is not int or max_side<32):
        cap.release();raise ValueError('max-side must be at least 32')
    output.mkdir(parents=True)
    native=output/'native';raw=output/'interpolator-output';frames=output/'frames';review=output/'review'
    for p in (native,raw,frames,review):p.mkdir()
    count=0
    while True:
        ok,bgr=cap.read()
        if not ok:break
        rgb=Image.fromarray(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB))
        if max_side:rgb.thumbnail((max_side,max_side),Image.Resampling.LANCZOS)
        rgb.save(native/f'{count:06}.png');count+=1
    cap.release()
    if count!=len(times):raise ValueError('decoder and timestamp counts disagree')
    origins=sample_sources(count)
    rate=Fraction(str(fps)).limit_denominator(100000)
    target=rate*2
    # Two cloned context frames each side keep boundary interpolation defined.
    # These context frames are never exported and never constitute a loop repair.
    vf=f'tpad=start=2:stop=2:start_mode=clone:stop_mode=clone,minterpolate=fps={target}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1'
    command=[ffmpeg,'-hide_banner','-loglevel','error','-framerate',rate,
             '-start_number','0','-i',native/'%06d.png','-vf',vf,
             '-fps_mode','passthrough','-start_number','0',raw/'%06d.png']
    run(command)
    for index,item in enumerate(origins):
        src=native/f'{index//2:06}.png' if item['kind']=='native' else raw/f'{index+4:06}.png'
        if not src.is_file():raise ValueError(f'interpolator missing expected sample {index}; no duplicate fallback')
        dst=frames/f'{index:06}.png';shutil.copyfile(src,dst)
        item.update(index=index,timeSeconds=index/float(target),
                    sha256=hashlib.sha256(dst.read_bytes()).hexdigest())
    # Every triplet is available for checking eyes, mouths, fur and boundaries.
    for page,start in enumerate(range(0,count-1,12)):
        board=Image.new('RGB',(192*3, (min(12,count-1-start))*216),'#eeeeee')
        draw=ImageDraw.Draw(board)
        for row,left in enumerate(range(start,min(start+12,count-1))):
            for col,index in enumerate((2*left,2*left+1,2*left+2)):
                im=Image.open(frames/f'{index:06}.png');im.thumbnail((192,192))
                x,y=col*192,row*216
                board.paste(im,(x+(192-im.width)//2,y+24))
                label=f'{index}: '+('NATIVE' if index%2==0 else 'SYNTH 0.5')
                draw.text((x+3,y+4),label,fill='black')
        board.save(review/f'triplets-{page:03}.jpg')
    run([ffmpeg,'-hide_banner','-loglevel','error','-framerate',target,'-start_number','0',
         '-i',frames/'%06d.png','-an','-c:v','ffv1',output/'candidate.mkv'])
    with Image.open(frames/'000000.png') as first:frame_size=list(first.size)
    report=dict(schemaVersion=1,status='candidate-unreviewed',source=str(source),
                sourceSha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                sourceFps=str(rate),targetFps=str(target),nativeCount=count,
                frameCount=len(origins),maxSide=max_side,frameSize=frame_size,
                processedSha256=hashlib.sha256((output/'candidate.mkv').read_bytes()).hexdigest(),
                nativePixelsPreserved=True,loopInterpolated=False,
                algorithm='ffmpeg-minterpolate-mci-aobmc-bidir-vsbmc',
                context='two cloned boundary frames; removed from output',
                frames=origins,visualAcceptance='unreviewed',
                limitations='Does not validate motion semantics, masks or the loop seam. Scaling is explicit; native preservation is relative to the archived working-size decode.')
    (output/'lineage.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--ffmpeg',default='ffmpeg');p.add_argument('--ffprobe',default='ffprobe')
    p.add_argument('--max-side',type=int)
    a=p.parse_args();r=densify(a.video,a.output,a.ffmpeg,a.ffprobe,a.max_side)
    print(json.dumps({k:r[k] for k in ('status','nativeCount','frameCount','sourceFps','targetFps','loopInterpolated')}))
