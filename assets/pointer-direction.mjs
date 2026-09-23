// Direction-ring mapping. Smooth the geometric angle, never the uneven atlas index.
export function validPhases(phases,anchors,count) {
  return phases==null || (Array.isArray(phases)&&phases.length>=8&&
    phases.every((p,i)=>Array.isArray(p)&&p.length===2&&Number.isInteger(p[0])&&p[0]>=0&&p[0]<count&&
      Number.isFinite(p[1])&&p[1]>=0&&p[1]<360&&(!i||(p[0]>phases[i-1][0]&&p[1]>phases[i-1][1])))&&
    phases[0][0]===0&&phases[0][1]===0&&anchors.every((f,i)=>phases.some(p=>p[0]===f&&p[1]===i*45)));
}
export function mapDirection(angle, anchors, count, phases=null) {
  const turn=Math.PI*2, a=((angle%turn)+turn)%turn;
  if(phases) {
    const degrees=a/turn*360, points=[...phases,[count,360]];
    let i=0;
    while(i+1<points.length-1 && points[i+1][1]<=degrees)i++;
    const [f0,p0]=points[i], [f1,p1]=points[i+1];
    return Math.round(f0+(f1-f0)*(degrees-p0)/(p1-p0))%count;
  }
  const extended=[...anchors,anchors[0]+count];
  const unit=a/(turn/anchors.length), i=Math.floor(unit), weight=unit-i;
  return Math.round(extended[i]+(extended[i+1]-extended[i])*weight)%count;
}
export function angularDistance(a,b) { return Math.atan2(Math.sin(a-b),Math.cos(a-b)); }
export function inNeutralZone(dx,dy,wasNeutral,config={}) {
  const {radiusX=20,radiusY=10,top=-6,exitScale=1.35}=config;
  const scale=wasNeutral?exitScale:1;
  return dy>=top && (dx/(radiusX*scale))**2+(dy/(radiusY*scale))**2<1;
}
export function pointerAngle(dx,dy,verticalScale=1.15) {
  return (Math.atan2(dx,-dy*verticalScale)+Math.PI*2)%(Math.PI*2);
}
