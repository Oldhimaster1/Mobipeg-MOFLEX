import {inspectMovieSegment} from './movie.mjs';

export function parseMoflexVideoDescriptor(descriptors) {
  let p=0;
  const varint=()=>{
    let value=0,b=0,count=0;
    do {
      if(p>=descriptors.length||++count>4)throw Error('Invalid MOFLEX descriptor');
      b=descriptors[p++];value=(value<<7)|(b&127);
    }while(b&128);
    return value;
  };
  while(p<descriptors.length){
    const type=varint(),length=varint();
    if(type===0)break;
    if(length>descriptors.length-p)throw Error('Malformed MOFLEX video descriptor');
    if(type===3){
      if(length<13)throw Error('Unsupported MOFLEX video descriptor');
      const b=descriptors.subarray(p,p+length);
      const numerator=((b[0]*16777216)+(b[1]<<16)+(b[2]<<8)+b[3]);
      const denominator=(b[4]<<8)+b[5];
      const width=(b[6]<<8)+b[7],height=(b[8]<<8)+b[9],layout=b[12];
      if(!numerator||!denominator||!width||!height||width>4096||height>4096||![0,6].includes(layout))
        throw Error('Unsupported MOFLEX frame geometry or frame rate');
      const displayFPS=numerator/denominator;
      return {width,height,layout,displayFPS,codedFPS:displayFPS*(layout===0?2:1),eyes:layout===0?2:1};
    }
    p+=length;
  }
  throw Error('No MobiClip video stream in this MOFLEX');
}

export async function inspectPlayableMoflex(file){
  const segment=await inspectMovieSegment(file);
  const video=parseMoflexVideoDescriptor(segment.descriptors);
  return {...video,frames:segment.frames,duration:segment.frames/video.codedFPS};
}

export function displayedCodedFrame(displayFrame,eyes,eye=0){
  if(!Number.isInteger(displayFrame)||displayFrame<0||![1,2].includes(eyes)||!Number.isInteger(eye)||eye<0||eye>=eyes)
    throw Error('Invalid player frame position');
  return displayFrame*eyes+eye;
}
