import {createFrameAnimator} from './frame-animator.mjs';
import {mapDirection,angularDistance,inNeutralZone,pointerAngle,validPhases} from './pointer-direction.mjs';
import {verifyQuality} from './quality-gate.mjs';
import {previewFrame,previewDegrees,verifyPreviewAssets} from './candidate-preview.mjs';

/**
 * The scene is a position:relative container fitted exactly to the base image.
 * Copy all five .mjs files. Serve through HTTP with JavaScript module MIME.
 * subjects: [{id, manifest: URL|string}]. rootUrl resolves manifest source paths.
 * Call destroy() on unmount or before switching scenes; ready reports failures per subject.
 */
export function mountHeadFollowers({scene,baseImage,subjects,rootUrl=new URL('.',document.baseURI),
  enabled=()=>true,onState=()=>{},diagnosticPreview=false,experimentalPreview=false}) {
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  const lifetime=new AbortController();
  let generation=0,disposed=false,cleanups=[],pending=[];
  const status={};
  const emit=(id,state)=>{status[id]=state;onState({...status});};
  async function mount(subject,epoch,signal) {
    const manifestUrl=new URL(subject.manifest,rootUrl);
    const response=await fetch(manifestUrl,{signal});
    if(!response.ok)throw new Error('manifest could not be loaded');
    const config=await response.json();
    if(![config.frameCount,config.columns,config.framesPerSheet].every(v=>Number.isInteger(v)&&v>0)
      || !Array.isArray(config.sheets)||config.sheets.length!==Math.ceil(config.frameCount/config.framesPerSheet)
      || config.sheets.some(v=>typeof v!=='string'||!v)||new Set(config.sheets).size!==config.sheets.length)
      throw new Error('invalid atlas capacity');
    if(!Array.isArray(config.sourceSize)||config.sourceSize.length!==2||!config.sourceSize.every(v=>Number.isInteger(v)&&v>0)
      || !Array.isArray(config.crop)||config.crop.length!==4||!config.crop.every(Number.isInteger))
      throw new Error('invalid scene geometry');
    const [sw,sh]=config.sourceSize, [x,y,w,h]=config.crop;
    if(x<0||y<0||w<=0||h<=0||x+w>sw||y+h>sh||!Array.isArray(config.eye)||config.eye.length!==2
      || !config.eye.every(Number.isFinite)||config.eye[0]*sw<x||config.eye[0]*sw>=x+w
      || config.eye[1]*sh<y||config.eye[1]*sh>=y+h)throw new Error('invalid crop or eye position');
    if(config.preview) {
      if(!experimentalPreview)throw new Error('experimental candidate needs explicit experimentalPreview');
      await verifyPreviewAssets(config,manifestUrl,rootUrl,signal);
    } else if(!diagnosticPreview)await verifyQuality(config,manifestUrl,rootUrl,signal);
    await baseImage.decode();
    if(new URL(config.baseImage,rootUrl).href!==baseImage.src || sw!==baseImage.naturalWidth
      || sh!==baseImage.naturalHeight || (baseImage.dataset.sceneId && config.sceneId!==baseImage.dataset.sceneId))
      throw new Error('atlas belongs to a different scene');
    if((!config.preview&&(config.directionFrames?.length!==8 || config.directionFrames[0]!==0
      || config.directionFrames.some((v,i,a)=>!Number.isInteger(v)||v<0||v>=config.frameCount||(i&&v<=a[i-1]))
      || !validPhases(config.phaseSamples,config.directionFrames,config.frameCount)))
      || config.sheets?.length!==Math.ceil(config.frameCount/config.framesPerSheet))throw new Error('invalid atlas metadata');
    async function loadImage(url) {const image=new Image();image.src=url;await image.decode();return image;}
    const sheets=await Promise.all(config.sheets.map(file=>loadImage(new URL(file,manifestUrl).href)));
    for(let i=0;i<sheets.length;i++) {
      const cells=Math.min(config.framesPerSheet,config.frameCount-i*config.framesPerSheet);
      if(sheets[i].width!==w*config.columns || sheets[i].height<Math.ceil(cells/config.columns)*h)
        throw new Error('atlas dimensions mismatch');
    }
    const plate=config.background?.owner==='page'
      ? await loadImage(new URL(config.cleanPlate?.path || '',rootUrl).href):null;
    if(plate && (plate.width!==sw||plate.height!==sh))throw new Error('clean plate dimensions mismatch');
    if(disposed||epoch!==generation||signal.aborted)return;
    const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');
    if(!ctx)throw new Error('canvas unavailable');
    canvas.className='head-follow-patch';canvas.dataset.subject=subject.id;
    canvas.setAttribute('aria-hidden','true');canvas.width=w;canvas.height=h;
    canvas.style.cssText=`position:absolute;pointer-events:none;left:${x/sw*100}%;top:${y/sh*100}%;width:${w/sw*100}%;height:${h/sh*100}%;visibility:hidden;mix-blend-mode:normal`;
    scene.append(canvas);
    const settings=config.runtime||{},steps=3600;
    const arc=config.preview?.mode==='arc',arcStart=arc?config.preview.samples[0][0]:0;
    const arcSpan=arc?config.preview.samples.at(-1)[0]-arcStart:360;
    const toStep=angle=>arc?(previewDegrees(angle,config.preview)-arcStart)/arcSpan*(steps-1):angle/(Math.PI*2)*steps;
    const toAngle=step=>arc?(arcStart+step/(steps-1)*arcSpan)*Math.PI/180:step/steps*Math.PI*2;
    // smoothDamp already filters movement; a default deadband makes slow motion stick.
    const hysteresis=(settings.angleHysteresisDegrees??0)*Math.PI/180;
    let animator,visible=true,neutral=true,lastAngle=null,wasActive=null;
    const active=()=>visible&&!document.hidden&&enabled()&&!reduced.matches;
    function draw(frame) {
      if(frame===null){ctx.clearRect(0,0,w,h);return;}
      const sheet=Math.floor(frame/config.framesPerSheet),cell=frame%config.framesPerSheet;
      ctx.clearRect(0,0,w,h);
      if(plate)ctx.drawImage(plate,x,y,w,h,0,0,w,h);
      ctx.drawImage(sheets[sheet],cell%config.columns*w,Math.floor(cell/config.columns)*h,w,h,0,0,w,h);
    }
    function reset(angle=null) {
      animator?.destroy();neutral=angle===null;lastAngle=angle;
      animator=createFrameAnimator({frameCount:steps,initialFrame:angle===null?0:toStep(angle),
        circular:!arc,smoothTime:settings.smoothTime??.14,
        render:step=>{if(!neutral)draw(config.preview?previewFrame(toAngle(step),config.preview):
          mapDirection(toAngle(step),config.directionFrames,config.frameCount,config.phaseSamples));}});
      if(neutral)ctx.clearRect(0,0,w,h);
    }
    function sync() {
      const now=active();canvas.style.visibility=now?'visible':'hidden';
      if(now!==wasActive){reset();if(!now)animator.destroy();wasActive=now;}
    }
    const observer=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;sync();});observer.observe(scene);
    document.addEventListener('visibilitychange',sync,{signal});
    window.addEventListener('pointermove',event=>{
      sync();if(!active()||event.pointerType==='touch')return;
      const rect=baseImage.getBoundingClientRect();
      const dx=event.clientX-(rect.left+config.eye[0]*rect.width),dy=event.clientY-(rect.top+config.eye[1]*rect.height);
      if(inNeutralZone(dx,dy,neutral,settings.neutral)){if(!neutral)reset();return;}
      const angle=pointerAngle(dx,dy,settings.verticalScale??1.15);
      if(config.preview&&previewFrame(angle,config.preview)===null){if(!neutral)reset();return;}
      if(neutral){reset(angle);return;}
      const delta=lastAngle===null?Infinity:arc?
        (previewDegrees(angle,config.preview)-previewDegrees(lastAngle,config.preview))*Math.PI/180:angularDistance(angle,lastAngle);
      if(Math.abs(delta)<hysteresis)return;
      lastAngle=angle;animator.setTarget(toStep(angle));
    },{signal,passive:true});
    document.documentElement.addEventListener('pointerleave',()=>reset(),{signal});
    sync();
    cleanups.push(()=>{observer.disconnect();animator?.destroy();canvas.remove();});
    emit(subject.id,config.preview?`experimental-${config.preview.mode}`:diagnosticPreview?'diagnostic-preview':'ready');
  }
  function configure() {
    generation++;pending.forEach(item=>item.abort());pending=[];
    cleanups.forEach(fn=>fn());cleanups=[];
    if(disposed)return Promise.resolve({...status});
    const epoch=generation;
    return Promise.all(subjects.map(subject=>{
      if(reduced.matches){emit(subject.id,'reduced-motion');return;}
      const controller=new AbortController();pending.push(controller);emit(subject.id,'loading');
      return mount(subject,epoch,controller.signal).catch(error=>{
        if(epoch===generation&&!disposed)emit(subject.id,`unavailable: ${error.message}`);
      });
    })).then(()=>({...status}));
  }
  reduced.addEventListener('change',configure,{signal:lifetime.signal});
  const ready=configure();
  function destroy(){if(disposed)return;disposed=true;generation++;lifetime.abort();
    pending.forEach(item=>item.abort());cleanups.forEach(fn=>fn());pending=[];cleanups=[];}
  window.addEventListener('pagehide',destroy,{signal:lifetime.signal});
  return {ready,destroy,getStatus:()=>({...status})};
}
