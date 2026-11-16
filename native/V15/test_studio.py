#!/usr/bin/env python3
"""MobiPEG Studio unit and true integration tests.

Integration uses real Mobiclip/MOFLEX video and ADPCM audio encode/decode.
The tests never modify source files or existing final outputs.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import MobiPEG_Studio_V15 as app

_default_enc=ROOT/'local/bin/ffmpeg'
if not _default_enc.is_file():_default_enc=ROOT/'MobiPEG_V13_work/local/bin/ffmpeg'
ENC=Path(os.environ.get('MOBIPEG_TEST_FFMPEG',str(_default_enc))).resolve()
PROBE=ENC.with_name('ffprobe')
SOURCES=Path(os.environ.get('MOBIPEG_TEST_VIDEO_DIR',str(ROOT/'v15_library_sources'))).resolve()


class StudioUnitTests(unittest.TestCase):
    def test_q_mapping_covers_entire_valid_range(self):
        for q in range(12,60):
            flags=app.q_flags(q)
            qp=int(flags[1]);qyx=int(flags[3])
            self.assertEqual(q,12+6*qyx+qp%6)
            self.assertTrue(12<=qp<=17)

    def test_q_rejects_invalid_numbers(self):
        for q in (-1,0,11,60,999):
            with self.assertRaises(ValueError):app.q_flags(q)

    def test_resolution_invariants(self):
        for w,h in ((0,240),(399,240),(400,241),(-2,240)):
            with self.assertRaises(ValueError):app.scale_filter(w,h)

    def test_stereo_eye_isolation(self):
        for mode in ('full-sbs','half-sbs'):
            flags,layout=app.video_filters(mode,400,224,'24','clean')
            spec=flags[1]
            self.assertEqual(layout,'0')
            self.assertIn('[left]crop=',spec)
            self.assertIn('[right]crop=',spec)
            self.assertEqual(spec.count('hqdn3d='),2)
            self.assertIn('setpts=2*N[l]',spec)
            self.assertIn('setpts=2*N+1[r]',spec)
            self.assertIn('interleave=nb_inputs=2',spec)
            self.assertNotIn('hstack',spec)
        self.assertIn('setsar=2',app.video_filters('half-sbs',400,224,'24','detail')[0][1])

    def test_stereo_coded_rate_exactly_double(self):
        for rate,doubled in [('24','48'),('25','50'),('30','60'),
                             ('24000/1001','48000/1001'),
                             ('30000/1001','60000/1001')]:
            self.assertEqual(app.coded_rate_label(rate,'full-sbs'),doubled)
            self.assertEqual(app.coded_rate_label(rate,'half-sbs'),doubled)
            self.assertEqual(app.coded_rate_label(rate,'2d'),rate)

    def test_2d_filter_pipeline(self):
        args,layout=app.video_filters('2d',400,240,'24','detail')
        self.assertEqual(args[0],'-vf')
        self.assertEqual(layout,'6')
        self.assertIn('scale=400:240',args[1])

    def test_invalid_mode_and_filter(self):
        with self.assertRaises(ValueError):app.video_filters('4d',400,240,'24','detail')
        with self.assertRaises(ValueError):app.video_filters('2d',400,240,'24','bad')

    def test_supported_rates(self):
        self.assertAlmostEqual(app.rate_value('30000/1001'),29.970029970,places=7)
        self.assertAlmostEqual(app.rate_value('24'),24.)
        with self.assertRaises(ValueError):app.rate_value('0')

    def test_preset_profiles_cover_quality_and_size(self):
        self.assertLess(app.PRESETS['best']['q'],app.PRESETS['small']['q'])
        self.assertEqual(app.PRESETS['quality']['q'],30)


@unittest.skipUnless(ENC.is_file() and PROBE.is_file(), 'Built FFmpeg unavailable')
class StudioRealDecoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='studio-v15-tests-')
        cls.work=Path(cls.temp.name)
        cls.short_audio=cls.work/'audio-short.mp4'
        cls.short_stereo=cls.work/'sbs-short.mp4'
        if (SOURCES/'Yip.mp4').exists():
            subprocess.run([str(ENC),'-hide_banner','-nostdin','-v','error','-y',
                     '-i',str(SOURCES/'Yip.mp4'),'-t','1.2','-c','copy',
                     str(cls.short_audio)],check=True,timeout=60)
        if (SOURCES/'MobiPEG_stereo_FULL_SBS_reference.mp4').exists():
            subprocess.run([str(ENC),'-hide_banner','-nostdin','-v','error','-y',
                     '-i',str(SOURCES/'MobiPEG_stereo_FULL_SBS_reference.mp4'),
                     '-t','1.2','-c','copy',str(cls.short_stereo)],check=True,timeout=60)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def opts(self,source,output,**kwargs):
        args=['--input',str(source),'--output',str(output),
              '--ffmpeg',str(ENC),'--preset','quality','--fps','24']
        for key,value in kwargs.items():
            k='--'+key.replace('_','-')
            if isinstance(value,bool):
                if value:args.append(k)
            else:args += [k,str(value)]
        return app.parser().parse_args(args)

    def run_encode(self,source,output,**kwargs):
        logs=[]
        result=app.encode(self.opts(source,output,**kwargs),logs.append)
        self.assertTrue(result.exists())
        self.assertTrue(any('PASS:' in x for x in logs),logs)
        return result

    def test_real_2d_video_and_idempotency(self):
        src=SOURCES/'sonic2.mp4'
        if not src.exists():self.skipTest('Missing test video')
        first=self.run_encode(src,self.work/'test2d.moflex')
        second=self.run_encode(src,self.work/'test2d_again.moflex')
        self.assertEqual(hashlib.sha256(first.read_bytes()).digest(),
                         hashlib.sha256(second.read_bytes()).digest())
        with self.assertRaises(FileExistsError):
            app.encode(self.opts(src,first),lambda _:None)
        self.assertGreater(app.verified_frame_count(PROBE,first),1)

    def test_hard_size_budget_with_real_encodes(self):
        src=SOURCES/'sonic2.mp4'
        if not src.exists():self.skipTest('Missing test video')
        movie=self.run_encode(src,self.work/'sizebudget.moflex',max_size_mb=0.17)
        self.assertLessEqual(movie.stat().st_size,170000)

    def test_actual_adpcm_audio(self):
        if not self.short_audio.exists():self.skipTest('Missing test audio source')
        video=self.run_encode(self.short_audio,self.work/'audio.moflex')
        info=json.loads(app.invoke([PROBE,'-v','error','-show_entries',
                  'stream=codec_type,codec_name','-of','json',video]))
        types=[s['codec_type'] for s in info['streams']]
        self.assertIn('video',types)
        self.assertIn('audio',types)
        app.invoke([ENC,'-hide_banner','-nostdin','-v','error','-xerror',
                    '-i',video,'-map','0:a:0','-f','null','-'])

    def test_true_stereoscopic_sbs(self):
        if not self.short_stereo.exists():self.skipTest('Missing test SBS source')
        for mode in ('full-sbs','half-sbs'):
            movie=self.run_encode(self.short_stereo,
                self.work/f'stereo_{mode}.moflex',mode=mode,resolution='400x224')
            probe=json.loads(app.invoke([PROBE,'-v','error',
                 '-select_streams','v:0','-show_entries',
                 'stream=width,height,nb_read_packets',
                 '-count_packets','-of','json',movie]))
            stream=probe['streams'][0]
            self.assertEqual(stream['width'],400)
            self.assertEqual(stream['height'],224)
            frames=int(stream['nb_read_packets'])
            self.assertEqual(frames%2,0,'Must encode full left/right pairs')
            self.assertGreater(frames,40,'Must encode 48 coded frames per stereo second')
            self.assertEqual(self.first_video_descriptor(movie),(0,24,1,400,224))

    @staticmethod
    def first_video_descriptor(movie):
        # Independent raw binary check. Descriptor type=3 length=13, codec=0,
        # then BE16 display fps numerator/denominator, width/height, layout.
        first=movie.read_bytes()[:256]
        index=first.find(bytes((3,13,0,0)))
        if index<0:raise AssertionError('Missing MOFLEX layout descriptor')
        data=first[index+4:index+15]
        num=int.from_bytes(data[:2],'big')
        den=int.from_bytes(data[2:4],'big')
        w=int.from_bytes(data[4:6],'big')
        h=int.from_bytes(data[6:8],'big')
        return (data[10],num,den,w,h)

    def test_synthetic_eye_order_and_audio(self):
        # Real audiovisual content with visually unambiguous LEFT=red and
        # RIGHT=blue. Both 800x224 full SBS and 400x224 half SBS become
        # 400x224, 48-coded-fps layout-0 output and one second of audio.
        for mode,eye_width in [('full-sbs',400),('half-sbs',200)]:
            src=self.work/f'color_{mode}.mkv'
            color=f'color=c={{}}:s={eye_width}x224:r=24:d=1'
            app.invoke([ENC,'-hide_banner','-nostdin','-v','error','-y',
                '-f','lavfi','-i',color.format('red'),
                '-f','lavfi','-i',color.format('blue'),
                '-f','lavfi','-i','sine=frequency=440:sample_rate=44100:duration=1',
                '-filter_complex','[0:v][1:v]hstack=inputs=2[vid]',
                '-map','[vid]','-map','2:a','-c:v','ffv1','-c:a','pcm_s16le',src])
            movie=self.run_encode(src,self.work/f'colored_{mode}.moflex',
                                  mode=mode,resolution='400x224')
            self.assertEqual(self.first_video_descriptor(movie),(0,24,1,400,224))
            self.assertEqual(app.verified_frame_count(PROBE,movie),48)
            raw=app.invoke([ENC,'-hide_banner','-nostdin','-v','error','-xerror',
                            '-i',movie,'-map','0:v:0','-frames:v','4',
                            '-pix_fmt','rgb24','-f','rawvideo','-'])
            stride=400*224*3
            self.assertEqual(len(raw),4*stride)
            for frame in range(4):
                off=frame*stride+(112*400+200)*3
                r,g,b=raw[off:off+3]
                for px,py in [(16,16),(384,208)]:
                    corner=(frame*400*224+py*400+px)*3
                    cr,cg,cb=raw[corner:corner+3]
                    self.assertGreater(cr if frame%2==0 else cb,200,'Eye must fill the frame after SAR correction')
                if frame%2==0:
                    self.assertGreater(r,b+80,('left eye',mode,frame,r,g,b))
                else:
                    self.assertGreater(b,r+80,('right eye',mode,frame,r,g,b))
            pcm=app.invoke([ENC,'-hide_banner','-nostdin','-v','error','-xerror',
                           '-i',movie,'-map','0:a:0','-ac','2','-ar','44100',
                           '-f','s16le','-'])
            self.assertLess(abs(len(pcm)/4/44100-1.0),0.05,
                            ('Audio must last one displayed stereo second',mode))

    def test_dry_run_and_unchanged_source(self):
        src=SOURCES/'sonic2.mp4'
        if not src.exists():self.skipTest('Missing test video')
        digest=hashlib.sha256(src.read_bytes()).digest()
        out=self.work/'dryrun.moflex'
        app.encode(self.opts(src,out,dry_run=True),lambda _:None)
        self.assertFalse(out.exists())
        self.assertEqual(digest,hashlib.sha256(src.read_bytes()).digest())


if __name__=='__main__':unittest.main()
