// Subtitle timing adjustments used by the local SUPER MOFLEX trailer editor.
// Shift cue timestamps without touching ASS/SSA styling or subtitle text.
const stamp=/^(\d+):(\d{2}):(\d{2})([.,])(\d{1,3})$/;
function parseTimestamp(text){
  const match=stamp.exec(text.trim());
  if(!match||Number(match[2])>59||Number(match[3])>59)throw Error('Invalid subtitle timestamp');
  const digits=match[5].length;
  const milliseconds=(Number(match[1])*3600+Number(match[2])*60+Number(match[3]))*1000+
    Number(match[5])*10**(3-digits);
  return {milliseconds,digits,separator:match[4],hourDigits:match[1].length};
}
function formatTimestamp(original,value){
  const {digits,separator,hourDigits}=parseTimestamp(original);
  const unit=10**(3-digits),units=Math.round(Math.max(0,value)/unit);
  const perHour=3600000/unit,perMinute=60000/unit,perSecond=1000/unit;
  const h=Math.floor(units/perHour),m=Math.floor((units%perHour)/perMinute),
    s=Math.floor((units%perMinute)/perSecond),frac=units%perSecond;
  return String(h).padStart(hourDigits,'0')+':'+String(m).padStart(2,'0')+':'+
    String(s).padStart(2,'0')+separator+String(frac).padStart(digits,'0');
}

export function shiftSubtitleTiming(text,offsetMs){
  if(!Number.isInteger(offsetMs)||Math.abs(offsetMs)>300000)
    throw Error('Subtitle timing adjustment must be an integer between -300000 and 300000 ms.');
  if(!offsetMs)return text;
  const eol=text.includes('\r\n')?'\r\n':'\n';
  const matchTimestamp='(\\d+:\\d{2}:\\d{2}[.,]\\d{1,3})';
  if(/^\s*\[Events\]/im.test(text)){
    let inEvents=false,fields=[],changed=0;
    const output=[];
    for(const line of text.split(/\r?\n/)){
      const section=/^\s*\[([^\]]+)\]/.exec(line);
      if(section)inEvents=section[1].toLowerCase()==='events';
      if(inEvents&&/^\s*Format:/i.test(line))
        fields=line.replace(/^\s*Format:\s*/i,'').split(',').map(value=>value.trim().toLowerCase());
      if(!inEvents||!/^\s*Dialogue:/i.test(line)){output.push(line);continue;}
      const start=fields.indexOf('start'),end=fields.indexOf('end');
      if(start<0||end<0||fields.length<3||fields.at(-1)!=='text')
        throw Error('Unsupported ASS/SSA event format.');
      const prefix=/^(\s*Dialogue:\s*)/i.exec(line)[0],remainder=line.slice(prefix.length),parts=[];
      let from=0;
      for(let j=0;j<fields.length-1;j++){
        const boundary=remainder.indexOf(',',from);
        if(boundary<0)throw Error('Incomplete ASS/SSA dialogue event.');
        parts.push(remainder.slice(from,boundary));from=boundary+1;
      }
      parts.push(remainder.slice(from));
      const startText=parts[start].trim(),endText=parts[end].trim();
      const startMs=parseTimestamp(startText).milliseconds+offsetMs,
        endMs=parseTimestamp(endText).milliseconds+offsetMs;
      if(endMs<=0)continue;
      for(const field of [start,end]){
        const original=parts[field],value=original.trim(),ms=field===start?startMs:endMs;
        parts[field]=original.replace(value,formatTimestamp(value,ms));
      }
      output.push(prefix+parts.join(','));changed++;
    }
    if(!changed)throw Error('No subtitle dialogue remains after applying the timing adjustment.');
    return output.join(eol);
  }
  const timeline=new RegExp('^(\\s*)'+matchTimestamp+'(\\s*-->\\s*)'+matchTimestamp+'(.*)$');
  let changed=0;
  const blocks=[];
  for(const block of text.split(/\r?\n\s*\r?\n/)){
    const lines=block.split(/\r?\n/),index=lines.findIndex(line=>line.includes('-->'));
    if(index<0){blocks.push(block.replace(/\r?\n/g,eol));continue;}
    const match=timeline.exec(lines[index]);
    if(!match)throw Error('Invalid SRT timing line.');
    const start=parseTimestamp(match[2]).milliseconds+offsetMs,
      end=parseTimestamp(match[4]).milliseconds+offsetMs;
    if(end<=0)continue;
    lines[index]=match[1]+formatTimestamp(match[2],start)+match[3]+
      formatTimestamp(match[4],end)+match[5];
    blocks.push(lines.join(eol));changed++;
  }
  if(!changed)throw Error('No subtitle cues remain after applying the timing adjustment.');
  return blocks.join(eol+eol);
}
