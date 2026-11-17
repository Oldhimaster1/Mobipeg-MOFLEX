#!/usr/bin/env python3
"""Inspect and edit the Clownsec CSXTRA01 trailer without remuxing the movie."""
import argparse
from array import array
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import wave

from moflex_join import FAT32_LIMIT

MAGIC = b'CSXTRA01'
MAX_TEXT = 1 << 20
MAX_SECTIONS = 256
FFMPEG = Path(__file__).resolve().parent / 'local/bin' / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')


@dataclass(frozen=True)
class Section:
    tag: bytes
    offset: int
    length: int


def read_at(stream, offset, length):
    stream.seek(offset)
    data = stream.read(length)
    if len(data) != length:
        raise ValueError('Truncated MOFLEX file')
    return data


def trailer(path):
    with Path(path).open('rb') as stream:
        size = stream.seek(0, os.SEEK_END)
        if size < 16 or read_at(stream, 0, 2) != b'L2':
            raise ValueError('Expected a MOFLEX file')
        payload, magic = struct.unpack('<Q8s', read_at(stream, size-16, 16))
        if magic != MAGIC:
            return size, []
        end = size-16
        if not 14 <= payload < end:
            raise ValueError('Invalid CSXTRA01 payload offset')
        sections = []
        offset = payload
        while offset < end:
            if end-offset < 8 or len(sections) >= MAX_SECTIONS:
                raise ValueError('Invalid CSXTRA01 section table')
            tag, length = struct.unpack('<4sI', read_at(stream, offset, 8))
            offset += 8
            if length == 0 or length > end-offset:
                raise ValueError('CSXTRA01 section runs outside the trailer')
            sections.append(Section(tag, offset, length))
            offset += length
        return payload, sections


def language_bytes(value):
    if not re.fullmatch('[A-Za-z0-9]{1,3}', value):
        raise ValueError('Language labels must contain one to three ASCII letters or digits')
    return value.upper().encode('ascii').ljust(4, b'\0')


def language_text(raw):
    return raw.split(b'\0', 1)[0].decode('ascii', errors='replace')


def parse_metadata(raw):
    fields = {}
    for line in raw.decode('utf-8-sig', errors='replace').splitlines():
        key, separator, value = line.partition('=')
        if separator and key.strip():
            fields[key.strip()] = value
    return fields


