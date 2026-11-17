// Faithful port of MobiPEG_Studio_V15.py orchestration. The codec is native WASM.
export const PRESETS={best:{q:27,search:9,me:'umh'},quality:{q:30,search:9,me:'hex'},balanced:{q:32,search:7,me:'hex'},small:{q:36,search:7,me:'hex'}};
export const FILTERS={detail:null,clean:'hqdn3d=0.7:1.1:0:0',smooth:'hqdn3d=1.4:1.8:0:0',bilateral:'bilateral=sigmaS=1.2:sigmaR=0.035:planes=1'};
export const ASPECTS=['source','4/3','16/9','16/10','5/3','21/9','1/1','9/16'];
export const RATES=['10','12','15','18','20','24000/1001','24','25','30000/1001','30','48','50','60000/1001','60'];
export const RESOLUTIONS=['400x240','400x224','400x208','400x192','400x176','400x160','384x224','352x240','320x240','320x224','320x192','320x176','256x192','256x144','512x288','640x368','640x480','800x480'];
// Only expose controls used by this custom MobiClip build; arbitrary output and
// timestamp flags would bypass its stereo and segmented-movie invariants.
export const ADVANCED_NUMBERS={subme:[2,9,1],skip:[0,65535,1],refine:[0,1,1],penalty:[0,1024,1],diagonal:[0,1,1],gop:[2,600,1],lumaSpatial:[0,20,0],chromaSpatial:[0,20,0],lumaTemporal:[0,30,0],chromaTemporal:[0,30,0],volume:[-60,12,0],highpass:[20,1000,0],lowpass:[1000,20000,0]};
export const ADVANCED_ENUMS={me:['dia','hex','umh','esa','tesa'],scaler:['neighbor','bilinear','bicubic','lanczos','spline'],inputRange:['auto','tv','pc']};
export function validateAdvanced(a){
  if(a==null)return;
  if(typeof a!=='object'||Array.isArray(a))throw Error('Invalid advanced configuration');
  for(const [key,value]of Object.entries(a)){
    if(Object.hasOwn(ADVANCED_NUMBERS,key)){
      const [min,max,integer]=ADVANCED_NUMBERS[key];
      if(typeof value!=='number'||!Number.isFinite(value)||value<min||value>max||integer&&!Number.isInteger(value))throw Error(`Invalid ${key}: ${min}…${max}${integer?' integer':''}`);
    }else if(Object.hasOwn(ADVANCED_ENUMS,key)){
      if(!ADVANCED_ENUMS[key].includes(value))throw Error(`Invalid ${key}`);
    }else throw Error(`Unsupported advanced parameter: ${key}`);
  }
  if(a.highpass!=null&&a.lowpass!=null&&a.highpass>=a.lowpass)throw Error('highpass must be below lowpass');
}
export function advancedAudioFilter(s,samples=null){const a=s.advanced??{};return [a.highpass!=null?`highpass=f=${a.highpass}`:null,a.lowpass!=null?`lowpass=f=${a.lowpass}`:null,a.volume!=null?`volume=${a.volume}dB`:null,'aresample=48000:async=0:first_pts=0','apad',samples!=null?`atrim=end_sample=${samples}`:null,'asetpts=N/SR/TB'].filter(Boolean).join(',');}
export function rate(s){const [n,d=1]=String(s).split('/').map(Number);return n/d;}
export function validateCrop(c){
  if(c==null)return;
  if(typeof c!=='object'||Array.isArray(c)||!['fit','fill','stretch'].includes(c.fit))throw Error('Invalid framing mode');
  if(c.aspect!=null&&!ASPECTS.includes(c.aspect))throw Error('Invalid crop aspect ratio');
  for(const k of Object.keys(c))if(!['fit','aspect','left','right','top','bottom'].includes(k))throw Error('Unknown crop parameter');
  for(const k of ['left','right','top','bottom'])if(c[k]!=null&&(!Number.isInteger(c[k])||c[k]<0||c[k]>16384||c[k]%2))throw Error('Crop margins must be even input pixel counts from 0 to 16384');
}
export function validate(s){if(s.speed!=null&&!['original','fast'].includes(s.speed))throw Error('Unknown encoding speed');if(s.audioCodec!=null&&!['adpcm','fastaudio'].includes(s.audioCodec))throw Error('Unknown MOFLEX audio codec');validateCrop(s.crop);validateAdvanced(s.advanced);if(s.audioTrack!==undefined&&(!Number.isInteger(s.audioTrack)||s.audioTrack<0))throw Error('Invalid audio track');if(s.workers!==undefined&&(!Number.isInteger(s.workers)||s.workers<1||s.workers>256))throw Error('Parallel worker count must be an integer between 1 and 256');if(s.engine!==undefined&&!['auto','scalar','simd'].includes(s.engine))throw Error('Unknown WASM engine');if(!['2d','full-sbs','half-sbs'].includes(s.mode)||!PRESETS[s.preset]||!Object.hasOwn(FILTERS,s.filter)||!RATES.includes(s.fps)||!RESOLUTIONS.includes(s.resolution)||!['auto','on','off'].includes(s.motion))throw Error('Unsupported conversion setting');if(s.q!==null&&(!Number.isInteger(s.q)||s.q<12||s.q>59))throw Error('Quantizer must be 12–59');if(s.maxMB!==null&&(!Number.isFinite(s.maxMB)||s.maxMB<0.004096))throw Error('Maximum size must be at least 0.004096 MB');return s;}
export function codedRate(s){if(s.mode==='2d')return s.fps;const [n,d]=s.fps.split('/');return d?`${Number(n)*2}/${d}`:String(Number(n)*2);}
export function scale(w,h,sar,clean,a={},crop={}){
  crop=crop??{};
  const edges=['left','right','top','bottom'].map(k=>crop[k]??0),[l,r,t,b]=edges;
  const framing=crop.fit??'fit',range=`in_range=${a.inputRange??'auto'}:out_range=tv:flags=${a.scaler??'lanczos'}`;
  const sizing=framing==='stretch'?`scale=${w}:${h}:reset_sar=1:${range}`:
    `scale=${w}:${h}:force_original_aspect_ratio=${framing==='fill'?'increase':'decrease'}:force_divisible_by=2:reset_sar=1:${range}`;
  return [...(edges.some(Boolean)?[`crop=iw-${l+r}:ih-${t+b}:${l}:${t}`]:[]),...(sar===2?['setsar=sar*2']:[]),...(crop.aspect&&crop.aspect!=='source'?[`crop=w='trunc(min(iw,ih*(${crop.aspect})/sar)/2)*2':h='trunc(min(ih,iw*sar/(${crop.aspect}))/2)*2':x='trunc((iw-ow)/4)*2':y='trunc((ih-oh)/4)*2'`]:[]),sizing,
    ...(framing==='stretch'?[]:[framing==='fill'?`crop=${w}:${h}:(iw-ow)/2:(ih-oh)/2`:`pad=${w}:${h}:(ow-iw)/2:(oh-ih)/2`]),
    'setsar=1',...(clean?[clean]:[]),'format=yuv420p'].join(',');
}
export function filters(s){const[w,h]=s.resolution.split('x').map(Number),a=s.advanced??{},denoise=['lumaSpatial','chromaSpatial','lumaTemporal','chromaTemporal'],customDenoise=denoise.some(k=>a[k]!=null),clean=customDenoise?'hqdn3d='+denoise.map(k=>a[k]??0).join(':'):FILTERS[s.filter];if(s.mode==='2d')return ['-vf',`fps=${s.fps},${scale(w,h,1,clean,a,s.crop)}`];const eye=scale(w,h,s.mode==='half-sbs'?2:1,clean,a,s.crop),tb=`1/(2*(${s.fps}))`;return ['-filter_complex',`[0:v:0]fps=${s.fps},split=2[left][right];[left]crop=iw/2:ih:0:0,${eye},settb=expr=${tb},setpts=2*N[l];[right]crop=iw/2:ih:iw/2:0,${eye},settb=expr=${tb},setpts=2*N+1[r];[l][r]interleave=nb_inputs=2,format=yuv420p[vid]`,'-map','[vid]'];}
export function layout(s){return s.mode==='2d'?['-mo_layout','6']:['-mo_layout','0','-mo_interleave_input_double_rate','1'];}
export function environment(s){const p=PRESETS[s.preset],ref=s.motion==='on'||s.motion==='auto'&&['best','quality'].includes(s.preset);const a=s.advanced??{};return {MOBI_SUBME:String(a.subme??(s.speed==='fast'?2:p.search)),MOBI_SKIP:String(a.skip??0),MOBI_V11_MV_REFINE:a.refine!=null?String(a.refine):ref?'1':'0',MOBI_V11_MV_PENALTY:String(a.penalty??0),...(a.diagonal!=null?{MOBI_V11_MV_DIAGONAL:String(a.diagonal)}:{})};}
export const base=['-hide_banner','-nostdin','-v','warning','-y','-stats_period','0.25','-progress','pipe:1','-threads','1','-filter_threads','1','-filter_complex_threads','1'];
export function encodeArgs(s,q,input='/input/source',out='/video.moflex'){validate(s);const p=PRESETS[s.preset];return [...base,'-i',input,...filters(s),'-an','-c:v','mobiclip','-mobiclip','1','-qp',String(12+(q-12)%6),'-mobi_qyx',String(Math.floor((q-12)/6)),'-preset','medium','-me_method',s.advanced?.me??p.me,'-threads','1','-filter_complex_threads','1','-g',String(s.advanced?.gop??Math.ceil(rate(s.fps)*2)),...(s.mode==='2d'?[]:['-r',codedRate(s)]),...layout(s),'-f','moflex',out];}
export function encodeClipArgs(s,q,start,seconds){
  if(!Number.isFinite(start)||start<0||!Number.isFinite(seconds)||seconds<=0)throw Error('Invalid movie segment');
  const args=encodeArgs(s,q);
  args.splice(args.indexOf('-i'),0,'-xerror','-ss',start.toFixed(8));
  args.splice(args.length-1,0,'-frames:v',String(Math.round(seconds*rate(s.fps))*(s.mode==='2d'?1:2)));
  return args;
}
export function audioClipArgs(s,start,seconds){
  if(!Number.isFinite(start)||start<0||!Number.isFinite(seconds)||seconds<=0)throw Error('Invalid movie audio segment');
  const args=audioArgs(s,seconds);
  const secondInput=args.indexOf('-i',args.indexOf('-i')+1);
  args.splice(secondInput,0,'-ss',start.toFixed(8));
  return args;
}
export function audioArgs(s,seconds){const samples=Math.round(seconds*48000);return [...base,'-i','/input/video.moflex','-i','/input/source','-map','0:v:0','-map',`1:a:${s.audioTrack??0}`,'-c:v','copy','-c:a','pcm_s16le','-ar','48000','-ac','2','-af',advancedAudioFilter(s,samples), '-mo_audio',s.audioCodec??'adpcm',...(s.mode==='2d'?[]:['-r',codedRate(s)]),...layout(s),'-t',(samples/48000).toFixed(8),'-f','moflex','/final.moflex'];}
export function parseProbe(log){const d=/Duration:\s*(\d+):(\d+):([\d.]+)/.exec(log);if(!/Video:/.test(log)||!d)throw Error('Cannot read video or duration. This format may not be supported.');const duration=Number(d[1])*3600+Number(d[2])*60+Number(d[3]);if(!Number.isFinite(duration)||duration<=0)throw Error('Video must have a known, positive duration');return {duration,audio:/Audio:/.test(log)};}
export function progressLine(line){const m=/^(frame|out_time_us|total_size|speed|progress)=(.*)$/.exec(line.trim());return m?{key:m[1],value:m[2].trim()}:null;}

