#!/usr/bin/env python3
"""Conservative, read-only structural preflight for MobiClip/MOFLEX videos.

This does not decode every frame or certify playback on a physical Nintendo 3DS.
Use the project's patched FFmpeg decoder and a real console for final testing.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from moflex_join import BLOCK, FAT32_LIMIT, inspect
from moflex_convert import video_descriptor
from super_moflex import describe, trailer

LONG_MOVIE_US = 0xffffffff  # Legacy 32-bit microsecond duration field.


def evaluate(path: Path) -> dict:
    path = Path(path)
    issues = []
    def note(severity: str, code: str, message: str):
        issues.append({'severity': severity, 'code': code, 'message': message})

    report = {
        'file': path.name, 'bytes': None, 'status': 'fail', 'checks': issues,
        'video': None, 'seek_index': None, 'extras': None,
        'scope': 'Structural preflight only; does not decode the movie or certify Nintendo 3DS playback.'
    }
    try:
        size = path.stat().st_size
        report['bytes'] = size
    except OSError as error:
        note('error', 'FILE_UNREADABLE', f'Cannot read this file: {error.strerror or error}')
        return report
    if size > FAT32_LIMIT:
        note('error', 'FAT32_LIMIT', 'File exceeds 4,294,967,295 bytes and cannot be stored as one FAT32 file.')
    if size < BLOCK * 2:
        note('error', 'FILE_TOO_SMALL', 'Too short to contain a MOFLEX seek index and a media block.')
        return report

    try:
        media_size, sections = trailer(path)
    except (ValueError, OSError) as error:
        note('error', 'TRAILER_INVALID', str(error))
        return report
    if media_size % BLOCK:
        note('error', 'BLOCK_ALIGNMENT', 'Primary MOFLEX portion is not aligned to 4,096-byte blocks.')
        return report
    if media_size < BLOCK * 2:
        note('error', 'MEDIA_TOO_SMALL', 'The primary movie has no complete media block.')
        return report
    report['extras'] = {'trailer_bytes': size-media_size, 'sections': len(sections),
                        'has_super_moflex': bool(sections)}
    try:
        part = inspect(path, media_bytes=media_size)
        info = video_descriptor(path)
    except (ValueError, OSError, EOFError, OverflowError) as error:
        note('error', 'MOFLEX_STRUCTURE', str(error))
        return report

    coded_fps = info['coded_fps']
    duration = part.frames / coded_fps
    report['video'] = {
        **info, 'frames': part.frames, 'estimated_seconds': round(duration, 6),
        'eye_width': info['width']//2 if info['family']=='side-by-side' else info['width'],
        'eye_height': info['height']//2 if info['family']=='top-bottom' else info['height'],
    }
    report['seek_index'] = {'entries': len(part.entries), 'front_bytes': part.front,
                            'media_bytes': media_size, 'first_index_frame': part.entries[0][0]}
    if info['family']=='side-by-side' and info['width']%2 or info['family']=='top-bottom' and info['height']%2:
        note('error', 'STEREO_GEOMETRY', 'Packed stereo dimensions cannot be divided evenly between eyes.')
    if report['video']['eye_width'] > 400 or report['video']['eye_height'] > 240:
        note('warning', 'EXPERIMENTAL_RESOLUTION',
             'Per-eye resolution exceeds the 400×240 top-screen size; physical console compatibility is unverified.')
    if info['display_fps'] > 30.01:
        note('warning', 'EXPERIMENTAL_FRAME_RATE',
             'Displayed frame rate exceeds 30 fps; performance on real 3DS hardware may be inadequate.')
    if info['eyes']==2 and info['family'] != 'interleaved':
        note('warning', 'STEREO_LAYOUT',
             'Packed stereoscopic layout needs confirmation in the intended 3DS player.')
    if duration * 1_000_000 > LONG_MOVIE_US:
        note('warning', 'LONG_MOVIE_SEEKING',
             'The movie exceeds ~71m35s; the legacy 32-bit duration field saturates. '
             'Seeking past this point is not confirmed on a real 3DS.')
    # The head index checks ordering and the first media sync. Intermediate
    # bitstream corruption and undecodable video need a full decoder pass.
    if part.entries[-1][0] >= part.frames:
        note('error', 'INDEX_FRAME_RANGE', 'The seek index points beyond the declared frame count.')
    if part.entries[0][0] != 0:
        note('warning', 'INDEX_START', 'The first seek entry does not start at coded frame zero.')
    if sections:
        try:
            extra = describe(path)
        except (ValueError, OSError, UnicodeError) as error:
            note('error', 'SUPER_MOFLEX_INVALID', str(error))
        else:
            report['extras'].update({
                'subtitles': len(extra['subtitles']),
                'alternate_audio': len(extra['alternate_audio']),
                'poster': extra['poster'] is not None,
                'primary_language': extra['primary_language'],
            })
            if extra['subtitles'] or extra['alternate_audio']:
                note('info', 'EXTRA_PLAYER_REQUIRED',
                     'Clownsec SUPER MOFLEX subtitles/alternate audio need a compatible player; '
                     'the original Nintendo player ignores appended extras.')
            if len(extra['subtitles'])>16:
                note('error', 'TOO_MANY_SUBTITLES', 'More than 16 embedded subtitle sections.')

    report['status'] = ('fail' if any(x['severity']=='error' for x in issues) else
                        'warning' if any(x['severity']=='warning' for x in issues) else 'pass')
    return report


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file',type=Path,help='MOFLEX file to inspect without modifying it')
    parser.add_argument('--json',action='store_true',help='Emit structured JSON diagnostics')
    args=parser.parse_args(argv)
    result=evaluate(args.file)
    if args.json:
        print(json.dumps(result,indent=2,ensure_ascii=False))
    else:
        print(f"MobiPEG MOFLEX preflight: {result['file']} — {result['status'].upper()}")
        video=result['video']
        if video:
            print(f"Video: {video['eye_width']}×{video['eye_height']} per eye, "
                  f"{video['display_fps']:.3f} displayed fps, {video['family']} "
                  f"(layout {video['layout']})")
            print(f"Frames: {video['frames']:,}; duration: {video['estimated_seconds']:.2f} s; "
                  f"seek entries: {result['seek_index']['entries']:,}")
        for issue in result['checks']:
            print(f"[{issue['severity'].upper()}] {issue['code']}: {issue['message']}")
        print(result['scope'])
    return 1 if result['status']=='fail' else 0


if __name__=='__main__':
    raise SystemExit(main())
