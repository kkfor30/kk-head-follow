"""Non-destructive local repair candidates: route, registration, color, masks, flow.

No paid generation. Never certifies a repaired face, invents direction labels, or
blends two faces. Rejected candidates leave the original atlas untouched.
"""
from __future__ import annotations
import argparse
import copy
import json
import shutil
from pathlib import Path
import numpy as np
from PIL import Image
from atlas_quality import (read, digest, mask, load_frames, write_sheets,
                           validate_phases, background_metrics)
from validate_head_manifest import validate
from deformation_quality import inspect_inverse_map


def opencv():
    try:
        import cv2
    except ImportError as exc:
        raise ValueError('registration / optical flow needs optional opencv-python-headless') from exc
    return cv2


def composite(frame, base):
    alpha = frame[:,:,3:4].astype(float)/255
    return np.rint(frame[:,:,:3]*alpha+base*(1-alpha)).clip(0,255).astype('uint8')


def correct_color(frame, reference, static, motion, maximum=12):
    if type(maximum) not in (int,float) or not 0 < maximum <= 12:
        raise ValueError('color offset limit must be within (0,12]')
    before = composite(frame, reference)
    # Fit only fully covered static pixels; do not infer colors from a feather band.
    samples = static & (frame[:,:,3] >= 254)
    if samples.sum() < 16:
        raise ValueError('not enough opaque static pixels for color fitting')
    offset = np.median(reference.astype(float)[samples]-frame[:,:,:3].astype(float)[samples],axis=0)
    if np.abs(offset).max() > maximum:
        raise ValueError('color drift exceeds the bounded correction; inspect alignment / background structure')
    result = frame.copy()
    result[:,:,:3] = np.rint(frame[:,:,:3].astype(float)+offset).clip(0,255).astype('uint8')
    qa = background_metrics([composite(result,reference)],reference,static,motion)
    before_error = float(np.abs(before.astype(float)-reference)[static].mean())
    if not qa['passed'] or qa['samples'][0]['mae'] > before_error + .05:
        raise ValueError('color correction leaves texture mismatch or makes the background worse')
    return result, dict(offset=offset.tolist(), beforeMAE=before_error, after=qa['samples'][0])


def register_translation(frame, reference, static, motion, maximum=3):
    cv = opencv()
    if type(maximum) not in (int,float) or not 0 < maximum <= 3:
        raise ValueError('translation limit must be within (0,3] pixels')
    gray = lambda a: cv.cvtColor(a[:,:,:3], cv.COLOR_RGB2GRAY).astype('float32')/255
    samples = static & (frame[:,:,3] >= 254)
    if samples.sum() < 32 or np.std(gray(reference)[samples]) < .01:
        raise ValueError('registration needs textured static background; flat color is not an alignment reference')
    try:
        _, warp = cv.findTransformECC(gray(reference),gray(frame),np.eye(2,3,dtype='float32'),
                                      cv.MOTION_TRANSLATION,(cv.TERM_CRITERIA_COUNT|cv.TERM_CRITERIA_EPS,80,1e-6),
                                      (samples*255).astype('uint8'),3)
    except cv.error as exc:
        raise ValueError('static-background registration did not converge') from exc
    if np.abs(warp[:,2]).max() > maximum:
        raise ValueError('registration displacement exceeds local repair limit')
    a = frame.astype('float32')/255
    a[:,:,:3] *= a[:,:,3:4]
    aligned = cv.warpAffine(a,warp,(frame.shape[1],frame.shape[0]),
                            flags=cv.INTER_LINEAR|cv.WARP_INVERSE_MAP,borderMode=cv.BORDER_CONSTANT)
    aligned[:,:,:3] /= np.maximum(aligned[:,:,3:4],1e-6)
    result = np.rint(aligned*255).clip(0,255).astype('uint8')
    if np.any(result[:,:,3][motion] < 250):
        raise ValueError('alignment would expose the old head or cut the motion envelope')
    before = float(np.abs(composite(frame,reference).astype(float)-reference)[static].mean())
    after = float(np.abs(composite(result,reference).astype(float)-reference)[static].mean())
    if after > before + .05:
        raise ValueError('alignment made static-background error worse')
    return result,dict(translation=warp[:,2].tolist(), beforeMAE=before, afterMAE=after)


def clean_composite(frame, plate, alpha):
    """Caller supplies a reviewed, per-frame soft matte and head-free plate."""
    if alpha.shape != frame.shape[:2] or plate.shape != frame.shape[:2]+(3,):
        raise ValueError('clean plate / matte dimensions mismatch')
    if alpha.max() == 0 or alpha.min() == 255:
        raise ValueError('foreground matte must contain both foreground and background')
    if np.any((alpha > 16) & (frame[:,:,3] < 250)):
        raise ValueError('matte enters a feathered or missing source region; recompile a larger opaque source patch')
    # Alpha compositing here replaces the old head; never paste onto the old face.
    a = alpha[:,:,None].astype(float)/255
    rgb = np.rint(frame[:,:,:3]*a+plate*(1-a)).clip(0,255).astype('uint8')
    return np.dstack([rgb,np.full(alpha.shape,255,dtype='uint8')])


