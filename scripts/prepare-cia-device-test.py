#!/usr/bin/env python3
"""Generate two short, synthetic ADPCM movies for local CIA hardware testing."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    target = args.directory.resolve()
    target.mkdir(parents=True, exist_ok=False)
    movies = []
    for index, (color, frequency) in enumerate([('red', 440), ('blue', 880)], 1):
        source = target / f'episode-{index}.mkv'
        output = target / f'episode-{index}.moflex'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
            f"color=c={color}:s=320x240:r=24:d=6,drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='lt(mod(t,1),0.08)'",
            '-f', 'lavfi', '-i',
            f'aevalsrc=0.25*sin(2*PI*{frequency}*t)*lt(mod(t\\,1)\\,0.08):s=48000:d=6',
            '-c:v', 'ffv1', '-c:a', 'pcm_s16le', str(source)], check=True)
        subprocess.run([sys.executable, str(ROOT / 'native/MobiPEG_Studio_V15.py'),
            '-i', str(source), '-o', str(output), '--preset', 'small',
            '--resolution', '320x240'], check=True)
        movies.append({'file': output.name, 'title': f'{index}: {color} / {frequency} Hz pulses'})
        source.unlink()
    project = {'version': 1, 'title': 'MobiPEG Device Test', 'publisher': 'MobiPEG',
               'id': 'C7E57', 'movies': movies}
    (target / 'device-project.json').write_text(json.dumps(project, indent=2) + '\n')
    print(f'Device movies and native-compatible project saved in {target}')
    print('Use your own compatible local collection-player template in the browser builder.')

if __name__ == '__main__':
    main()
