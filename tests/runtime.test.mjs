// DOM stubs test resource/lifecycle behavior without opening or inspecting a browser.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mountHeadFollowers} from '../assets/head-follow.mjs';
import {createHash} from 'node:crypto';
import {mapDirection,angularDistance} from '../assets/pointer-direction.mjs';
import {previewFrame,validPreview} from '../assets/candidate-preview.mjs';

function environment({fail=false,slow=false,unreviewed=false,changed=false}={}) {
  const names=['window','document','matchMedia','Image','IntersectionObserver','fetch','requestAnimationFrame','cancelAnimationFrame'];
  const saved=Object.fromEntries(names.map(name=>[name,Object.getOwnPropertyDescriptor(globalThis,name)]));
  const window=new EventTarget(),document=new EventTarget(),media=new EventTarget();
  media.matches=false;document.hidden=false;document.baseURI='http://example.test/';document.documentElement=new EventTarget();
  const calls=[],canvases=[],jobs=new Map();let serial=0,release;
  const waiting=slow?new Promise(resolve=>release=resolve):Promise.resolve();
  document.createElement=()=>{
    const canvas={dataset:{},style:{},setAttribute(){},getContext(){return {clearRect(){calls.push('clear');},drawImage(){calls.push('draw');}};},
      remove(){const index=canvases.indexOf(canvas);if(index>=0)canvases.splice(index,1);}};return canvas;
  };
  const manifest={sceneId:'test',baseImage:'base.png',sourceSize:[100,100],crop:[40,40,10,10],eye:[.45,.45],
    frameCount:8,columns:8,framesPerSheet:8,directionFrames:[0,1,2,3,4,5,6,7],sheets:['sheet.png'],background:{owner:'scene',mode:'preserve'}};
  const hash=value=>createHash('sha256').update(value).digest('hex');
  const pixelBytes=new TextEncoder().encode('fixture pixels');
  const binding={contract:structuredClone(manifest),assets:[{scope:'root',path:'base.png',sha256:hash(pixelBytes)},
    {scope:'manifest',path:'sheet.png',sha256:hash(pixelBytes)}]};
  const reportBytes=new TextEncoder().encode(JSON.stringify({status:'reviewed',circular:true,issues:[],binding}));
  manifest.quality=unreviewed?{status:'candidate',circular:false}:
    {status:'reviewed',circular:true,binding,report:'quality.json',reportSha256:hash(reportBytes)};
  Object.assign(globalThis,{window,document,matchMedia:()=>media,
    Image:class{constructor(){this.width=80;this.height=10;}async decode(){await waiting;}},
    IntersectionObserver:class{constructor(callback){this.callback=callback;}observe(){this.callback([{isIntersecting:true}]);}disconnect(){}},
    fetch:async url=>({ok:!fail,json:async()=>manifest,
      arrayBuffer:async()=>String(url).endsWith('quality.json')?reportBytes.buffer:
        (changed?new TextEncoder().encode('changed pixels').buffer:pixelBytes.buffer)}),
    requestAnimationFrame:callback=>{jobs.set(++serial,callback);return serial;},cancelAnimationFrame:id=>jobs.delete(id)});
  const scene={append(canvas){canvases.push(canvas);}};
  const baseImage={src:'http://example.test/base.png',naturalWidth:100,naturalHeight:100,dataset:{sceneId:'test'},
    decode:async()=>{},getBoundingClientRect:()=>({left:0,top:0,width:100,height:100})};
  return {scene,baseImage,calls,canvases,jobs,release,media,manifest,
    makePreview(mode='phase',samples=[[0,0],[360,7]]) {
      delete manifest.directionFrames;
      manifest.quality={status:'candidate',circular:false};
      manifest.preview={mode,samples,notes:'Synthetic fixture only; not reviewed for directions.'};
      manifest.baseImageSha256=hash(pixelBytes);manifest.sheetHashes={'sheet.png':hash(pixelBytes)};
    },
    flush(){let time=1,guard=0;while(jobs.size){if(++guard>1000)throw new Error('animation did not settle');
      const batch=[...jobs.values()];jobs.clear();for(const callback of batch)callback(time);time+=16.67;}},
    pointer(x,y){const event=new Event('pointermove');Object.assign(event,{clientX:x,clientY:y,pointerType:'mouse'});window.dispatchEvent(event);},
    restore(){for(const name of names){if(saved[name])Object.defineProperty(globalThis,name,saved[name]);else delete globalThis[name];}}};
}
test('pointer draws, neutral clears, teardown removes layers and pending callbacks',async()=>{
  const env=environment();let controller;
  try{controller=mountHeadFollowers({...env,subjects:[{id:'person',manifest:'frames/manifest.json'}]});
    assert.deepEqual(await controller.ready,{person:'ready'});assert.equal(env.canvases.length,1);
    env.pointer(45,0);assert.equal(env.calls.at(-1),'draw');
    env.pointer(45,45);assert.equal(env.calls.at(-1),'clear');
    env.pointer(45,0);env.pointer(90,40);assert(env.jobs.size>0);
    controller.destroy();assert.equal(env.canvases.length,0);assert.equal(env.jobs.size,0);
    const count=env.calls.length;env.pointer(0,0);assert.equal(env.calls.length,count);
  }finally{controller?.destroy();env.restore();}
});
test('failed resources keep the scene static',async()=>{
  const env=environment({fail:true});let controller;
  try{controller=mountHeadFollowers({...env,subjects:[{id:'person',manifest:'missing.json'}]});
    const status=await controller.ready;assert.match(status.person,/unavailable/);assert.equal(env.canvases.length,0);
  }finally{controller?.destroy();env.restore();}
});
test('slow pointer motion below three degrees still updates the smoothing target',async()=>{
  const env=environment();let controller;
  try{controller=mountHeadFollowers({...env,subjects:[{id:'person',manifest:'frames/manifest.json'}]});
    await controller.ready;
    env.pointer(45,0);assert.equal(env.jobs.size,0);
    env.pointer(46,0);assert(env.jobs.size>0,'a small valid direction change must not be discarded');
  }finally{controller?.destroy();env.restore();}
});
test('late image decode cannot attach a canvas after unmount',async()=>{
  const env=environment({slow:true});let controller;
  try{controller=mountHeadFollowers({...env,subjects:[{id:'person',manifest:'frames/manifest.json'}]});
    controller.destroy();env.release();await controller.ready;assert.equal(env.canvases.length,0);
  }finally{controller?.destroy();env.restore();}
});
test('reduced motion skips mounting',async()=>{
  const env=environment();env.media.matches=true;let controller;
  try{controller=mountHeadFollowers({...env,subjects:[{id:'person',manifest:'frames/manifest.json'}]});
    assert.deepEqual(await controller.ready,{person:'reduced-motion'});assert.equal(env.canvases.length,0);
  }finally{controller?.destroy();env.restore();}
});
test('unreviewed and changed atlases cannot replace a static hero',async()=>{
  for(const options of [{unreviewed:true},{changed:true}]) {
    const env=environment(options);let controller;
    try{controller=mountHeadFollowers({...env,subjects:[{id:'person',manifest:'frames/manifest.json'}]});
      assert.match((await controller.ready).person,/unavailable/);assert.equal(env.canvases.length,0);
    }finally{controller?.destroy();env.restore();}
  }
});
test('diagnostic preview is explicit and never reports ready',async()=>{
  const env=environment({unreviewed:true});let controller;
  try{controller=mountHeadFollowers({...env,diagnosticPreview:true,subjects:[{id:'person',manifest:'frames/manifest.json'}]});
    assert.equal((await controller.ready).person,'diagnostic-preview');assert.equal(env.canvases.length,1);
  }finally{controller?.destroy();env.restore();}
});
test('direction mapping covers clockwise and counterclockwise circles without a top reversal',()=>{
  const anchors=[0,12,20,33,40,48,62,70],count=80;
  for(const direction of [1,-1]) {
    let previous=mapDirection(0,anchors,count);
    for(let degree=1;degree<=720;degree++) {
      const next=mapDirection(direction*degree*Math.PI/180,anchors,count);
      const delta=angularDistance(next/count*2*Math.PI,previous/count*2*Math.PI);
      assert(direction*delta>=-1e-8);assert(Math.abs(delta)<=2*Math.PI/count+1e-8);previous=next;
    }
  }
  const phases=anchors.map((f,i)=>[f,i*45]);phases.splice(1,0,[3,30]);
  assert.equal(mapDirection(Math.PI/6,anchors,count,phases),3);
});