def flow_bridge(left, right, count, motion):
    cv = opencv()
    if type(count) is not int or not 1 <= count <= 8:
        raise ValueError('a local bridge allows 1..8 synthetic frames')
    if np.any(left[:,:,3][motion]<250) or np.any(right[:,:,3][motion]<250):
        raise ValueError('moving contours touch feather / transparent boundary; widen source coverage first')
    gray = lambda a: cv.cvtColor(a[:,:,:3],cv.COLOR_RGB2GRAY)
    f = cv.calcOpticalFlowFarneback(gray(left),gray(right),None,.5,4,21,5,7,1.5,0)
    b = cv.calcOpticalFlowFarneback(gray(right),gray(left),None,.5,4,21,5,7,1.5,0)
    yy,xx=np.mgrid[:left.shape[0],:left.shape[1]].astype('float32')
    grid=np.dstack([xx,yy])
    remap=lambda a,g:cv.remap(a,g[:,:,0],g[:,:,1],cv.INTER_LINEAR,borderMode=cv.BORDER_REFLECT_101)
    consistency=np.linalg.norm(f+remap(b,grid+f),axis=2)
    residual=np.mean(np.abs(left[:,:,:3].astype(float)-remap(right[:,:,:3],grid+f)),axis=2)
    magnitude=np.linalg.norm(f,axis=2)
    p95=float(np.percentile(consistency[motion],95))
    error=float(np.mean(residual[motion]))
    displacement=float(np.percentile(magnitude[motion],95))
    if p95 > 1.5 or error > 12 or displacement > min(left.shape[:2])*.08:
        raise ValueError(f'flow bridge unreliable: consistency={p95:.2f}, residual={error:.2f}, displacement={displacement:.2f}')
    result=[]
    for i in range(1,count+1):
        t=i/(count+1)
        source,field,fraction=(left,f,t) if t<=.5 else (right,b,1-t)
        # Inverse-map one source only. No crossfade of eyes, ears or silhouettes.
        mapping=grid.copy()
        for _ in range(5):
            mapping=grid-fraction*remap(field,mapping)
        geometry=inspect_inverse_map(mapping,motion)
        if not geometry['passed']:
            raise ValueError('optical-flow fold or missing source detected in the motion region')
        out=remap(source,mapping)
        if np.any(out[:,:,3][motion] < 250):
            raise ValueError('bridge exposes old contour')
        result.append(out)
    return result,dict(consistencyP95=p95,warpedResidual=error,displacementP95=displacement,
                       method='bidirectional-flow-single-source',visualStatus='unreviewed')


