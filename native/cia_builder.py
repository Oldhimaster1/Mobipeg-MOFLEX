#!/usr/bin/env python3
"""Build and preview movie CIAs using a locally installed VidInjector9002-CLI."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile

from moflex_join import FAT32_LIMIT
from super_moflex import FFMPEG, copy_bytes, describe, read_at, run_ffmpeg, trailer

LIMIT = 27
HEADER = 0x2020
SIGNATURE = (0x240,0x140,0x80,0x240,0x140,0x80)


def text_field(value, name, maximum):
    if not isinstance(value,str) or not value.strip() or len(value.encode('utf-16-le'))//2>maximum or any(ord(c)<32 for c in value):
        raise ValueError(f'{name} must contain 1–{maximum} UTF-16 units on a single line')
    return value


def unique_id(value):
    if not isinstance(value,str) or not re.fullmatch('[c-eC-E][0-9a-fA-F]{4}',value):
        raise ValueError('Unique title ID must be five hex digits from C0000 through EFFFF')
    return value.upper()


def title_id(value):
    return 0x0004000000000000 | int(unique_id(value),16)<<8


def read_project(path):
    if path.stat().st_size>1024*1024:
        raise ValueError('CIA project exceeds 1 MiB')
    value=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value,dict) or value.get('version')!=1:
        raise ValueError('Unsupported CIA project version')
    movies=value.get('movies')
    if not isinstance(movies,list) or not 1<=len(movies)<=LIMIT:
        raise ValueError(f'A CIA project requires 1–{LIMIT} movies')
    text_field(value.get('title'),'Title',63)
    text_field(value.get('publisher','MobiPEG'),'Publisher',63)
    identifier=unique_id(value.get('id'))
    for used in value.get('reserved_title_ids',[]):
        if isinstance(used,str) and used.upper() in (identifier,f'{title_id(identifier):016X}'):
            raise ValueError('This title ID is listed as already in use')
    for movie in movies:
        if not isinstance(movie,dict) or not isinstance(movie.get('file'),str):
            raise ValueError('Each movie requires a file path')
    return value


def verify_cia(path, expected=None):
    align=lambda value:(value+63)&~63
    size=path.stat().st_size
    if size>FAT32_LIMIT:
        raise ValueError('CIA exceeds the FAT32 file size limit')
    with path.open('rb') as stream:
        header=read_at(stream,0,HEADER)
        header_size,_,_,cert,ticket,tmd,meta,content=struct.unpack_from('<IHHIIIIQ',header)
        tmd_pos=align(header_size)+align(cert)+align(ticket)
        content_pos=tmd_pos+align(tmd)
        if header_size!=HEADER or not all((cert,ticket,tmd,content)) or content_pos+content+meta>size:
            raise ValueError('Invalid CIA section sizes')
        signature=struct.unpack('>I',read_at(stream,tmd_pos,4))[0]-0x10000
        if not 0<=signature<len(SIGNATURE):
            raise ValueError('Invalid CIA title metadata signature format')
        start=SIGNATURE[signature]
        identifier=struct.unpack('>Q',read_at(stream,tmd_pos+start+0x4c,8))[0]
        if expected is not None and identifier!=expected:
            raise ValueError('CIA title ID differs from the requested title ID')
        count=struct.unpack('>H',read_at(stream,tmd_pos+start+0x9e,2))[0]
        records=start+0x9c4
        if not count or records+count*48>tmd:
            raise ValueError('Invalid CIA content table')
        end=content_pos+content
        checked=0
        for index in range(count):
            record=read_at(stream,tmd_pos+records+index*48,48)
            _,number,flags,length,digest=struct.unpack('>IHHQ32s',record)
            if not header[0x20+number//8] & (128>>(number%8)):
                continue
            if flags&1 or not length or content_pos+align(length)>end:
                raise ValueError('Unexpected encrypted or incomplete CIA content')
            stream.seek(content_pos)
            actual=hashlib.sha256()
            remaining=length
            while remaining:
                chunk=stream.read(min(1024*1024,remaining))
                if not chunk:
                    raise ValueError('Truncated CIA content')
                actual.update(chunk)
                remaining-=len(chunk)
            if actual.digest()!=digest:
                raise ValueError('CIA content SHA-256 mismatch')
            content_pos+=align(length)
            checked+=1
        if not checked or content_pos!=end:
            raise ValueError('CIA content map does not match its size')
    return {'title_id':f'{identifier:016X}','bytes':size,'contents_checked':checked}


def call_backend(backend, work, *args):
    result=subprocess.run([str(backend),*map(str,args)],cwd=work,capture_output=True,text=True,errors='replace')
    if result.returncode:
        raise RuntimeError((result.stdout+'\n'+result.stderr).strip()[-2400:] or 'VidInjector failed')


def prepare_project(project, project_path, backend, ffmpeg, work):
    parameters=work/'movie.vi9p'
    movies=project['movies']
    project_paths=[(project_path.parent/m['file']).resolve() for m in movies]
    sources=[(path,*trailer(path)) for path in project_paths]
    if sum(size for _,size,_ in sources)>=FAT32_LIMIT:
        raise ValueError('Movie payloads alone meet or exceed the FAT32 limit. Split the project into separate CIAs.')
    call_backend(backend,work,'-n',parameters)
    for _ in movies[1:]:
        call_backend(backend,work,'-ar',parameters,parameters)
    def set_value(index,value):
        if any(ord(c)<32 for c in str(value)):
            raise ValueError('CIA parameter contains a control character')
        call_backend(backend,work,'-sp',parameters,index,value,parameters)
    title=project['title']
    set_value(0,'1' if len(movies)>1 else '0')
    set_value(4,title)
    set_value(5,text_field(project.get('long_title',title),'Long title',127))
    set_value(6,project.get('publisher','MobiPEG'))
    media=[]
    for index,(movie,(path,size,sections)) in enumerate(zip(movies,sources)):
        label=movie.get('title') or (describe(path)['metadata'].get('title') if sections else None) or path.stem
        if len(movies)>1:
            set_value(12+index,text_field(label,'Movie menu title',127))
        if sections:
            clean=work/f'movie-{index}.moflex'
            with path.open('rb') as inp, clean.open('wb') as dest:
                copy_bytes(inp,dest,size)
            path=clean
        media.append(path)
        set_value(12+len(movies)+index,path)
        if movie.get('banner'):
            set_value(12+len(movies)*2+index,(project_path.parent/movie['banner']).resolve(strict=True))
    for key,index in (('banner',1),('icon',2)):
        if project.get(key):
            set_value(index,(project_path.parent/project[key]).resolve(strict=True))
        elif key=='icon' and project.get('auto_icon',True):
            icon=work/'cover.bmp'
            run_ffmpeg(ffmpeg,['-i',media[0],'-frames:v','1','-vf',
                                'scale=48:48:force_original_aspect_ratio=decrease,pad=48:48:(ow-iw)/2:(oh-ih)/2',
                                '-update','1',icon])
            set_value(index,icon)
    return parameters


def new_project(args):
    destination=args.destination.resolve()
    if not 1<=len(args.movies)<=LIMIT:
        raise ValueError(f'Choose between one and {LIMIT} movies')
    movies=[]
    for path in args.movies:
        path=path.resolve(strict=True)
        trailer(path)
        movies.append({'file':str(path)})
    project={'version':1,'title':text_field(args.title,'Title',63),'id':unique_id(args.id),
             'publisher':text_field(args.publisher,'Publisher',63),'movies':movies}
    with destination.open('x',encoding='utf-8') as stream:
        json.dump(project,stream,indent=2,ensure_ascii=False)
        stream.write('\n')


def process(args):
    location=Path(args.backend).expanduser() if args.backend else shutil.which('VidInjector9002-CLI')
    if not location:
        raise ValueError('Install VidInjector9002-CLI or pass --backend with its path')
    backend=Path(location).resolve(strict=True)
    project=read_project(args.project)
    out=args.output.resolve()
    suffix='.cia' if args.action=='build' else '.png'
    if out.suffix.lower()!=suffix or out.exists() and not args.overwrite:
        raise ValueError(f'Choose an unused {suffix} output or explicitly allow overwrite')
    with tempfile.TemporaryDirectory(prefix='mobipeg-cia-',dir=out.parent) as directory:
        work=Path(directory)
        parameters=prepare_project(project,args.project,backend,args.ffmpeg.resolve(),work)
        candidate=work/('movie'+suffix)
        if args.action=='build':
            call_backend(backend,work,'-bc',parameters,unique_id(project['id']),'video','VDIJ',candidate)
            result=verify_cia(candidate,title_id(project['id']))
        else:
            call_backend(backend,work,'-gp',parameters,2 if args.asset=='icon' else 1,candidate)
            with candidate.open('rb') as image:
                if image.read(8)!=b'\x89PNG\r\n\x1a\n':
                    raise ValueError('VidInjector did not return a PNG preview')
            result={'asset':args.asset}
        if out.exists() and not args.overwrite:
            raise FileExistsError(out)
        candidate.replace(out)
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_subparsers(dest='action',required=True)
    new=modes.add_parser('new',help='Save an editable project in movie order')
    new.add_argument('destination',type=Path)
    new.add_argument('movies',nargs='+',type=Path)
    new.add_argument('--title',required=True)
    new.add_argument('--id',required=True)
    new.add_argument('--publisher',default='MobiPEG')
    for action in ('build','preview'):
        mode=modes.add_parser(action)
        mode.add_argument('project',type=Path)
        mode.add_argument('output',type=Path)
        mode.add_argument('--backend')
        mode.add_argument('--ffmpeg',type=Path,default=FFMPEG)
        mode.add_argument('--overwrite',action='store_true')
        if action=='preview':mode.add_argument('--asset',choices=('icon','banner'),default='icon')
    inspect=modes.add_parser('verify')
    inspect.add_argument('path',type=Path)
    args=parser.parse_args()
    try:
        if args.action=='new':new_project(args)
        else:print(json.dumps(verify_cia(args.path) if args.action=='verify' else process(args),indent=2))
    except (OSError, ValueError, RuntimeError, TypeError, struct.error) as error:
        print(f'Error: {error}',file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
