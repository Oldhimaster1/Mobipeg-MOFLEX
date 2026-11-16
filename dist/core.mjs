// Faithful port of MobiPEG_Studio_V15.py orchestration. The codec is native WASM.
export const PRESETS={best:{q:27,search:9,me:'umh'},quality:{q:30,search:9,me:'hex'},balanced:{q:32,search:7,me:'hex'},small:{q:36,search:7,me:'hex'}};
export const FILTERS={detail:null,clean:'hqdn3d=0.7:1.1:0:0',smooth:'hqdn3d=1.4:1.8:0:0',bilateral:'bilateral=sigmaS=1.2:sigmaR=0.035:planes=1'};
export const RATES=['24','25','30','24000/1001','30000/1001'];
export const RESOLUTIONS=['400x240','400x224','320x240'];
export function rate(s){const [n,d=1]=String(s).split('/').map(Number);return n/d;}
export function validate(s){if(s.engine!==undefined&&!['auto','scalar','simd'].includes(s.engine))throw Error('Unknown WASM engine');if(!['2d','full-sbs','half-sbs'].includes(s.mode)||!PRESETS[s.preset]||!Object.hasOwn(FILTERS,s.filter)||!RATES.includes(s.fps)||!RESOLUTIONS.includes(s.resolution)||!['auto','on','off'].includes(s.motion))throw Error('Unsupported conversion setting');if(s.q!==null&&(!Number.isInteger(s.q)||s.q<12||s.q>59))throw Error('Quantizer must be 12–59');if(s.maxMB!==null&&(!Number.isFinite(s.maxMB)||s.maxMB<0.004096))throw Error('Maximum size must be at least 0.004096 MB');return s;}
export function codedRate(s){if(s.mode==='2d')return s.fps;const [n,d]=s.fps.split('/');return d?`${Number(n)*2}/${d}`:String(Number(n)*2);}
export function scale(w,h,sar,clean){return [`setsar=${sar}`,`scale=${w}:${h}:force_original_aspect_ratio=decrease:force_divisible_by=2:${sar===2?'reset_sar=1:':''}in_range=auto:out_range=tv:flags=lanczos`,`pad=${w}:${h}:(ow-iw)/2:(oh-ih)/2`,'setsar=1',...(clean?[clean]:[]),'format=yuv420p'].join(',');}
export function filters(s){const[w,h]=s.resolution.split('x').map(Number),clean=FILTERS[s.filter];if(s.mode==='2d')return ['-vf',`fps=${s.fps},${scale(w,h,1,clean)}`];const eye=scale(w,h,s.mode==='half-sbs'?2:1,clean),tb=`1/(2*(${s.fps}))`;return ['-filter_complex',`[0:v:0]fps=${s.fps},split=2[left][right];[left]crop=iw/2:ih:0:0,${eye},settb=expr=${tb},setpts=2*N[l];[right]crop=iw/2:ih:iw/2:0,${eye},settb=expr=${tb},setpts=2*N+1[r];[l][r]interleave=nb_inputs=2,format=yuv420p[vid]`,'-map','[vid]'];}
export function layout(s){return s.mode==='2d'?['-mo_layout','6']:['-mo_layout','0','-mo_interleave_input_double_rate','1'];}
export function environment(s){const p=PRESETS[s.preset],ref=s.motion==='on'||s.motion==='auto'&&['best','quality'].includes(s.preset);return {MOBI_SUBME:String(p.search),MOBI_SKIP:'0',MOBI_V11_MV_REFINE:ref?'1':'0',MOBI_V11_MV_PENALTY:'0'};}
export const base=['-hide_banner','-nostdin','-v','warning','-y','-stats_period','0.25','-progress','pipe:1','-threads','1','-filter_threads','1','-filter_complex_threads','1'];
export function encodeArgs(s,q,input='/input/source',out='/video.moflex'){validate(s);const p=PRESETS[s.preset];return [...base,'-i',input,...filters(s),'-an','-c:v','mobiclip','-mobiclip','1','-qp',String(12+(q-12)%6),'-mobi_qyx',String(Math.floor((q-12)/6)),'-preset','medium','-me_method',p.me,'-threads','1','-filter_complex_threads','1','-g',String(Math.ceil(rate(s.fps)*2)),...(s.mode==='2d'?[]:['-r',codedRate(s)]),...layout(s),'-f','moflex',out];}
export function encodeClipArgs(s,q,start,seconds){
  if(!Number.isFinite(start)||start<0||!Number.isFinite(seconds)||seconds<=0)throw Error('Invalid movie segment');
  const args=encodeArgs(s,q);
  args.splice(args.indexOf('-i'),0,'-ss',start.toFixed(8));
  args.splice(args.length-1,0,'-t',seconds.toFixed(8));
  return args;
}
export function audioClipArgs(s,start,seconds){
  if(!Number.isFinite(start)||start<0||!Number.isFinite(seconds)||seconds<=0)throw Error('Invalid movie audio segment');
  const args=audioArgs(s,seconds);
  const secondInput=args.indexOf('-i',args.indexOf('-i')+1);
  args.splice(secondInput,0,'-ss',start.toFixed(8));
  return args;
}
export function audioArgs(s,seconds){return [...base,'-i','/input/video.moflex','-i','/input/source','-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','pcm_s16le','-ar','44100','-ac','2','-af','apad', '-mo_audio','adpcm',...(s.mode==='2d'?[]:['-r',codedRate(s)]),...layout(s),'-t',seconds.toFixed(8),'-f','moflex','/final.moflex'];}
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
}
export async function convert({settings:s,source,run,notify=()=>{},verify=true,clip=null}){validate(s);if(clip&&(!Number.isFinite(clip.start)||clip.start<0||!Number.isFinite(clip.seconds)||clip.seconds<=0))throw Error('Invalid movie clip');notify({stage:'Inspecting video',fraction:null});const probe=await run(['-hide_banner','-i','/input/source'],{source},null,{},true);const media=parseProbe(probe.log);let q=s.q??PRESETS[s.preset].q,low=12,high=59,best=null,attempt=0;const cap=s.maxMB===null?null:Math.floor(s.maxMB*1e6),seen=new Set();
while(attempt<(cap===null?1:9)&&low<=high&&!seen.has(q)){seen.add(q);attempt++;notify({stage:`Encoding${cap===null?'':` · size trial ${attempt}/9`} · Q${q}`,fraction:0,attempt,q,duration:clip?.seconds??media.duration});const enc=await run(clip?encodeClipArgs(s,q,clip.start,clip.seconds):encodeArgs(s,q),{source},'/video.moflex',environment(s));if(!enc.frames||s.mode!=='2d'&&enc.frames%2)throw Error('Incomplete video or missing stereo eye');const seconds=enc.frames/(rate(s.fps)*(s.mode==='2d'?1:2));let blob=enc.blob;
if(media.audio){notify({stage:'Encoding ADPCM audio',fraction:0,duration:seconds});const mux=await run(clip?audioClipArgs(s,clip.start,seconds):audioArgs(s,seconds),{source,'video.moflex':blob},'/final.moflex',{});blob=mux.blob;if(mux.frames!==enc.frames)throw Error('Frame count changed during audio mux');}
notify({stage:`Candidate Q${q}: ${(blob.size/1e6).toFixed(2)} MB`,fraction:null});if(cap===null||blob.size<=cap){if(!best||q<best.q)best={q,blob,frames:enc.frames,seconds};high=q-1;}else low=q+1;if(cap===null)break;q=Math.floor((low+high)/2);}
if(!best)throw Error('Cannot meet this size limit at the coarsest V15 quantizer. Increase the limit.');if(verify){await verifyCandidate({kind:'video',blob:best.blob,frames:best.frames,seconds:best.seconds,run,notify});if(media.audio)await verifyCandidate({kind:'audio',blob:best.blob,frames:best.frames,seconds:best.seconds,run,notify});}if(cap!==null&&best.blob.size>cap)throw Error('Final size exceeds the limit');return {...best,audio:media.audio,settings:s,attempts:attempt};}
