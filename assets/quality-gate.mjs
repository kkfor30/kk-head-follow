// A quality report is an engineering handoff, not a security signature.
// Verify the reviewed contract and shipped pixels before enabling a direction ring.
function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(k=>[k,stable(value[k])]));
  return value;
}
export function sameContract(a,b) {return JSON.stringify(stable(a))===JSON.stringify(stable(b));}
export async function verifyQuality(config,manifestUrl,rootUrl,signal) {
  const {quality:q,...contract}=config;
  if(q?.status!=='reviewed'||q.circular!==true||!sameContract(q.binding?.contract,contract))
    throw new Error('quality review missing, failed or stale');
  async function verified(url,expected) {
    if(!/^[a-f0-9]{64}$/i.test(expected||''))throw new Error('missing asset hash');
    const response=await fetch(url,{signal,cache:'no-cache'});
    if(!response.ok)throw new Error('quality resource unavailable');
    const bytes=await response.arrayBuffer();
    const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');
    if(hash!==expected.toLowerCase())throw new Error('reviewed asset changed');
    return bytes;
  }
  const bytes=await verified(new URL(q.report,manifestUrl),q.reportSha256);
  const report=JSON.parse(new TextDecoder().decode(bytes));
  if(report.status!=='reviewed'||report.circular!==true||report.issues?.length!==0||!sameContract(report.binding,q.binding))
    throw new Error('invalid quality report');
  const expected=[['root',config.baseImage],...config.sheets.map(p=>['manifest',p])];
  if(config.cleanPlate)expected.push(['root',config.cleanPlate.path]);
  if(config.frameLineage)expected.push(['root',config.frameLineage.path]);
  const records=q.binding.assets;
  if(!Array.isArray(records)||records.length!==expected.length||
    expected.some(([scope,path])=>records.filter(r=>r.scope===scope&&r.path===path).length!==1))
    throw new Error('incomplete quality asset binding');
  const assets=await Promise.all(records.map(async r=>{
    const url=new URL(r.path,r.scope==='root'?rootUrl:manifestUrl);
    return [url.href,{bytes:await verified(url,r.sha256),sha256:r.sha256.toLowerCase()}];
  }));
  return new Map(assets);
}
