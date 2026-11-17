"""Run with the bundled Windows Python under Wine or on Windows itself."""
from pathlib import Path
import json
import subprocess
import sys
import shutil
import array
import math
import tempfile
bundle=Path(sys.argv[1]).resolve()
app=bundle/'MobiPEGStudio.exe'
ff=bundle/'local/bin/ffmpeg.exe'
probe=ff.with_name('ffprobe.exe')
def run(args):
    try:return subprocess.check_output([str(a) for a in args],stderr=subprocess.STDOUT,timeout=180)
    except subprocess.CalledProcessError as error:
        print(error.output.decode(errors='replace'))
        raise
assert b'--audio-track' in run([app,'--help'])
with tempfile.TemporaryDirectory(prefix='mobipeg-portable-') as temp:
    work=Path(temp);source=work/'source with spaces.mkv'
    if len(sys.argv)>2:
        shutil.copyfile(sys.argv[2],source)
    else:
        run([ff,'-v','error','-f','lavfi','-i','color=red:s=200x224:r=24:d=1',
        '-f','lavfi','-i','color=blue:s=200x224:r=24:d=1',
        '-f','lavfi','-i','sine=frequency=880:sample_rate=48000:duration=1',
        '-filter_complex','[0:v][1:v]hstack[v]','-map','[v]','-map','2:a',
        '-c:v','ffv1','-c:a','pcm_s16le',source])
    for mode,frames in [('2d',24),('full-sbs',48),('half-sbs',48)]:
        out=work/(mode+'.moflex')
        assert b'PASS:' in run([app,'-i',source,'-o',out,'--mode',mode,'--resolution','400x224',*(['--audio-track','1'] if len(sys.argv)>2 else [])])
        info=json.loads(run([probe,'-v','error','-count_packets','-show_entries','stream=codec_name,nb_read_packets','-of','json',out]))
        assert int(next(s for s in info['streams'] if s.get('codec_name')=='mobiclip')['nb_read_packets'])==frames
        assert any(s.get('codec_name')=='adpcm_ima_moflex' for s in info['streams'])
        run([ff,'-v','error','-xerror','-i',out,'-f','null','-'])
        if len(sys.argv)>2:
            audio=array.array('h',run([ff,'-v','error','-i',out,'-map','0:a:0','-ac','1','-ar','44100','-f','s16le','-']))
            values=audio[4410:39690:4]
            def energy(hz):
                return sum(v*math.cos(2*math.pi*hz*i*4/44100) for i,v in enumerate(values))**2+sum(v*math.sin(2*math.pi*hz*i*4/44100) for i,v in enumerate(values))**2
            assert energy(880)>energy(440)*100,'Wrong audio language selected'
        rejected=subprocess.run([str(app),'-i',str(source),'-o',str(out)],capture_output=True,timeout=180)
        assert rejected.returncode!=0
print('Windows portable package: three modes, audio, full decode and output protection passed.')