test('experimental candidates require opt-in and preserve their non-ready state',async()=>{
  for(const optin of [false,true]) {
    const env=environment();env.makePreview();let controller;
    try{controller=mountHeadFollowers({...env,experimentalPreview:optin,subjects:[{id:'person',manifest:'frames/manifest.json'}]});
      const state=(await controller.ready).person;
      if(optin){assert.equal(state,'experimental-phase');env.pointer(45,0);assert.equal(env.calls.at(-1),'draw');}
      else {assert.match(state,/unavailable/);assert.equal(env.canvases.length,0);}
    }finally{controller?.destroy();env.restore();}
  }
});

test('candidate asset changes, invalid geometry and direction certificates cannot mount',async()=>{
  for(const mutation of ['hash','capacity','crop','reviewed','phases']) {
    const env=environment({changed:mutation==='hash'});env.makePreview();let controller;
    if(mutation==='capacity')env.manifest.columns=.5;
    if(mutation==='crop')env.manifest.crop=[95,40,10,10];
    if(mutation==='reviewed')env.manifest.quality.status='reviewed';
    if(mutation==='phases')env.manifest.phaseSamples=[[0,0],[7,315]];
    try{controller=mountHeadFollowers({...env,experimentalPreview:true,subjects:[{id:'person',manifest:'frames/manifest.json'}]});
      assert.match((await controller.ready).person,/unavailable/);assert.equal(env.canvases.length,0);
    }finally{controller?.destroy();env.restore();}
  }
});

