"""Real indexed-seek/forward equivalence, including fragmented GOPs and audio."""
import hashlib,json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from fractions import Fraction
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'native'))
from moflex_join import join
ROOT=Path(__file__).resolve().parents[1]
FF=ROOT/'native/local/bin/ffmpeg'
class IndexedSeek(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.work=tempfile.TemporaryDirectory(prefix='mobipeg-index-test-');cls.folder=Path(cls.work.name)
  cls.source=cls.folder/'source.mkv'
  subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=400x240:r=24:d=8','-f','lavfi','-i','sine=f=887:r=48000:d=8','-c:v','ffv1','-c:a','pcm_s16le',str(cls.source)],check=True)
  cls.movies={}
  for mode in ['2d','full-sbs','half-sbs']:
   for codec in ['adpcm','fastaudio']:
    output=cls.folder/(mode+'-'+codec+'.moflex')
    subprocess.run([sys.executable,'native/MobiPEG_Studio_V15.py','-i',str(cls.source),'-o',str(output),'--preset','small','--q','38','--resolution','400x240','--mode',mode,'--audio-codec',codec],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    cls.movies[mode,codec]=output
 @classmethod
 def tearDownClass(cls):cls.work.cleanup()
 def decode(self,path,start,kind,forward=False):
  options=['-map','0:v:0','-frames:v','6','-pix_fmt','yuv420p','-f','rawvideo'] if kind=='video' else ['-t','0.25','-map','0:a:0','-ac','2','-ar','48000','-f','s16le']
  env={**os.environ};env.pop('MOBIPEG_FORWARD_SEEK',None)
  if forward:env['MOBIPEG_FORWARD_SEEK']='1'
  result=subprocess.run([str(FF),'-v','debug','-xerror','-ss',str(start),'-i',str(path),*options,'pipe:1'],env=env,capture_output=True,check=True)
  return result.stdout,result.stderr
 def test_forward_equivalence_audio_video_and_stereo(self):
  for (mode,codec),path in self.movies.items():
   for start in [0.125,1.3,2.0,3.125,5.75,7.5]:
    for kind in ['video','audio']:
     with self.subTest(mode=mode,codec=codec,start=start,kind=kind):
      expected,_=self.decode(path,start,kind,True);actual,_=self.decode(path,start,kind)
      self.assertEqual(actual,expected)
 def test_joined_long_timestamps_and_pair_order(self):
  for (mode,codec),path in self.movies.items():
   joined=self.folder/(mode+'-'+codec+'-joined.moflex')
   frames=192*(2 if mode!='2d' else 1)
   join([(path,frames)]*12,Fraction(48 if mode!='2d' else 24),joined)
   for kind in ['video','audio']:
    actual,log=self.decode(joined,83.125,kind)
    expected,_=self.decode(path,3.125,kind,True)
    self.assertEqual(actual,expected,(mode,codec,kind))
    self.assertIn(b'MOFLEX indexed seek:',log)
 def test_unindexed_file_keeps_safe_forward_compatibility(self):
  from moflex_join import inspect
  original=self.movies['2d','adpcm'];info=inspect(original,192)
  bare=self.folder/'unindexed.moflex';bare.write_bytes(original.read_bytes()[info.front:])
  for kind in ['video','audio']:
   actual,log=self.decode(bare,3.125,kind);expected,_=self.decode(original,3.125,kind,True)
   self.assertEqual(actual,expected);self.assertNotIn(b'MOFLEX indexed seek:',log)
 def test_legacy_interleaved_layout_zero_keeps_eye_order(self):
  from moflex_join import inspect
  original=self.movies['half-sbs','adpcm'];info=inspect(original,384)
  descriptors=bytearray(info.descriptors);descriptors[14]=0
  legacy=self.folder/'layout-zero.moflex';legacy.write_bytes(original.read_bytes().replace(info.descriptors,bytes(descriptors)))
  for kind in ['video','audio']:
   actual,_=self.decode(legacy,5.125,kind);expected,_=self.decode(legacy,5.125,kind,True)
   self.assertEqual(actual,expected)
 def test_fractional_frame_rate_preserves_audio_samples(self):
  path=self.folder/'fractional.moflex'
  subprocess.run([sys.executable,'native/MobiPEG_Studio_V15.py','-i',str(self.source),'-o',str(path),'--preset','small','--q','38','--fps','24000/1001'],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
  for start in [1.3,3.125,7.5]:
   for kind in ['video','audio']:
    actual,_=self.decode(path,start,kind);expected,_=self.decode(path,start,kind,True);self.assertEqual(actual,expected)
 def test_fractional_rates_keep_exact_pixels_and_samples(self):
  for mode in ['2d','half-sbs']:
   for fps in ['24000/1001','30000/1001']:
    output=self.folder/(mode+'-'+fps.replace('/','-')+'.moflex')
    subprocess.run([sys.executable,'native/MobiPEG_Studio_V15.py','-i',str(self.source),'-o',str(output),'--preset','small','--q','38','--mode',mode,'--fps',fps],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    for start in [1.125,3.5,6.125]:
     for kind in ['video','audio']:
      actual,_=self.decode(output,start,kind);expected,_=self.decode(output,start,kind,True)
      self.assertEqual(actual,expected,(mode,fps,start,kind))
 def test_corrupt_indexed_sync_rejected(self):
  # Keep the front index intact but damage the target sync checksum.
  from moflex_join import inspect
  path=self.movies['2d','adpcm'];info=inspect(path,192)
  damaged=bytearray(path.read_bytes());offset=info.entries[-2][2];damaged[offset+2]^=1
  corrupt=self.folder/'corrupt.moflex';corrupt.write_bytes(damaged)
  result=subprocess.run([str(FF),'-v','error','-xerror','-ss',str(info.entries[-2][1]/1e6+0.1),'-i',str(corrupt),'-t','0.1','-f','null','-'],capture_output=True)
  self.assertNotEqual(result.returncode,0)
if __name__=='__main__':unittest.main()
