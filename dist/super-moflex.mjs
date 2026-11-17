// CSXTRA01 trailer, interoperable with the Clownsec player and writer.
const decoder = new TextDecoder();
const MAX_SUBTITLE_BYTES = 1024 * 1024;
const read = async (file, offset, bytes) => file.slice(offset, offset + bytes).arrayBuffer();
const label = buffer => decoder.decode(buffer).split('\0')[0];

export async function readSuperMoflex(file) {
  const result = {media:file, metadata:{}, subtitles:[], alternateAudio:null, primaryLanguage:null,sections:[],poster:null};
  if (file.size < 16) return result;
  const footer = new DataView(await read(file, file.size-16, 16));
  if (label(new Uint8Array(footer.buffer,8)) !== 'CSXTRA01') return result;
  const end = file.size-16, base = Number(footer.getBigUint64(0,true));
  if (!Number.isSafeInteger(base) || base < 14 || base >= end) throw Error('Invalid SUPER MOFLEX trailer offset');
  result.media = file.slice(0,base);
  let offset = base, count = 0;
  while (offset < end) {
    if (end-offset < 8 || ++count > 256) throw Error('Invalid SUPER MOFLEX section table');
    const header = new DataView(await read(file,offset,8));
    const tag = label(new Uint8Array(header.buffer,0,4)), bytes = header.getUint32(4,true);
    offset += 8;
    if (!bytes || offset+bytes > end) throw Error('Truncated SUPER MOFLEX section');
    const section={tag,header:header.buffer,body:file.slice(offset,offset+bytes)};
    result.sections.push(section);
    if (tag === 'NFO0' && bytes <= 65536) {
      for (const line of decoder.decode(await read(file,offset,bytes)).split(/\r?\n/)) {
        const separator = line.indexOf('=');
        if (separator > 0) Object.defineProperty(result.metadata,line.slice(0,separator),
          {value:line.slice(separator+1), enumerable:true, configurable:true});
      }
    } else if (tag === 'LNG0' && bytes === 4) {
      result.primaryLanguage = label(await read(file,offset,4));
    } else if (tag === 'SUB0' || tag === 'SUB1') {
      const extra = tag === 'SUB1' ? 4 : 0;
      if (bytes > extra && bytes-extra <= MAX_SUBTITLE_BYTES && result.subtitles.length < 16) {
        const language = extra ? label(await read(file,offset,4)) : 'SUB';
        result.subtitles.push({language,text:file.slice(offset+extra,offset+bytes),section});
      }
    } else if ((tag === 'AUD1' || tag === 'AUD0') && !result.alternateAudio) {
      const extra = tag === 'AUD1' ? 12 : 8;
      if (bytes <= extra) throw Error('Invalid alternate audio header');
      const audio = new DataView(await read(file,offset,extra));
      const rate = audio.getUint32(0,true), channels = audio.getUint16(4,true), samples = audio.getUint16(6,true);
      const packetBytes = channels*(4+samples/2);
      if (rate < 8000 || rate > 192000 || ![1,2].includes(channels) ||
          samples < 256 || samples > 8192 || samples%256 || (bytes-extra)%packetBytes)
        throw Error('Unsupported alternate audio packet format');
      result.alternateAudio = {data:file.slice(offset+extra,offset+bytes),rate,channels,samples,packetBytes,
        language:extra===12?label(new Uint8Array(audio.buffer,8)):'ALT'};
    } else if (tag === 'ART5' && bytes >= 4 && bytes<=4*1024*1024) {
      const dimensions=new DataView(await read(file,offset,4));
      const width=dimensions.getUint16(0,true),height=dimensions.getUint16(2,true);
      if(width&&height&&bytes===4+width*height*2)
        result.poster={width,height,data:file.slice(offset+4,offset+bytes)};
    }
    offset += bytes;
  }
  return result;
}

