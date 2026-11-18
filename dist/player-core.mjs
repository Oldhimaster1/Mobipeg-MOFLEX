import {inspectMovieSegment} from './movie.mjs?v=20261118t';

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
      if(!numerator||!denominator||!width||!height||width>4096||height>4096||layout>6)
        throw Error('Unsupported MOFLEX frame geometry or frame rate');
      const displayFPS=numerator/denominator;
      const eyes=layout===6?1:2,packing=layout<2?'interleaved':layout<4?'top-bottom':layout<6?'side-by-side':'2d';
      const eyeWidth=packing==='side-by-side'?width/2:width,eyeHeight=packing==='top-bottom'?height/2:height;
      if(!Number.isInteger(eyeWidth)||!Number.isInteger(eyeHeight))throw Error('Invalid packed stereo dimensions');
      return {width,height,eyeWidth,eyeHeight,layout,packing,leftFirst:layout<2?layout===1:layout%2===0,displayFPS,codedFPS:displayFPS*(layout<2?2:1),eyes};
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

export function displayedCodedFrame(displayFrame,eyes,eye=0,packing='interleaved',leftFirst=true){
  if(!Number.isInteger(displayFrame)||displayFrame<0||![1,2].includes(eyes)||!Number.isInteger(eye)||eye<0||eye>=eyes)
    throw Error('Invalid player frame position');
  return displayFrame*(packing==='interleaved'?eyes:1)+(packing==='interleaved'?(leftFirst?eye:1-eye):0);
}

export function classifyStereoPixels(video,{width,height,packing,eyes},frames){
  if(eyes===1)return {kind:'2d',difference:null};
  const bytes=width*height*4,available=Math.min(frames,Math.floor(video.byteLength/bytes));
  let total=0,count=0;
  const sample=(a,b)=>{for(let i=0;i<a.length;i+=16){total+=Math.abs(a[i]-b[i])+Math.abs(a[i+1]-b[i+1])+Math.abs(a[i+2]-b[i+2]);count+=3;}};
  if(packing==='interleaved')for(let n=0;n+1<available;n+=2)sample(new Uint8Array(video,n*bytes,bytes),new Uint8Array(video,(n+1)*bytes,bytes));
  else for(let n=0;n<available;n++){
    const f=new Uint8Array(video,n*bytes,bytes);
    if(packing==='side-by-side')for(let y=0;y<height;y++)sample(f.subarray((y*width)*4,(y*width+width/2)*4),f.subarray((y*width+width/2)*4,(y*width+width)*4));
    else sample(f.subarray(0,bytes/2),f.subarray(bytes/2));
  }
  const difference=total/(Math.max(1,count)*255);
  return {kind:difference<.002?'duplicated-eyes':'genuine-3d',difference};
}