def audio_info(stream, section):
    header = 12 if section.tag == b'AUD1' else 8
    if section.length <= header:
        raise ValueError('Invalid alternate audio header')
    raw = read_at(stream, section.offset, header)
    rate, channels, samples = struct.unpack_from('<IHH', raw)
    if not 8000 <= rate <= 192000 or channels not in (1, 2) or not 256 <= samples <= 8192 or samples%256:
        raise ValueError('Unsupported alternate audio packet format')
    packet = channels*(4+samples//2)
    if (section.length-header)%packet:
        raise ValueError('Incomplete alternate audio packet')
    return {'rate': rate, 'channels': channels, 'packet_samples': samples,
            'packet_bytes': packet, 'language': language_text(raw[8:]) or 'ALT',
            'samples': (section.length-header)//packet*samples}


IMA_STEPS = (7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,80,88,97,
             107,118,130,143,157,173,190,209,230,253,279,307,337,371,408,449,494,544,598,658,724,796,876,
             963,1060,1166,1282,1411,1552,1707,1878,2066,2272,2499,2749,3024,3327,3660,4026,4428,4871,
             5358,5894,6484,7132,7845,8630,9493,10442,11487,12635,13899,15289,16818,18500,20350,22385,
             24623,27086,29794,32767)
IMA_INDEX = (-1,-1,-1,-1,2,4,6,8)


def extract_audio(stream, section, output, seconds=None):
    info = audio_info(stream, section)
    channels, samples, size = (info[key] for key in ('channels','packet_samples','packet_bytes'))
    remaining = info['samples']
    if seconds is not None:
        remaining = min(remaining, round(seconds*info['rate']))
    stream.seek(section.offset+(12 if section.tag==b'AUD1' else 8))
    with wave.open(str(output),'wb') as wav:
        wav.setparams((channels,2,info['rate'],remaining,'NONE','not compressed'))
        while remaining:
            packet = stream.read(size)
            if len(packet)!=size:
                raise ValueError('Truncated alternate audio packet')
            length = min(samples,remaining)
            pcm = array('h',[0])*(length*channels)
            for channel in range(channels):
                index,predictor = struct.unpack_from('<hh',packet,channel*4)
                if not 0<=index<=88:
                    raise ValueError('Invalid alternate audio predictor state')
                for sample in range(length):
                    chunk = sample//256*channels+channel
                    byte = packet[4*channels+chunk*128+sample%256//2]
                    code = byte>>4 if sample%2 else byte&15
                    diff = ((2*(code&7)+1)*IMA_STEPS[index])>>3
                    predictor = min(32767,max(-32768,predictor+(-diff if code&8 else diff)))
                    index = min(88,max(0,index+IMA_INDEX[code&7]))
                    pcm[sample*channels+channel] = predictor
            if sys.byteorder!='little':
                pcm.byteswap()
            wav.writeframesraw(pcm)
            remaining -= length
    return info['language']


def describe(path):
    base, sections = trailer(path)
    result = {'moflex_bytes': base, 'metadata': {}, 'subtitles': [], 'alternate_audio': [],
              'primary_language': None, 'poster': None, 'sections': []}
    with Path(path).open('rb') as stream:
        for section in sections:
            tag = section.tag
            result['sections'].append({'tag': tag.decode('ascii', errors='replace'), 'bytes': section.length})
            if tag == b'NFO0' and section.length <= MAX_TEXT:
                result['metadata'].update(parse_metadata(read_at(stream, section.offset, section.length)))
            elif tag == b'LNG0' and section.length == 4:
                result['primary_language'] = language_text(read_at(stream, section.offset, 4))
            elif tag == b'ART5' and section.length >= 4:
                width, height = struct.unpack('<HH', read_at(stream, section.offset, 4))
                if width and height and section.length == 4+width*height*2:
                    result['poster'] = {'width': width, 'height': height}
            elif tag in (b'SUB0', b'SUB1') and section.length > (4 if tag == b'SUB1' else 0):
                lang = language_text(read_at(stream, section.offset, 4)) if tag == b'SUB1' else 'SUB'
                result['subtitles'].append(lang)
            elif tag in (b'AUD0', b'AUD1'):
                result['alternate_audio'].append(audio_info(stream, section))
    return result


def copy_bytes(source, destination, count):
    while count:
        chunk = source.read(min(count, 1024*1024))
        if not chunk:
            raise ValueError('Source changed while copying MOFLEX')
        destination.write(chunk)
        count -= len(chunk)


def rewrite(source, output, additions, remove=(), overwrite=False):
    """Add (tag, bytes or Path) sections and keep everything else byte-for-byte."""
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve() or output.exists() and not overwrite:
        raise ValueError('Choose a different, unused output path or explicitly allow overwrite')
    base, sections = trailer(source)
    retained = [section for section in sections if section.tag not in remove]
    prepared = [(tag, body, body.stat().st_size if isinstance(body, Path) else len(body))
                for tag, body in additions]
    total_sections = len(retained)+len(prepared)
    size = base + (16 if total_sections else 0)
    size += sum(8+s.length for s in retained)+sum(8+n for _, _, n in prepared)
    if size > FAT32_LIMIT:
        raise ValueError('Output exceeds the FAT32 limit of 4,294,967,295 bytes')
    if (total_sections > MAX_SECTIONS or sum(s.tag in (b'SUB0', b'SUB1') for s in retained)
            + sum(tag in (b'SUB0', b'SUB1') for tag, _, _ in prepared) > 16):
        raise ValueError('The trailer supports at most 16 subtitle tracks and 256 sections')
    with tempfile.TemporaryDirectory(prefix='mobipeg-trailer-', dir=output.parent) as directory:
        temp = Path(directory)/'output.moflex'
        with source.open('rb') as src, temp.open('wb') as dst:
            copy_bytes(src, dst, base)
            for section in retained:
                src.seek(section.offset-8)
                copy_bytes(src, dst, section.length+8)
            for tag, body, length in prepared:
                if len(tag) != 4 or not 0 < length <= 0xffffffff:
                    raise ValueError('Invalid CSXTRA01 section size or tag')
                dst.write(struct.pack('<4sI', tag, length))
                if isinstance(body, Path):
                    with body.open('rb') as payload:
                        copy_bytes(payload, dst, length)
                else:
                    dst.write(body)
            if total_sections:
                dst.write(struct.pack('<Q8s', base, MAGIC))
            if dst.tell() != size:
                raise ValueError('Output length changed unexpectedly')
        result = describe(temp)
        if output.exists() and not overwrite:
            raise FileExistsError(output)
        temp.replace(output)
        return result


def run_ffmpeg(encoder, args):
    result = subprocess.run([str(encoder), '-hide_banner', '-nostdin', '-v', 'error', *map(str, args)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace').strip()[-2000:])
    return result.stdout


def alternate_section(encoder, source, output, language):
    # The bundled encoder outputs one 256-sample packet with the same
    # predictor, step index and nibble layout used by CSXTRA01.
    raw = output.with_suffix('.adpcm')
    run_ffmpeg(encoder, ['-i', source, '-map', '0:a:0', '-ac', '2', '-ar', '48000',
                        '-af', 'asetnsamples=n=256:p=1', '-c:a', 'adpcm_ima_moflex', '-f', 'data', raw])
    if not raw.stat().st_size or raw.stat().st_size%264:
        raise ValueError('Alternate audio produced invalid MOFLEX ADPCM packets')
    with raw.open('rb') as src, output.open('wb') as dst:
        dst.write(struct.pack('<IHH4s', 48000, 2, 256, language_bytes(language)))
        copy_bytes(src, dst, raw.stat().st_size)


def metadata_bytes(fields):
    if not isinstance(fields, dict):
        raise ValueError('Metadata must be a JSON object')
    lines = []
    for key, value in fields.items():
        if not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}', key) or not isinstance(value, (str, int, float, bool)):
            raise ValueError(f'Invalid metadata field {key!r}')
        value = str(value)
        if any(ord(character)<32 for character in value):
            raise ValueError(f'Metadata field {key!r} must fit on one line')
        lines.append(f'{key}={value}\n')
    data = ''.join(lines).encode()
    if not data or len(data) > 65536:
        raise ValueError('Metadata must contain between 1 and 65,536 bytes')
    return data


def edit(args):
    if args.output.suffix.lower() != '.moflex':
        raise ValueError('Use a .moflex output filename')
    remove = {tag.encode('ascii') for tag in args.remove}
    additions = []
    with tempfile.TemporaryDirectory(prefix='mobipeg-tracks-', dir=args.output.parent) as directory:
        if args.metadata:
            with args.metadata.open(encoding='utf-8-sig') as handle:
                fields = json.load(handle)
            additions.append((b'NFO0', metadata_bytes(fields)))
            remove.add(b'NFO0')
        if args.language:
            additions.append((b'LNG0', language_bytes(args.language)))
            remove.add(b'LNG0')
        for language, name in args.subtitle:
            path = Path(name)
            if path.suffix.lower() not in ('.srt', '.ass', '.ssa') or not 0 < path.stat().st_size <= MAX_TEXT:
                raise ValueError('Use a nonempty SRT, ASS or SSA file under 1 MiB')
            subtitle = path.read_text(encoding='utf-8-sig').encode()
            additions.append((b'SUB1', language_bytes(language)+subtitle))
        if args.poster:
            art = run_ffmpeg(args.ffmpeg, ['-i', args.poster, '-vf', 'scale=132:188', '-frames:v', '1',
                                         '-pix_fmt', 'rgb565le', '-f', 'rawvideo', 'pipe:1'])
            if len(art) != 132*188*2:
                raise ValueError('Could not create a 132 × 188 poster')
            additions.append((b'ART5', struct.pack('<HH', 132, 188)+art))
            remove.add(b'ART5')
        if args.alternate_audio:
            language, source = args.alternate_audio
            encoded = Path(directory)/'audio.section'
            alternate_section(args.ffmpeg, source, encoded, language)
            additions.append((b'AUD1', encoded))
            remove.update((b'AUD0', b'AUD1'))
        return rewrite(args.input, args.output, additions, remove, args.overwrite)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('-o', '--output', type=Path, help='Write edits to a separate .moflex')
    parser.add_argument('--metadata', type=Path, help='JSON object, e.g. title, year, genres, desc, runtime')
    parser.add_argument('--language', help='In-band audio language code')
    parser.add_argument('--subtitle', nargs=2, action='append', default=[], metavar=('LANG', 'FILE'))
    parser.add_argument('--alternate-audio', nargs=2, metavar=('LANG', 'FILE'))
    parser.add_argument('--poster', type=Path)
    parser.add_argument('--remove', action='append', default=[], choices=('SUB0','SUB1','AUD0','AUD1','LNG0','NFO0','ART5'))
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--ffmpeg', type=Path, default=FFMPEG)
    args = parser.parse_args()
    try:
        if not args.output and any((args.metadata,args.language,args.subtitle,args.alternate_audio,args.poster,args.remove)):
            raise ValueError('Specify --output to write changes')
        print(json.dumps(edit(args) if args.output else describe(args.input), indent=2, ensure_ascii=False))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
