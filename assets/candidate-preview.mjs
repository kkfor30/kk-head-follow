// Pointer-controlled candidates. These functions never certify a direction ring.
export function validPreview(p,count) {
  const s=p?.samples;
  return Number.isInteger(count)&&count>0&&['phase','arc'].includes(p?.mode)&&typeof p.notes==='string'&&p.notes.trim().length>0&&
    Array.isArray(s)&&s.length>=2&&s.every((v,i)=>Array.isArray(v)&&v.length===2&&Number.isFinite(v[0])&&
      Number.isInteger(v[1])&&v[1]>=0&&v[1]<count&&(!i||(v[0]>s[i-1][0]&&v[1]>s[i-1][1])))&&
    s[0][0]>=0&&s[0][0]<360&&s.at(-1)[0]-s[0][0]<=360&&
    (p.mode==='phase'?(s[0][0]===0&&s.at(-1)[0]===360):s.at(-1)[0]-s[0][0]<360);
}
export function previewDegrees(angle,p) {
  if(!Number.isFinite(angle))return null;
  const start=p.samples[0][0],end=p.samples.at(-1)[0];
  let degrees=((angle*180/Math.PI)%360+360)%360;
  if(degrees<start-1e-7)degrees+=360;
  return degrees>end+1e-7?null:Math.max(start,Math.min(end,degrees));
}
export function previewFrame(angle,p) {
  const samples=p.samples,degrees=previewDegrees(angle,p);
  if(degrees===null)return null;
  for(let i=1;i<samples.length;i++)if(degrees<=samples[i][0]) {
    const [a,f]=samples[i-1],[b,g]=samples[i];
    return Math.round(f+(g-f)*(degrees-a)/(b-a));
  }
  return null;
}
export async function verifyPreviewAssets(config,manifestUrl,rootUrl,signal) {
  if(!validPreview(config.preview,config.frameCount)||config.directionFrames!==undefined||config.phaseSamples!==undefined||config.quality?.status==='reviewed')
    throw new Error('invalid experimental candidate; cannot carry certified direction metadata');
  const entries=[[new URL(config.baseImage,rootUrl),config.baseImageSha256],
    ...config.sheets.map(p=>[new URL(p,manifestUrl),config.sheetHashes?.[p]])];
  if(config.cleanPlate)entries.push([new URL(config.cleanPlate.path,rootUrl),config.cleanPlate.sha256]);
  await Promise.all(entries.map(async([url,expected])=>{
    if(!/^[a-f0-9]{64}$/i.test(expected||''))throw new Error('missing candidate asset hash');
    const response=await fetch(url,{signal,cache:'no-cache'});
    if(!response.ok)throw new Error('candidate asset unavailable');
    const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await response.arrayBuffer())),
      b=>b.toString(16).padStart(2,'0')).join('');
    if(hash!==expected.toLowerCase())throw new Error('candidate asset changed');
  }));
}
