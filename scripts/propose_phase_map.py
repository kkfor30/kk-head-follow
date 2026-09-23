"""Propose timing between observed direction anchors; not a pose estimator.

Writes only a separate candidate report. It never edits or approves a manifest.
"""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image


def redistribute(anchors, edge_motion):
    """Keep measured anchors fixed; compress near-still subintervals continuously."""
    if len(anchors)!=8 or any(type(v) is not int for v in anchors) or any(a>=b for a,b in zip(anchors,anchors[1:])):
        raise ValueError('eight increasing observed anchors required')
    if len(edge_motion)!=anchors[-1]-anchors[0] or not np.isfinite(edge_motion).all() or min(edge_motion)<0:
        raise ValueError('invalid inter-frame motion measurements')
    points=[]
    for sector,(a,b) in enumerate(zip(anchors,anchors[1:])):
        values=np.array(edge_motion[a-anchors[0]:b-anchors[0]],float)
        # Small positive floor preserves monotonicity; it is not fabricated imagery.
        values=np.maximum(values,max(float(np.median(values))*.1,1e-6))
        phases=45*sector+45*np.r_[0,np.cumsum(values)]/values.sum()
        points.extend([[i,float(p)] for i,p in zip(range(a,b),phases[:-1])])
    points.append([anchors[-1],315.])
    return points


def propose(folder, anchors, head_rect, output):
    if output.exists():raise ValueError('preserve earlier proposal; choose a new output')
    if len(anchors)!=8 or anchors[0]>=anchors[-1]:raise ValueError('invalid anchors')
    x,y,w,h=head_rect
    if min(x,y)<0 or min(w,h)<=0:raise ValueError('invalid head rectangle')
    edges=[];hashes={};previous=None;previous_alpha=None
    for index in range(anchors[0],anchors[-1]+1):
        paths=[folder/'frames'/f'{index:05}.png',folder/'masks'/f'{index:05}.png']
        rgb=np.array(Image.open(paths[0]).convert('RGB'));alpha=np.array(Image.open(paths[1]).convert('L'))
        if alpha.shape!=rgb.shape[:2] or x+w>rgb.shape[1] or y+h>rgb.shape[0]:raise ValueError('head rectangle or mask outside image')
        for p in paths:hashes[str(p.resolve())]=hashlib.sha256(p.read_bytes()).hexdigest()
        gray=cv2.cvtColor(rgb[y:y+h,x:x+w],cv2.COLOR_RGB2GRAY)
        matte=alpha[y:y+h,x:x+w]>192
        if previous is not None:
            region=matte&previous_alpha
            if region.sum()<64:raise ValueError('not enough overlapping head foreground')
            flow=cv2.calcOpticalFlowFarneback(previous,gray,None,.5,3,21,4,7,1.5,0)
            edges.append(float(np.median(np.linalg.norm(flow,axis=2)[region])))
        previous=gray;previous_alpha=matte
    phases=redistribute(anchors,edges)
    report=dict(status='proposal-unreviewed',method='foreground-motion-within-observed-sectors',
                warning='Motion magnitude is not head/gaze angle. Does not repair the 315-to-360 seam or missing poses.',
                headRect=head_rect,sourceAnchors=anchors,sourcePhaseProposal=phases,edgeMotion=edges,inputHashes=hashes)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--folder',type=Path,required=True);p.add_argument('--anchors',type=int,nargs=8,required=True)
    p.add_argument('--head-rect',type=int,nargs=4,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();propose(a.folder,a.anchors,a.head_rect,a.output)