test('a wide arc smooths within its available interval and clears outside it',async()=>{
  const env=environment();env.makePreview('arc',[[45,0],[315,7]]);let controller;
  try{controller=mountHeadFollowers({...env,experimentalPreview:true,subjects:[{id:'person',manifest:'frames/manifest.json'}]});
    assert.equal((await controller.ready).person,'experimental-arc');
    const point=degree=>env.pointer(45+100*Math.sin(degree*Math.PI/180),45-100*Math.cos(degree*Math.PI/180)/1.15);
    point(60);env.calls.length=0;point(300);env.flush();
    assert(env.calls.includes('draw'));
    for(let i=0;i<env.calls.length;i+=2)assert.deepEqual(env.calls.slice(i,i+2),['clear','draw']);
    point(0);assert.equal(env.calls.at(-1),'clear');
    controller.destroy();assert.equal(env.jobs.size,0);assert.equal(env.canvases.length,0);
  }finally{controller?.destroy();env.restore();}
});

test('candidate mappings handle a top-crossing arc without claiming missing directions',()=>{
  const arc={mode:'arc',samples:[[315,0],[360,3],[405,7]],notes:'fixture'};
  assert(validPreview(arc,8));
  for(const [degree,frame] of [[315,0],[-45,0],[0,3],[45,7],[180,null]])
    assert.equal(previewFrame(degree*Math.PI/180,arc),frame);
  assert(!validPreview({...arc,samples:[[0,0],[360,7]]},8));
  const phase={...arc,mode:'phase',samples:[[0,0],[360,7]]};
  for(let degree=-720;degree<720;degree++) {
    const frame=previewFrame(degree*Math.PI/180,phase);assert(frame>=0&&frame<8);
  }
});
