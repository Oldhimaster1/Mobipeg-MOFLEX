#!/usr/bin/env python3
"""Confirm exact agreement between encoder frame buffers and software decoder."""
import argparse
import hashlib
from pathlib import Path
import tempfile

import v13_adaptive_lab as lab


def check(idx,mode):
    row, env, extra, raw, _=lab.params_for(idx,lab.load_reports())
    n=row['coded_frames']
    qplan=lab.HERE/f'v13_experiments/quant_{idx:03d}_{mode}.txt'
    assert qplan.is_file()
    with tempfile.TemporaryDirectory(prefix='mobi_v13_reconstruct_') as dir:
        temp=Path(dir)
        dump=temp/'encoder_fdec.yuv'
        movie=temp/'trial.moflex'
        env['MOBI_V13_Q_PLAN']=str(qplan)
        env['MOBI_FDECDUMP']=str(dump)
        args=[lab.ENC,'-hide_banner','-nostdin','-v','error','-y',
            '-f','rawvideo','-pix_fmt','yuv420p','-video_size','400x224',
            '-framerate','48','-i',raw,'-an',
            '-c:v','mobiclip','-mobiclip','1','-qp',str(row['qp']),
            '-mobi_qyx',str(row['qyx']),'-preset','medium',
            '-me_method','hex','-g',str(n)] + extra + [
            '-mo_layout','0','-f','moflex',movie]
        lab.run(args,env=env)
        decoded=lab.run([lab.ENC,'-hide_banner','-nostdin','-v','error',
             '-xerror','-i',movie,'-map','0:v:0','-pix_fmt','yuv420p',
             '-f','rawvideo','pipe:1'])
        reconstructed=dump.read_bytes()
        assert len(decoded)==len(reconstructed)==n*lab.FRAME_BYTES
        assert decoded==reconstructed, 'Encoder-decoder reconstruction drift!'
        h=hashlib.sha256(decoded).hexdigest()
        print(f'PASS GOP {idx:03d} {mode} frames={n} exact reconstruction SHA-256={h}')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',default='motion')
    p.add_argument('indices',nargs='*',type=int,default=[8,25,46])
    a=p.parse_args()
    for idx in a.indices:check(idx,a.mode)

if __name__=='__main__':main()