def repair(path, root, spec, output):
    path,root,output=path.resolve(),root.resolve(),output.resolve()
    if output == path.parent or output in path.parents:
        raise ValueError('repair output must be a separate sibling or build directory')
    if output.exists():
        raise ValueError('repair output already exists; preserve earlier candidates')
    validate(root,path)
    m=read(path); original=copy.deepcopy(m)
    frames=load_frames(m,path); w,h=m['crop'][2:]; x,y=m['crop'][:2]
    base=np.array(Image.open(root/m['baseImage']).convert('RGB').crop((x,y,x+w,y+h)))
    operations=spec.get('operations',[])
    if not operations and not spec.get('keepFrames') and not spec.get('bridges'):
        raise ValueError('no repair requested')
    needs_masks=bool(operations or spec.get('bridges'))
    motion=static=None
    if needs_masks:
        motion=mask(root/spec['motionUnion'],(w,h))
        static=mask(root/spec['staticMask'],(w,h))
        background_metrics([base],base,static,motion) # verifies disjoint padded masks
    keep=spec.get('keepFrames',list(range(len(frames))))
    if (not keep or keep[0]!=0 or any(type(i) is not int or not 0<=i<len(frames) for i in keep)
            or any(a>=b for a,b in zip(keep,keep[1:])) or not set(m['directionFrames']).issubset(keep)):
        raise ValueError('keepFrames must increase, retain frame 0 and every real direction anchor')
    if m.get('upperSource') and keep[-1]!=len(frames)-1:
        raise ValueError('retain the verified upper center endpoints when trimming')
    results=[]; logs=[]
    for i in keep:
        frame=frames[i].copy()
        for op in operations:
            name=op['type']
            if name=='color-offset':
                frame,info=correct_color(frame,base,static,motion,op.get('maxOffset',12))
            elif name=='translation':
                frame,info=register_translation(frame,base,static,motion,op.get('maxPixels',3))
            elif name=='clean-composite':
                if len(op['masks'])!=len(frames):
                    raise ValueError('one foreground mask per original atlas frame is required')
                plate_image=Image.open(root/op['cleanPlate']).convert('RGB')
                if list(plate_image.size)!=m['sourceSize']:
                    raise ValueError('cleanPlate must match the full base image')
                matte=Image.open(root/op['masks'][i]).convert('L')
                if matte.size!=(w,h):
                    raise ValueError('foreground matte size mismatch')
                frame=clean_composite(frame,np.array(plate_image.crop((x,y,x+w,y+h))),np.array(matte))
                info=dict(cleanPlate=op['cleanPlate'],matte=op['masks'][i])
            else:
                raise ValueError('unknown repair operation: '+str(name))
            logs.append(dict(frame=i,operation=name,details=info))
        results.append(frame)
    bridge_specs=spec.get('bridges',[])
    bridge_map={b['afterFrame']:b for b in bridge_specs}
    if len(bridge_map)!=len(bridge_specs) or any(i not in keep for i in bridge_map):
        raise ValueError('invalid or duplicate bridge edge')
    phases=spec.get('phaseSamples',m.get('phaseSamples'))
    if bridge_map:
        if phases is None:
            raise ValueError('bridging requires observed phaseSamples; index distance is not angular evidence')
        validate_phases(phases,len(frames),m['directionFrames'])
    elif phases is not None:
        validate_phases(phases,len(frames),m['directionFrames'])
    phase_at=lambda i:float(np.interp(i,[p[0] for p in phases]+[len(frames)],[p[1] for p in phases]+[360]))
    output_frames=[]; origins=[]; remap_indices={}; new_phases=[]
    source_records=m.get('frameSources')
    if not source_records or len(source_records)!=len(frames):
        raise ValueError('repair requires frame provenance')
    for n,i in enumerate(keep):
        remap_indices[i]=len(output_frames)
        if phases is not None:new_phases.append([len(output_frames),phase_at(i)])
        output_frames.append(results[n]); origins.append(copy.deepcopy(source_records[i]))
        if i in bridge_map:
            target=keep[(n+1)%len(keep)]
            if bridge_map[i].get('toFrame')!=target:
                raise ValueError('bridge endpoints must be adjacent in the selected route')
            p0=phase_at(i);p1=360 if target==0 else phase_at(target)
            if not 0 < p1-p0 <= 30:
                raise ValueError('bridge exceeds 30 observed degrees; cannot invent a missing directional arc')
            bridge,info=flow_bridge(results[n],results[(n+1)%len(keep)],bridge_map[i]['count'],motion)
            logs.append(dict(afterFrame=i,toFrame=target,operation='flow-bridge',details=info))
            for j,f in enumerate(bridge):
                t=(j+1)/(len(bridge)+1)
                new_phases.append([len(output_frames),p0+t*(p1-p0)])
                output_frames.append(f)
                record=copy.deepcopy(source_records[i])
                record.update(synthesized=True,repair=dict(method=info['method'],fromFrame=i,toFrame=target,fraction=t,
                              parentManifestSha256=digest(path)))
                origins.append(record)
    m['directionFrames']=[remap_indices[i] for i in m['directionFrames']]
    m['frameSources']=origins
    if phases is not None:
        m['phaseSamples']=new_phases
        validate_phases(new_phases,len(output_frames),m['directionFrames'])
    if any(op['type']=='clean-composite' for op in operations):
        m['background'].update(owner='scene',mode='preserve',contactSheet=None)
        m['cleanPlate']=None # The clean plate is now baked into every candidate cell.
    # Key-border QA describes the original keyed source, not the final composite.
    # Preserve it for page/chroma-key; invalidate only final composition acceptance.
    if m['background']['mode']!='chroma-key':
        m['background']['qa']=dict(passed=None,framesChecked=0)
    m['quality']=dict(status='candidate',circular=False)
    m['schemaVersion']=3
    inputs=dict(m.get('repair',{}).get('inputHashes',{}))
    for name in [spec.get('motionUnion'),spec.get('staticMask')]:
        if name:inputs[name]=digest(root/name)
    for op in operations:
        if op['type']=='clean-composite':
            for name in [op['cleanPlate'],*op['masks']]:inputs[name]=digest(root/name)
    m['repair']=dict(parentManifestSha256=digest(path),operations=logs,inputHashes=inputs)
    output.mkdir(parents=True)
    write_sheets(m,output_frames,output)
    for key in ['neutralImage']:
        if m.get(key) and (path.parent/m[key]).is_file():shutil.copy2(path.parent/m[key],output/m[key])
    if m['background'].get('contactSheet'):
        from compile_head_atlas import make_background_contact_sheet
        make_background_contact_sheet([Image.fromarray(a) for a in output_frames],m['directionFrames'],output/m['background']['contactSheet'])
    (output/'manifest.json').write_text(json.dumps(m,indent=2)+'\n',encoding='utf-8')
    report=dict(status='candidate-not-reviewed',framesBefore=len(frames),framesAfter=len(output_frames),operations=logs,
                parentBinding=original,repairSpec=spec)
    (output/'repair-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    validate(root,output/'manifest.json')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('manifest',type=Path);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--spec',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    report=repair(a.manifest,a.root,read(a.spec),a.output)
    print(json.dumps(dict(status=report['status'],framesBefore=report['framesBefore'],framesAfter=report['framesAfter'])))