// Verify each media stream independently. Browser builds can run each check in a
// separate Worker to release the encoding WASM instance before verification.
export async function verifyCandidate({kind,blob,frames,seconds,run,notify=()=>{}}){
  if(!['video','audio'].includes(kind))throw Error('Unknown verification stream');
  if(!(blob instanceof Blob)||!Number.isInteger(frames)||frames<=0||!Number.isFinite(seconds)||seconds<=0)throw Error('Invalid verification candidate');
  notify({stage:`Verifying complete ${kind}`,fraction:0,duration:seconds});
  const check=await run([...base,'-xerror','-i','/input/final.moflex','-map',kind==='video'?'0:v:0':'0:a:0','-f','null','-'],{'final.moflex':blob});
  if(kind==='video'&&check.frames!==frames)throw Error('Decoded frame count does not match encoded video');
  if(kind==='audio'&&Number.isFinite(check.seconds)&&Math.abs(check.seconds-seconds)>.05)throw Error('Decoded audio duration does not match video');
}
export async function convert({settings:s,source,run,notify=()=>{},verify=true,clip=null,media:knownMedia=null}){validate(s);if(clip&&(!Number.isFinite(clip.start)||clip.start<0||!Number.isFinite(clip.seconds)||clip.seconds<=0))throw Error('Invalid movie clip');let media;
if(knownMedia!==null){
  if(typeof knownMedia!=='object'||!Number.isFinite(knownMedia.duration)||knownMedia.duration<=0||typeof knownMedia.audio!=='boolean')throw Error('Invalid inspected movie metadata');
  media={duration:knownMedia.duration,audio:knownMedia.audio};
}else{notify({stage:'Inspecting video',fraction:null});const probe=await run(['-hide_banner','-i','/input/source'],{source},null,{},true);media=parseProbe(probe.log);}
let q=s.q??PRESETS[s.preset].q,low=12,high=59,best=null,attempt=0;const cap=s.maxMB===null?null:Math.floor(s.maxMB*1e6),seen=new Set();
while(attempt<(cap===null?1:9)&&low<=high&&!seen.has(q)){seen.add(q);attempt++;notify({stage:`Encoding${cap===null?'':` · size trial ${attempt}/9`} · Q${q}`,fraction:0,attempt,q,duration:clip?.seconds??media.duration});const enc=await run(clip?encodeClipArgs(s,q,clip.start,clip.seconds):encodeArgs(s,q),{source},'/video.moflex',environment(s));if(!enc.frames&&clip&&enc.code===0)return {empty:true,frames:0,seconds:0,audio:media.audio,settings:s,attempts:attempt};if(!enc.frames||s.mode!=='2d'&&enc.frames%2)throw Error('Incomplete video or missing stereo eye');const seconds=enc.frames/(rate(s.fps)*(s.mode==='2d'?1:2));let blob=enc.blob;
if(media.audio){let audioSettings=s;notify({stage:`Encoding ${(s.audioCodec??'adpcm')==='fastaudio'?'FastAudio':'ADPCM'} audio`,fraction:0,duration:seconds});let mux;try{mux=await run(clip?audioClipArgs(audioSettings,clip.start,seconds):audioArgs(audioSettings,seconds),{source,'video.moflex':blob},'/final.moflex',{});}catch(error){if(s.audioCodec!=='fastaudio'||clip)throw error;notify({stage:'FastAudio unavailable; retrying with compatible ADPCM',fraction:0,duration:seconds});audioSettings={...s,audioCodec:'adpcm'};mux=await run(audioArgs(audioSettings,seconds),{source,'video.moflex':blob},'/final.moflex',{});}blob=mux.blob;if(mux.frames!==enc.frames)throw Error('Frame count changed during audio mux');}
notify({stage:`Candidate Q${q}: ${(blob.size/1e6).toFixed(2)} MB`,fraction:null});if(cap===null||blob.size<=cap){if(!best||q<best.q)best={q,blob,frames:enc.frames,seconds};high=q-1;}else low=q+1;if(cap===null)break;q=Math.floor((low+high)/2);}
if(!best)throw Error('Cannot meet this size limit at the coarsest V15 quantizer. Increase the limit.');if(verify){await verifyCandidate({kind:'video',blob:best.blob,frames:best.frames,seconds:best.seconds,run,notify});if(media.audio)await verifyCandidate({kind:'audio',blob:best.blob,frames:best.frames,seconds:best.seconds,run,notify});}if(cap!==null&&best.blob.size>cap)throw Error('Final size exceeds the limit');return {...best,audio:media.audio,settings:s,attempts:attempt};}

