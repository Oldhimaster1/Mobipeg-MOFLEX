const PROFILE_Q={best:27,quality:30,balanced:32,small:36};

export function estimateConversion({fileBytes,duration,settings,audio=true}){
  if(!Number.isFinite(fileBytes)||fileBytes<=0)throw Error('Invalid input size');
  if(!Number.isFinite(duration)||duration<=0)return {known:false,inputBytes:fileBytes};
  const [width,height]=String(settings.resolution).split('x').map(Number);
  const [fpsNum,fpsDen=1]=String(settings.fps).split('/').map(Number);
  const fps=fpsNum/fpsDen,eyes=settings.mode==='2d'?1:2;
  const q=settings.q??PROFILE_Q[settings.preset]??30;
  // A deliberately broad range. MobiClip size depends heavily on source motion
  // and detail, so the UI must never present this as a promised final size.
  const videoBitsPerSecond=width*height*fps*eyes*.20*2**((30-q)/8);
  const audioBitsPerSecond=audio?(settings.movieAudio?384000:352800):0;
  const center=(videoBitsPerSecond+audioBitsPerSecond)*duration/8;
  const minimum=Math.max(4096,Math.floor(center*.55));
  const maximum=Math.max(minimum,Math.ceil(center*1.8));
  const temporaryBytes=settings.movieAudio?Math.ceil(maximum*2.15):maximum;
  return {known:true,inputBytes:fileBytes,minimum,maximum,temporaryBytes,duration};
}

export function totalEstimate(items){
  const known=items.filter(item=>item.estimate?.known);
  return {
    known:known.length,
    unknown:items.length-known.length,
    inputBytes:items.reduce((sum,item)=>sum+(item.file?.size||0),0),
    minimum:known.reduce((sum,item)=>sum+item.estimate.minimum,0),
    maximum:known.reduce((sum,item)=>sum+item.estimate.maximum,0),
    peakTemporary:known.reduce((max,item)=>Math.max(max,item.estimate.temporaryBytes),0),
  };
}

export function formatBytes(bytes){
  if(!Number.isFinite(bytes))return 'Unavailable';
  if(bytes>=1e9)return (bytes/1e9).toFixed(bytes>=10e9?1:2)+' GB';
  if(bytes>=1e6)return (bytes/1e6).toFixed(bytes>=10e6?1:2)+' MB';
  if(bytes>=1e3)return (bytes/1e3).toFixed(1)+' KB';
  return Math.round(bytes)+' B';
}
