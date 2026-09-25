"""Prepare reviewable foreground candidates from a LOCAL U2-Net model.

No model download, paid generation, automatic approval or image replacement.
The result is a soft segmentation candidate, not certified hair matting.
"""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def mask_metrics(alpha):
    solid=alpha>128
    edge=np.concatenate([solid[0],solid[-1],solid[:,0],solid[:,-1]])
    return {'area':int(solid.sum()), 'edgePixels':int(edge.sum()),
            'topOrSideClipped':bool(solid[0].any() or solid[:,0].any() or solid[:,-1].any())}


def prepare(video, output, model_dir, start, end, size):
    model=model_dir/'u2net.onnx'
    if not model.is_file():
        raise ValueError('local u2net.onnx required; acquire the optional model separately')
    if output.exists():
        raise ValueError('output must be new; preserve earlier candidates')
    if start<0 or end<=start or min(size)<32:
        raise ValueError('invalid range or output size')
    # Construct a session directly: avoid new_session download/checksum network paths.
    from rembg.sessions.u2net import U2netSession
    import onnxruntime as ort
    session=object.__new__(U2netSession)
    options=ort.SessionOptions();options.intra_op_num_threads=2
    session.inner_session=ort.InferenceSession(str(model),sess_options=options,providers=['CPUExecutionProvider'])
    cap=cv2.VideoCapture(str(video))
    if not cap.isOpened() or end>int(cap.get(cv2.CAP_PROP_FRAME_COUNT)):
        cap.release();raise ValueError('video unavailable or range exceeds source frames')
    output.mkdir(parents=True);(output/'masks').mkdir();(output/'frames').mkdir()
    cap.set(cv2.CAP_PROP_POS_FRAMES,start)
    rows=[]; previous=None; page=[]
    def save_page():
        board=Image.new('RGB',(size[0]*2,(size[1]+22)*len(page)),'white')
        for j,(idx,rgb,alpha) in enumerate(page):
            a=alpha[:,:,None]/255
            bg=np.full_like(rgb,235);bg[:,::16]=150
            comp=np.rint(rgb*a+bg*(1-a)).astype('uint8')
            board.paste(Image.fromarray(rgb),(0,j*(size[1]+22)+22))
            board.paste(Image.fromarray(comp),(size[0],j*(size[1]+22)+22))
            ImageDraw.Draw(board).text((4,j*(size[1]+22)+3),f'source {idx} - candidate, not approved',fill='black')
        board.save(output/f'review-{page[0][0]:05}.jpg')
        page.clear()
    try:
        for idx in range(start,end):
            ok,bgr=cap.read()
            if not ok:raise ValueError(f'decode failed at {idx}')
            rgb=cv2.cvtColor(cv2.resize(bgr,tuple(size)),cv2.COLOR_BGR2RGB)
            alpha=np.array(session.predict(Image.fromarray(rgb))[0])
            Image.fromarray(rgb).save(output/'frames'/f'{idx:05}.png')
            Image.fromarray(alpha).save(output/'masks'/f'{idx:05}.png')
            metrics=mask_metrics(alpha)
            if previous is not None:
                metrics['alphaMeanChange']=float(np.abs(alpha.astype(float)-previous).mean())
            rows.append(dict(sourceFrame=idx,**metrics));previous=alpha
            page.append((idx,rgb,alpha))
            if len(page)==6:save_page()
            if (idx-start)%24==0:print(f'{idx-start+1}/{end-start}',flush=True)
        if page:save_page()
    finally:cap.release()
    report=dict(status='candidate',method='local-u2net-soft-mask',source=str(video),sourceSha256=sha(video),
                modelSha256=sha(model),range=[start,end],size=size,frames=rows,
                nextAction='Inspect all review pages; correct masks, preserve whiskers, check clipped source before compositing')
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--model-dir',type=Path,required=True)
    p.add_argument('--start',type=int,required=True);p.add_argument('--end',type=int,required=True)
    p.add_argument('--size',type=int,nargs=2,required=True)
    a=p.parse_args();prepare(a.video.resolve(),a.output.resolve(),a.model_dir.resolve(),a.start,a.end,a.size)