export function audioTracks(log){return [...log.matchAll(/Stream #0:\d+(?:\[[^\]]*\])?(?:\(([^)]+)\))?[^\n]*Audio: ([^\n]+)/g)].map((m,index)=>({index,label:`${index}: ${m[1]||'Unknown language'} — ${m[2]}`}));}

// A single displayed frame (two coded eyes in stereo), never an entire movie.
export function previewSourceArgs(s,start){
  validate(s);if(!Number.isFinite(start)||start<0)throw Error('Invalid preview timestamp');
  return [...base,'-ss',start.toFixed(8),'-i','/input/source',...filters(s),'-an',
    ...(s.mode==='2d'?[]:['-r',codedRate(s)]),'-frames:v',s.mode==='2d'?'1':'2','-pix_fmt','rgba','-c:v','rawvideo','-threads','1','-f','rawvideo','/source.rgba'];
}
export function previewDecodeArgs(s){return [...base,'-i','/input/preview.moflex','-map','0:v:0','-an','-frames:v',s.mode==='2d'?'1':'2','-pix_fmt','rgba','-c:v','rawvideo','-threads','1','-f','rawvideo','/decoded.rgba'];}
export async function previewFrame({settings:s,source,start,run,notify=()=>{}}){
  validate(s);const q=s.q??PRESETS[s.preset].q,eyes=s.mode==='2d'?1:2,[width,height]=s.resolution.split('x').map(Number);
  notify({stage:'Rendering framed source',fraction:null});
  const original=await run(previewSourceArgs(s,start),{source},'/source.rgba');
  notify({stage:'Encoding MobiClip preview',fraction:null});
  const encoded=await run(encodeClipArgs(s,q,start,1/rate(s.fps)),{source},'/video.moflex',environment(s));
  if(encoded.frames!==eyes)throw Error('Preview frame is unavailable at this timestamp. Choose an earlier position.');
  notify({stage:'Decoding MobiClip preview',fraction:null});
  const decoded=await run(previewDecodeArgs(s),{'preview.moflex':encoded.blob},'/decoded.rgba');
  const bytes=width*height*4*eyes;
  if(original.blob.size!==bytes||decoded.blob.size!==bytes||decoded.frames!==eyes)throw Error('Preview frame size does not match the selected resolution');
  return {original:original.blob,decoded:decoded.blob,width,height,eyes,q,encodedBytes:encoded.blob.size};
}

export async function previewMotion({settings:s,source,start,run,notify=()=>{}}){
  validate(s);
  const eyes=s.mode==='2d'?1:2,fps=rate(s.fps),q=s.q??PRESETS[s.preset].q;
  const [w,h]=s.resolution.split('x').map(Number);
  const factor=Math.min(1,256/w,156/h);
  const width=Math.max(2,Math.floor(w*factor/2)*2),height=Math.max(2,Math.floor(h*factor/2)*2);
  const stride=Math.ceil(fps/12);
  notify({stage:'Encoding motion preview',fraction:null});
  const encoded=await run(encodeClipArgs(s,q,start,2.5),{source},'/video.moflex',environment(s));
  const paired=Math.floor(encoded.frames/eyes);
  if(!paired)throw Error('Preview is unavailable at this timestamp. Choose an earlier position.');
  const frames=Math.ceil(paired/stride);
  const sample=`select='lt(n,${paired*eyes})*not(mod(floor(n/${eyes}),${stride}))',scale=${width}:${height}:flags=bicubic`;
  const raw=['-an','-frames:v',String(frames*eyes),'-fps_mode','passthrough',
    '-pix_fmt','rgba','-c:v','rawvideo','-threads','1','-f','rawvideo'];
  const framing=filters(s);
  framing[1]=eyes===1?framing[1]+','+sample:framing[1].replace(/\[vid\]$/,','+sample+'[vid]');
  notify({stage:'Rendering framed source',fraction:null});
  const original=await run([...base,'-ss',start.toFixed(8),'-i','/input/source',...framing,...raw,'/source.rgba'],
    {source},'/source.rgba');
  notify({stage:'Decoding motion preview',fraction:null});
  const decoded=await run([...base,'-i','/input/preview.moflex','-vf',sample,...raw,'/decoded.rgba'],
    {'preview.moflex':encoded.blob},'/decoded.rgba');
  const bytes=width*height*4*eyes*frames;
  if(original.blob.size!==bytes||decoded.blob.size!==bytes)
    throw Error('Motion preview frame counts differ. Try another position or the still preview.');
  return {original:original.blob,decoded:decoded.blob,width,height,eyes,q,frames,
    previewFPS:fps/stride,encodedBytes:encoded.blob.size};
}