export function languageHeader(language) {
  if (!/^[a-z0-9]{1,3}$/i.test(language))throw Error('Enter one to three letters or digits for the language.');
  const bytes=new Uint8Array(4);
  bytes.set(new TextEncoder().encode(language.toUpperCase()));
  return bytes;
}

export function metadataSection(fields) {
  const lines=[];
  for(const [key,value] of Object.entries(fields)){
    if (!/^[a-z][a-z0-9_]{0,63}$/i.test(key)||/[\x00-\x1f]/.test(value))throw Error('Metadata fields must fit on one line.');
    lines.push(key+'='+value);
  }
  const output=new TextEncoder().encode(lines.join('\n')+'\n');
  if(output.length>65536)throw Error('Metadata exceeds 65,536 bytes.');
  return output;
}

export function writeSuperMoflex(original, additions, removed=new Set()) {
  const retained=original.sections.filter(section=>!removed.has(section));
  if(retained.length+additions.length>256||
      [...retained,...additions].filter(section=>['SUB0','SUB1'].includes(section.tag)).length>16)
    throw Error('A SUPER MOFLEX can contain up to 16 subtitle tracks and 256 sections.');
  const parts=[original.media];
  let size=original.media.size;
  for(const {header,body} of retained){parts.push(header,body);size+=8+body.size;}
  for(const {tag,body} of additions){
    if(!/^[A-Z0-9]{4}$/.test(tag)||!body.size||body.size>0xffffffff)throw Error('Invalid trailer section.');
    const header=new Uint8Array(8);
    header.set(new TextEncoder().encode(tag));
    new DataView(header.buffer).setUint32(4,body.size,true);
    parts.push(header,body);
    size+=8+body.size;
  }
  if(parts.length>1){
    const footer=new Uint8Array(16);
    new DataView(footer.buffer).setBigUint64(0,BigInt(original.media.size),true);
    footer.set(new TextEncoder().encode('CSXTRA01'),8);
    parts.push(footer);
    size+=16;
  }
  if(size>0xffffffff)throw Error('The output exceeds the FAT32 limit of 4,294,967,295 bytes.');
  return new Blob(parts,{type:'application/octet-stream'});
}

function cueTime(value) {
  const match = /^(\d+):(\d{2}):(\d{2})[.,](\d{1,3})$/.exec(value.trim());
  return match ? +match[1]*3600 + +match[2]*60 + +match[3] + Number('0.'+match[4]) : NaN;
}

export function subtitleCues(text) {
  const cues = [];
  const add = (start,end,body) => {
    const from = cueTime(start), until = cueTime(end);
    if (Number.isFinite(from) && until > from && body.trim()) cues.push({from,until,text:body.trim()});
  };
  if (/^\[Events\]/im.test(text)) {
    let fields=[];
    for(const line of text.split(/\r?\n/)) {
      if (/^Format:/i.test(line)) fields=line.slice(7).toLowerCase().split(',').map(x=>x.trim());
      if (!/^Dialogue:/i.test(line) || fields.at(-1)!=='text') continue;
      const parts=line.slice(9).split(',');
      const start=fields.indexOf('start'), end=fields.indexOf('end');
      if(start>=0&&end>=0&&parts.length>=fields.length)
        add(parts[start],parts[end],parts.slice(fields.length-1).join(',').replace(/\{[^}]*\}/g,'').replace(/\\[Nn]/g,'\n'));
    }
  } else {
    for (const block of text.replace(/\r/g,'').split(/\n[ \t]*\n/)) {
      const lines=block.split('\n'), at=lines.findIndex(line=>line.includes('-->'));
      if(at<0) continue;
      const [from,to]=lines[at].trim().split(/\s+-->\s+/);
      if(to) add(from,to.split(/\s+/)[0],lines.slice(at+1).join('\n').replace(/<\/?(?:i|b|u|font)\b[^>]*>/gi,''));
    }
  }
  let maximum=0;
  return cues.sort((a,b)=>a.from-b.from).map(cue=>({...cue,maximum:maximum=Math.max(maximum,cue.until)}));
}

