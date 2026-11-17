#!/usr/bin/env python3
"""Verify cross-built Mach-O architecture, system imports and ad-hoc page hashes."""
import hashlib
import json
from pathlib import Path
import struct
import sys

for argument in sys.argv[1:]:
    path=Path(argument);b=path.read_bytes()
    assert b[:4]==b'\xcf\xfa\xed\xfe', 'Expected little-endian 64-bit Mach-O'
    u32=lambda p:struct.unpack_from('<I',b,p)[0]
    cpu=u32(4);assert cpu in (0x1000007,0x100000c)
    offset=32;signature=None;libraries=[]
    for _ in range(u32(16)):
        cmd,size=u32(offset),u32(offset+4)
        if cmd in (0xc,0x80000018,0x8000001f,0x80000023):
            start=offset+u32(offset+8);name=b[start:b.index(0,start)].decode()
            assert name.startswith(('/usr/lib/','/System/Library/')),name
            libraries.append(name)
        if cmd==0x1d:signature=(u32(offset+8),u32(offset+12))
        offset+=size
    if not signature:
        assert cpu==0x1000007,'ARM64 requires an ad-hoc signature'
        print(json.dumps({'file':path.name,'architecture':'x86_64','systemImports':libraries,'signaturePagesVerified':None,'unsignedIntelBinary':True}))
        continue
    at,length=signature
    big=lambda p:struct.unpack_from('>I',b,p)[0]
    assert big(at)==0xfade0cc0
    directory=None
    for i in range(big(at+8)):
        slot,relative=struct.unpack_from('>II',b,at+12+i*8)
        if slot==0:directory=at+relative
    assert directory is not None
    d=directory;assert big(d)==0xfade0c02
    hashes,slots,limit=big(d+16),big(d+28),big(d+32)
    size,kind,page=b[d+36],b[d+37],1<<b[d+39]
    digest={1:hashlib.sha1,2:hashlib.sha256,3:hashlib.sha256,4:hashlib.sha384}[kind]
    for slot in range(slots):
        expected=b[d+hashes+slot*size:d+hashes+(slot+1)*size]
        assert digest(b[slot*page:min((slot+1)*page,limit)]).digest()[:size]==expected, f'{path.name}: invalid signature page {slot}'
    print(json.dumps({'file':path.name,'architecture':'arm64' if cpu==0x100000c else 'x86_64','systemImports':libraries,'signaturePagesVerified':slots}))
