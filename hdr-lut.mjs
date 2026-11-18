// Local PQ/HLG BT.2020 -> BT.709 SDR conversion using the bundled WASM lut3d filter.
export const HDR_MODES=['auto','off','mobius','hable','reinhard'];
export const HDR_TRANSFERS=['auto','pq','hlg'];
const clamp=(n,lo=0,hi=1)=>Math.min(hi,Math.max(lo,n));
export function hdrTransferFromLog(log){
  for(const line of String(log).split(/\r?\n/)){
    if(!/\bVideo:/.test(line))continue;
    if(/\b(smpte2084|smpte-2084)\b/i.test(line))return 'pq';
    if(/\b(arib-std-b67|arib_std_b67)\b/i.test(line))return 'hlg';
  }
  return null;
}
export function selectedHdrTransfer(media,s){
  return s.hdrMode==='off'?null:s.hdrTransfer==='auto'||!s.hdrTransfer
    ?media?.hdrTransfer??null:s.hdrTransfer;
}
function light(v,t){
  v=clamp(v);
  if(t==='pq'){
    const m1=2610/16384,m2=2523/32,c1=3424/4096,c2=2413/128,c3=2392/128;
    const z=Math.pow(v,1/m2);
    return 10000*Math.pow(Math.max(z-c1,0)/(c2-c3*z),1/m1);
  }
  if(t==='hlg'){
    const a=0.17883277,b=1-4*a,c=0.5-a*Math.log(4*a);
    return v<=0.5?v*v/3:(Math.exp((v-c)/a)+b)/12;
  }
  throw Error('Unsupported HDR transfer');
}
function curve(x,mode,peak=10){
  if(mode==='hable'){
    const f=v=>(v*(0.15*v+0.05)+0.004)/(v*(0.15*v+0.5)+0.06)-0.02/0.30;
    return clamp(f(x)/f(peak));
  }
  if(mode==='reinhard')return clamp((x/(1+x))/(peak/(1+peak)));
  const knee=.35,shoulder=(1-knee)*(peak-knee)/(peak-1);
  return x<=knee?clamp(x):clamp(knee+(x-knee)/(1+(x-knee)/shoulder));
}
export function hdrPixel(r,g,b,transfer,mode='mobius'){
  if(!['pq','hlg'].includes(transfer)||!['mobius','hable','reinhard'].includes(mode))
    throw Error('Unsupported HDR LUT setup');
  let cr=light(r,transfer),cg=light(g,transfer),cb=light(b,transfer);
  if(transfer==='hlg'){
    const y=.2627*cr+.6780*cg+.0593*cb;
    const gain=1000*Math.pow(Math.max(y,1e-10),.2);
    cr*=gain;cg*=gain;cb*=gain;
  }
  const rr=Math.max(0,1.660491*cr-.587641*cg-.072850*cb);
  const gg=Math.max(0,-.124550*cr+1.132899*cg-.008349*cb);
  const bb=Math.max(0,-.018151*cr-.100579*cg+1.118730*cb);
  const l=.2126*rr+.7152*gg+.0722*bb;
  const gain=l>1e-7?curve(l/100,mode)/l:0;
  const gamma=x=>{x=clamp(x);return x<.018?4.5*x:1.099*Math.pow(x,.45)-.099;};
  return [gamma(rr*gain),gamma(gg*gain),gamma(bb*gain)];
}
export function createHdrLut(transfer,mode='mobius',size=33){
  if(!['pq','hlg'].includes(transfer)||!['mobius','hable','reinhard'].includes(mode))
    throw Error('Unsupported HDR LUT setup');
  if(!Number.isInteger(size)||size<2||size>65)throw Error('Invalid LUT size');
  const lines=['TITLE "MobiPEG HDR to BT709"','LUT_3D_SIZE '+size,
    'DOMAIN_MIN 0.0 0.0 0.0','DOMAIN_MAX 1.0 1.0 1.0'];
  for(let b=0;b<size;b++)for(let g=0;g<size;g++)for(let r=0;r<size;r++)
    lines.push(hdrPixel(r/(size-1),g/(size-1),b/(size-1),transfer,mode).map(v=>v.toFixed(6)).join(' '));
  return lines.join('\n')+'\n';
}
export function hdrFilter(s,transfer){
  if(!transfer||s.hdrMode==='off')return '';
  if(!['pq','hlg'].includes(transfer))throw Error('Invalid HDR transfer');
  return 'format=gbrp16le,lut3d=file=/input/hdr.cube:interp=tetrahedral,'+
    'setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709,';
}