export function subtitlesAt(cues, time) {
  let low=0,high=cues.length;
  while(low<high){
    const mid=(low+high)>>1;
    if(cues[mid].from<=time)low=mid+1;else high=mid;
  }
  const visible=[];
  for(let i=low-1;i>=0&&cues[i].maximum>time;i--)if(cues[i].until>time)visible.push(cues[i].text);
  return visible.reverse().join('\n');
}

const steps=[7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,80,88,97,
  107,118,130,143,157,173,190,209,230,253,279,307,337,371,408,449,494,544,598,658,724,796,876,
  963,1060,1166,1282,1411,1552,1707,1878,2066,2272,2499,2749,3024,3327,3660,4026,4428,4871,
  5358,5894,6484,7132,7845,8630,9493,10442,11487,12635,13899,15289,16818,18500,20350,22385,
  24623,27086,29794,32767];
const indexes=[-1,-1,-1,-1,2,4,6,8];
const clamp=(value,min,max)=>Math.min(max,Math.max(min,value));

export async function readAlternateAudio(track,start,seconds) {
  const {data,rate,channels,samples,packetBytes}=track;
  const from=Math.max(0,Math.round(start*rate)), until=Math.round((start+seconds)*rate);
  const sound=new Int16Array(Math.max(0,until-from)*2);
  const first=Math.floor(from/samples), last=Math.ceil(until/samples);
  const input=new DataView(await read(data,first*packetBytes,(last-first)*packetBytes));
  for(let packet=0;packet*packetBytes<input.byteLength;packet++){
    const base=packet*packetBytes;
    for(let channel=0;channel<channels;channel++){
      let index=input.getInt16(base+channel*4,true);
      let predictor=input.getInt16(base+channel*4+2,true);
      if(index<0||index>88)throw Error('Invalid alternate audio predictor state');
      for(let sample=0;sample<samples;sample++){
        const chunk=Math.floor(sample/256)*channels+channel;
        const packed=input.getUint8(base+4*channels+chunk*128+((sample%256)>>1));
        const code=sample%2?packed>>4:packed&15;
        const diff=((2*(code&7)+1)*steps[index])>>3;
        predictor=clamp(predictor+(code&8?-diff:diff),-32768,32767);
        index=clamp(index+indexes[code&7],0,88);
        const position=(first+packet)*samples+sample-from;
        if(position>=0&&position<until-from){
          sound[position*2+channel]=predictor;
          if(channels===1)sound[position*2+1]=predictor;
        }
      }
    }
  }
  return sound.buffer;
}

export async function alternateWav(track,duration) {
  const frames=Math.min(Math.round(duration*track.rate),track.data.size/track.packetBytes*track.samples);
  const bytes=frames*4;
  if(!bytes||bytes>128*1048576)throw Error('Alternate audio is too large for browser export. Use desktop export for this movie.');
  const header=new DataView(new ArrayBuffer(44));
  const write=(offset,text)=>new Uint8Array(header.buffer,offset,text.length).set(new TextEncoder().encode(text));
  write(0,'RIFF');header.setUint32(4,36+bytes,true);write(8,'WAVEfmt ');
  header.setUint32(16,16,true);header.setUint16(20,1,true);header.setUint16(22,2,true);
  header.setUint32(24,track.rate,true);header.setUint32(28,track.rate*4,true);
  header.setUint16(32,4,true);header.setUint16(34,16,true);
  write(36,'data');header.setUint32(40,bytes,true);
  const parts=[header.buffer];
  for(let at=0;at<frames;at+=track.rate*2){
    const count=Math.min(track.rate*2,frames-at);
    const buffer=await readAlternateAudio(track,at/track.rate,count/track.rate);
    parts.push(new Blob([buffer]));
  }
  return new Blob(parts);
}
