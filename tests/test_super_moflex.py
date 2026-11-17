"""Real encoder, trailer editor, export, and optional CIA backend integration."""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'native'))
import cia_builder
import moflex_convert
import super_moflex as supermo


@unittest.skipUnless(supermo.FFMPEG.is_file() and shutil.which('ffmpeg'),'requires the native encoder and FFmpeg')
class TrailerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work = Path(cls.temp.name)
        cls.source = cls.work/'source.mkv'
        cls.base = cls.work/'plain.moflex'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=red:s=320x240:r=24:d=2',
                        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2',
                        '-c:v','ffv1','-c:a','pcm_s16le',str(cls.source)],check=True)
        subprocess.run([sys.executable,str(ROOT/'native/MobiPEG_Studio_V15.py'),'-i',str(cls.source),'-o',str(cls.base),
                        '--resolution','320x240','--preset','small'],check=True,capture_output=True)
        cls.subtitle = cls.work/'english.srt'
        cls.subtitle.write_text('1\n00:00:00,000 --> 00:00:01,250\nA subtitle\n',encoding='utf-8')
        meta=cls.work/'meta.json'
        meta.write_text('{"title":"A movie","year":2026}',encoding='utf-8')
        cls.movie = cls.work/'super.moflex'
        subprocess.run([sys.executable,str(ROOT/'native/super_moflex.py'),str(cls.base),'-o',str(cls.movie),
                        '--metadata',str(meta),'--subtitle','ENG',str(cls.subtitle),'--language','ENG',
                        '--alternate-audio','JPN',str(cls.source)],check=True,capture_output=True)

    def test_preserves_payload_and_reopens_with_metadata(self):
        result=supermo.describe(self.movie)
        self.assertEqual(result['metadata']['title'],'A movie')
        self.assertEqual(result['subtitles'],['ENG'])
        self.assertEqual(result['alternate_audio'][0]['language'],'JPN')
        self.assertEqual(result['alternate_audio'][0]['packet_samples'],256)
        self.assertEqual(self.base.read_bytes(),self.movie.read_bytes()[:result['moflex_bytes']])
        updated=self.work/'changed.moflex'
        supermo.rewrite(self.movie,updated,[(b'XTRA',b'future data')],remove=(b'NFO0',))
        sections=supermo.trailer(updated)[1]
        self.assertIn(b'XTRA',[sec.tag for sec in sections])
        self.assertEqual(supermo.describe(updated)['subtitles'],['ENG'])

    def test_rejects_out_of_bounds_trailer(self):
        broken=self.work/'broken.moflex'
        broken.write_bytes(self.base.read_bytes()+struct.pack('<Q8s',0,supermo.MAGIC))
        with self.assertRaisesRegex(ValueError,'offset'):
            supermo.describe(broken)

    def test_export_every_track_to_mp4_and_mkv(self):
        probe=supermo.FFMPEG.with_name('ffprobe'+supermo.FFMPEG.suffix)
        for ext in ('mp4','mkv'):
            out=self.work/f'movie.{ext}'
            moflex_convert.convert(self.movie,out,audio='all')
            raw=subprocess.check_output([str(probe),'-v','error','-show_entries',
                'stream=codec_type:stream_tags=language','-of','json',str(out)])
            tracks=json.loads(raw)['streams']
            self.assertCountEqual([t['codec_type'] for t in tracks],['video','audio','audio','subtitle'])
            self.assertEqual([t['tags']['language'] for t in tracks if t['codec_type']=='audio'],['eng','jpn'])

    def test_native_tone_maps_tagged_hdr(self):
        for transfer in ('smpte2084','arib-std-b67'):
            source=self.work/f'{transfer}.mkv'
            graph=('nullsrc=s=320x240:r=24:d=0.5,format=yuv420p10le,'
                   'geq=lum=64+750*X/W:cb=512:cr=512,'
                   f'setparams=color_primaries=bt2020:color_trc={transfer}:colorspace=bt2020nc')
            subprocess.run([str(supermo.FFMPEG),'-v','error','-f','lavfi','-i',graph,'-c:v','ffv1',str(source)],check=True)
            images=[]
            for mode in ('auto','off'):
                out=self.work/f'{transfer}-{mode}.moflex'
                result=subprocess.run([sys.executable,str(ROOT/'native/MobiPEG_Studio_V15.py'),
                    '-i',str(source),'-o',str(out),'--preset','small','--resolution','320x240','--hdr-mode',mode],
                    check=True,capture_output=True,text=True)
                self.assertEqual('HDR to BT.709 SDR' in result.stdout,mode=='auto')
                image=subprocess.check_output([str(supermo.FFMPEG),'-v','error','-i',str(out),
                    '-frames:v','1','-pix_fmt','gray','-f','rawvideo','pipe:1'])
                self.assertEqual(len(image),320*240)
                self.assertGreater(image[120*320+280],image[120*320+40]+20)
                images.append(image)
            self.assertNotEqual(*images)

    @unittest.skipUnless(os.environ.get('MOBIPEG_CIA_BACKEND'),'set MOBIPEG_CIA_BACKEND for actual CIA builds')
    def test_single_and_two_movie_cia_with_title_and_content_hash(self):
        backend=os.environ['MOBIPEG_CIA_BACKEND']
        for count in (1,2):
            project=self.work/f'project-{count}.json'
            cia=self.work/f'package-{count}.cia'
            subprocess.run([sys.executable,str(ROOT/'native/cia_builder.py'),'new',str(project),
                *map(str,[self.base,self.movie][:count]),'--title','MobiPEG Test','--id','C1572'],
                check=True,capture_output=True)
            subprocess.run([sys.executable,str(ROOT/'native/cia_builder.py'),'build',str(project),str(cia),
                '--backend',backend],check=True,capture_output=True)
            result=cia_builder.verify_cia(cia,cia_builder.title_id('C1572'))
            self.assertEqual(result['contents_checked'],1)
            with self.assertRaisesRegex(ValueError,'title ID'):
                cia_builder.verify_cia(cia,cia_builder.title_id('C1573'))


if __name__=='__main__':
    unittest.main()
