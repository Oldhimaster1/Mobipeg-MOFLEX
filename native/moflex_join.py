"""Streaming join of independently encoded V15 MOFLEX ranges.

This is the desktop equivalent of dist/movie.mjs. It builds a fresh front
seek table and patches media clocks/counters; binary file concatenation alone
would create an unseekable/broken movie. Input files are never modified.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import os
import struct

BLOCK=4096
MAX_INDEX_ENTRIES=50000
FAT32_LIMIT=0xffffffff
FAT32_MESSAGE=('Output exceeds the FAT32 limit of 4,294,967,295 bytes. '
               'Increase compression, lower the resolution or frame rate, or split the movie.')


def require(ok, reason):
    if not ok:raise ValueError('MOFLEX join: '+reason)


def checksum(stamp):
    value=0xaaaa
    for shift in range(0,64,16):value^=(stamp>>shift)&0xffff
    return value


def set_sync(block, stamp):
    struct.pack_into('>HHQH',block,0,0x4c32,checksum(stamp),stamp,BLOCK-1)


def read_sync(block):
    require(len(block)==BLOCK and block[:2]==b'L2', 'invalid sync header')
    require(int.from_bytes(block[12:14],'big')==BLOCK-1,'unsupported block size')
    stamp=struct.unpack_from('>Q',block,4)[0]
    require(int.from_bytes(block[2:4],'big')==checksum(stamp),'bad sync checksum')
    pos=14

    def variable():
        nonlocal pos
        result=0
        for _ in range(4):
            require(pos<BLOCK,'truncated descriptor')
            value=block[pos];pos+=1
            result=(result<<7)|(value&127)
            if not value&128:return result
        raise ValueError('descriptor varint too long')

    data_stream=None;streams=0
    for _ in range(16):
        typ,length=variable(),variable()
        if typ==0:
            require(length==0,'bad descriptor terminator')
            break
        require(pos+length<BLOCK,'descriptor outside block')
        if typ==4:
            require(length==2,'unsupported data descriptor')
            data_stream=block[pos]
        if typ==3:streams+=1
        pos+=length
    require(data_stream is not None and streams==1,'expected MobiClip video and index stream')
    return {'stamp':stamp,'flag':pos,'descriptors':bytes(block[14:pos]),'data':data_stream}


def read_ep(block,pos):
    bit=pos*8

    def one():
        nonlocal bit
        require(bit<BLOCK*8,'truncated EP header')
        value=(block[bit//8]>>(7-(bit%8)))&1
        bit+=1
        return value

    def bits(count):
        result=0
        for _ in range(count):result=result*2+one()
        return result

    length_code=1
    while not one():
        length_code+=1
        require(length_code<=5,'invalid EP stream code')
    stream=bits(length_code);end=bool(one())
    if end:bits(32)
    length=bits(13)+1
    at=(bit+7)//8
    require(at+length<=BLOCK,'EP outside block')
    return stream,end,at,length


def make_ep(stream,end,size):
    require(0< size<=8192 and 0<=stream<32,'invalid EP packet')
    length=1 if stream<=1 else stream.bit_length()
    bits=[0]*(length-1)+[1]

    def add(value,count):
        bits.extend((value>>bit)&1 for bit in range(count-1,-1,-1))

    add(stream,length);bits.append(int(end))
    if end:bits.extend([1,0,0,1]+[0]*28)
    add(size-1,13)
    result=bytearray((len(bits)+7)//8)
    for i,value in enumerate(bits):
        if value:result[i//8]|=1<<(7-(i%8))
    return result


def create_front(descriptors,data_stream,entries,frames,duration_us):
    require(0<frames<=0xffffffff,'invalid frame count')
    raw=bytearray(struct.pack('<IIII',len(entries),frames,min(duration_us,0xffffffff),0))
    for frame,stamp,offset in entries:raw.extend(struct.pack('<QQQ',frame,stamp,offset))
    blocks=[];cursor=0
    while cursor<len(raw):
        block=bytearray(BLOCK);pos=0
        if not blocks:
            set_sync(block,1);block[14:14+len(descriptors)]=descriptors;pos=14+len(descriptors)
        block[pos]=2<<2;pos+=1
        remaining=len(raw)-cursor
        header=make_ep(data_stream,True,min(remaining,8192))
        if remaining+len(header)<=BLOCK-pos:
            block[pos:pos+len(header)]=header;pos+=len(header)
            block[pos:pos+remaining]=raw[cursor:];cursor=len(raw)
        else:
            overhead=len(make_ep(data_stream,False,1))
            take=min(remaining-1,BLOCK-pos-overhead)
            require(take>0,'index packet cannot fit')
            header=make_ep(data_stream,False,take)
            block[pos:pos+len(header)]=header;pos+=len(header)
            block[pos:pos+take]=raw[cursor:cursor+take];cursor+=take
        blocks.append(block)
        require(len(blocks)<=1024,'index has too many blocks')
    return b''.join(blocks)


@dataclass
class Part:
    path:Path
    front:int
    size:int
    frames:int
    entries:list
    descriptors:bytes
    data_stream:int
    time_offset:int=0


def inspect(path,expected_frames=None):
    path=Path(path);size=path.stat().st_size
    require(size>=BLOCK*2 and size%BLOCK==0,'segment size invalid')
    with path.open('rb') as file:
        header=file.read(BLOCK);meta=read_sync(header)
        pieces=[];done=False;block=0
        while not done:
            require(block*BLOCK<size and block<1024,'truncated seek table')
            data=header if block==0 else file.read(BLOCK)
            offset=meta['flag'] if block==0 else 0
            require(data[offset]>>2==2,'index block has wrong counter')
            stream,done,at,length=read_ep(data,offset+1)
            require(stream==meta['data'],'unexpected seek stream')
            pieces.append(data[at:at+length]);block+=1
        front=block*BLOCK
        raw=b''.join(pieces)
        require(len(raw)>=16,'missing seek table')
        count,frames,_,_=struct.unpack_from('<IIII',raw)
        require(0<count<=MAX_INDEX_ENTRIES and len(raw)==16+count*24,'bad seek entry count')
        if expected_frames is not None:require(frames==expected_frames,'frame count mismatch')
        entries=[struct.unpack_from('<QQQ',raw,16+i*24) for i in range(count)]
        previous=None
        for frame,stamp,offset in entries:
            require(front<=offset<size and offset%BLOCK==0,'bad seek offset')
            if previous:
                require(frame>=previous[0] and stamp>previous[1] and offset>previous[2],'unsorted seek table')
            previous=(frame,stamp,offset)
        require(entries[0][2]==front,'missing first media sync')
        first=file.read(BLOCK)
        media=read_sync(first)
        require(media['descriptors']==meta['descriptors'] and media['stamp']==entries[0][1],'media sync mismatch')
        return Part(path,front,size-front,frames,entries,meta['descriptors'],meta['data'])


def join(parts,frames_per_second:Fraction,output:Path,callback=lambda fraction:None,max_bytes=None):
    """Join (path, expected frame count) pairs in *timeline order*."""
    require(parts,'nothing to assemble')
    inspected=[inspect(path,count) for path,count in parts]
    require(all(p.descriptors==inspected[0].descriptors and p.data_stream==inspected[0].data_stream for p in inspected),'incompatible segments')
    frames=sum(p.frames for p in inspected)
    require(frames<=0xffffffff,'frame index capacity exceeded')
    require(sum(len(p.entries) for p in inspected)<=MAX_INDEX_ENTRIES,'seek index capacity exceeded')
    rate=Fraction(frames_per_second)
    require(rate>0,'invalid coded frame rate')
    entries=[];frame_offset=0;media_offset=0
    for part in inspected:
        part.time_offset=(frame_offset*1000000*rate.denominator)//rate.numerator
        for frame,stamp,offset in part.entries:
            entries.append((frame+frame_offset,stamp+part.time_offset,media_offset+offset-part.front))
        frame_offset+=part.frames;media_offset+=part.size
    duration_us=(frames*1000000*rate.denominator)//rate.numerator
    first=inspected[0]
    placeholder=create_front(first.descriptors,first.data_stream,entries,frames,duration_us)
    front_size=len(placeholder)
    front=create_front(first.descriptors,first.data_stream,[(f,t,o+front_size) for f,t,o in entries],frames,duration_us)
    require(len(front)==front_size,'seek table changed size')
    require(front_size+media_offset<=FAT32_LIMIT,FAT32_MESSAGE)
    if max_bytes is not None:
        require(front_size+media_offset<=max_bytes,'assembled movie exceeds the requested maximum size')
    output=Path(output)
    with output.open('wb') as dest:
        dest.write(front)
        last_counter=2;written=0
        for part in inspected:
            seeks={offset-part.front:stamp for _,stamp,offset in part.entries}
            shift=0;first_block=True
            with part.path.open('rb') as input:
                input.seek(part.front)
                for position in range(0,part.size,128*BLOCK):
                    data=bytearray(input.read(min(128*BLOCK,part.size-position)))
                    require(len(data)%BLOCK==0 and data,'partial media block')
                    for local in range(0,len(data),BLOCK):
                        absolute=position+local
                        block=memoryview(data)[local:local+BLOCK]
                        is_sync=absolute in seeks
                        if not is_sync and block[:2]==b'L2':
                            _,check,stamp,block_size=struct.unpack_from('>HHQH',block)
                            require(block_size!=BLOCK-1 or check!=checksum(stamp),'media sync is absent from seek index')
                        sync=read_sync(block) if is_sync else None
                        if sync:require(sync['descriptors']==part.descriptors,'media stream descriptors changed')
                        flag=sync['flag'] if sync else 0
                        original=block[flag]>>2
                        if first_block:
                            require(sync is not None,'missing first media sync')
                            shift=(last_counter+1-original+64)%64
                            first_block=False
                        else:
                            require(original==((previous_original+int(is_sync))&63),'invalid media block continuity counter')
                        previous_original=original
                        patched=(original+shift)&63
                        block[flag]=(patched<<2)|(block[flag]&3)
                        last_counter=patched
                        if sync:
                            require(sync['stamp']==seeks.pop(absolute),'sync clock mismatch')
                            set_sync(block,sync['stamp']+part.time_offset)
                    dest.write(data);written+=len(data)
                    callback(written/media_offset)
            require(not seeks,'unmatched seek entries')
        dest.flush();os.fsync(dest.fileno())
    require(output.stat().st_size==front_size+media_offset,'file size mismatch')
    return frames
