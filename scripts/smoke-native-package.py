#!/usr/bin/env python3
"""Exercise the packaged app, not the source wrapper, with generated media."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    executable = Path(sys.argv[1]).resolve()
    suffix = '.exe' if os.name == 'nt' else ''
    encoder = executable.parent / '_internal/local/bin' / ('ffmpeg' + suffix)
    probe = encoder.with_name('ffprobe' + suffix)
    env = dict(os.environ)
    # Avoid accidentally relying on build-tool DLLs/executables in PATH.
    env['PATH'] = (str(Path(os.environ['SystemRoot']) / 'System32')
                   if os.name == 'nt' else '/usr/bin:/bin')

    def run(args):
        return subprocess.check_output([str(arg) for arg in args], env=env,
                                       stderr=subprocess.STDOUT, timeout=180)

    run([executable, '--help'])
    with tempfile.TemporaryDirectory(prefix='mobipeg-portable-test-') as temp:
        work = Path(temp)
        source = work / 'stereo source.mkv'
        run([encoder, '-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=200x224:r=24:d=1',
             '-f', 'lavfi', '-i', 'color=blue:s=200x224:r=24:d=1',
             '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100:duration=1',
             '-filter_complex', '[0:v][1:v]hstack=inputs=2[v]', '-map', '[v]',
             '-map', '2:a', '-c:v', 'ffv1', '-c:a', 'pcm_s16le', source])
        for mode, expected in [('2d', 24), ('half-sbs', 48)]:
            target = work / f'{mode}.moflex'
            log = run([executable, '--input', source, '--output', target,
                       '--mode', mode, '--resolution', '400x224', '--fps', '24'])
            assert b'PASS:' in log, log.decode(errors='replace')
            info = json.loads(run([probe, '-v', 'error', '-count_packets',
                                   '-show_entries', 'stream=codec_name,nb_read_packets',
                                   '-of', 'json', target]))
            video = next(s for s in info['streams'] if s.get('codec_name') == 'mobiclip')
            assert int(video['nb_read_packets']) == expected, info
            assert any(s.get('codec_name') == 'adpcm_ima_moflex' for s in info['streams']), info
            run([encoder, '-v', 'error', '-xerror', '-i', target, '-f', 'null', '-'])
            # The portable CLI must preserve an existing output by default.
            rejected = subprocess.run([str(executable), '--input', str(source),
                                       '--output', str(target)], env=env,
                                      capture_output=True, timeout=180)
            assert rejected.returncode != 0, 'Existing output was not protected'
    print('Portable package passed: bundled encoder, 2D/stereo, audio, decode, output protection.')


if __name__ == '__main__':
    main()
