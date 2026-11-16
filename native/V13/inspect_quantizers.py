#!/usr/bin/env python3
"""Inspect *actual* emitted per-frame Mobiclip Q and P-frame Q deltas.

This verifies that an adaptive-quantizer plan made it into the compressed
stream.  It parses the Mobiclip slice header after reversing MOFLEX byte-pairs;
the reported values are not estimates inferred from encoder CLI arguments.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess


def run(args):
    z=subprocess.run([str(a) for a in args],capture_output=True,check=True,
                     timeout=240)
    return z.stdout


def parse_packet_header(packet):
    if len(packet)<4:raise ValueError('Truncated Mobiclip packet')
    b=bytearray(packet[:18])
    if len(b)%2:b.append(0)
    for i in range(0,len(b),2):b[i],b[i+1]=b[i+1],b[i]
    bits=''.join(f'{c:08b}' for c in b)
    if bits[0]=='1':
        return 'I',int(bits[3:9],2)
    p=1
    while p<len(bits) and bits[p]=='0':p+=1
    if p>=len(bits):raise ValueError('Truncated Exp-Golomb quantizer delta')
    zeros=p-1
    code=int(bits[p:p+zeros+1],2)-1
    delta=(code+1)//2 if code&1 else -(code//2)
    return 'P',delta


def inspect(movie,ffmpeg,ffprobe):
    pkt=[int(z) for z in run([ffprobe,'-v','error','-select_streams','v:0',
                    '-show_entries','packet=size','-of','csv=p=0',movie]).split()]
    raw=run([ffmpeg,'-hide_banner','-nostdin','-v','error','-i',movie,
             '-map','0:v:0','-c:v','copy','-f','data','pipe:1'])
    if sum(pkt)!=len(raw):raise ValueError('Video packet size mismatch')
    rows=[];position=0;q=None
    for i,n in enumerate(pkt):
        kind,val=parse_packet_header(raw[position:position+n]);position+=n
        if kind=='I':q=val
        elif q is not None:q+=val
        else:raise ValueError('P before first I')
        if not 12<=q<=161:raise ValueError('Invalid quantizer in frame '+str(i))
        rows.append({'frame':i,'type':kind,'quantizer':q,'bytes':n,
                     **({'delta':val} if kind=='P' else {})})
    qc=Counter(z['quantizer'] for z in rows)
    return {'file':str(movie),'coded_frames':len(rows),'payload_bytes':len(raw),
            'i_frames':sum(z['type']=='I' for z in rows),
            'p_frames_with_q_changes':sum(z.get('delta',0)!=0 for z in rows),
            'minimum_q':min(qc),'maximum_q':max(qc),
            'average_q':sum(k*v for k,v in qc.items())/len(rows),
            'q_distribution':dict(sorted(qc.items())), 'frames':rows}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('movie',type=Path)
    p.add_argument('--ffmpeg',type=Path,default='ffmpeg')
    p.add_argument('--ffprobe',type=Path,default='ffprobe')
    p.add_argument('--json',type=Path)
    a=p.parse_args()
    d=inspect(a.movie,a.ffmpeg,a.ffprobe)
    print(json.dumps({k:v for k,v in d.items() if k!='frames'},indent=2))
    if a.json:
        a.json.parent.mkdir(parents=True,exist_ok=True)
        a.json.write_text(json.dumps(d,indent=2))

if __name__=='__main__':main()
