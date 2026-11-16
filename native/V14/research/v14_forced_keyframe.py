#!/usr/bin/env python3
"""Test the one Avatar scene cut missed by V13's automatic I-frame detection."""
import json
from pathlib import Path
import time

import v13_adaptive_lab as lab
import v14_cut_lab as cut

HERE=Path(__file__).resolve().parent
OUT=HERE/'v14_cut_lab'
INDEX=43
CUT=4136


def main():
    selected,groups=cut.reports()
    base=selected[INDEX]
    b,env,extras,raw,source=lab.params_for(INDEX,lab.load_reports())
    n=base['coded_frames'];orig=source.read_bytes()
    paths={'seed':HERE/f'v13_experiments/quant_{INDEX:03d}_{base["variant"]}.txt',
           'cut6_2':OUT/f'q_{INDEX:03d}_cut6_2.txt',
           'balanced6_2':OUT/f'q_{INDEX:03d}_balanced6_2.txt'}
    flags={'single_left':[f'{(CUT-INDEX*96)/48:.9f}'],
           'both_eyes':[f'{(CUT-INDEX*96)/48:.9f}',f'{(CUT-INDEX*96+1)/48:.9f}']}
    all=[]
    for plan,pfile in paths.items():
        if not pfile.exists():continue
        for name,instants in flags.items():
            env['MOBI_V13_Q_PLAN']=str(pfile)
            file=OUT/f'gop_043_{plan}_{name}.moflex'
            args=[lab.ENC,'-hide_banner','-nostdin','-v','error','-y',
                '-f','rawvideo','-pix_fmt','yuv420p','-video_size','400x224',
                '-framerate','48','-i',raw,'-an','-c:v','mobiclip','-mobiclip','1',
                '-qp',str(b['qp']),'-mobi_qyx',str(b['qyx']),'-preset','medium',
                '-me_method','hex','-g',str(n)] + extras + [
                '-force_key_frames',','.join(instants),
                '-mo_layout','0','-f','moflex',file]
            start=time.monotonic()
            lab.run(args,env=env)
            dec=lab.run([lab.ENC,'-hide_banner','-nostdin','-v','error',
                '-xerror','-i',file,'-map','0:v:0','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'])
            if len(dec)!=n*lab.FRAME_BYTES:raise ValueError('Decoded frame mismatch')
            pk=[int(v) for v in lab.run([lab.PROBE,'-v','error',
                '-select_streams','v:0','-show_entries','packet=size','-of','csv=p=0',file]).split()]
            from MobiPEG_V13_work.V13.inspect_quantizers import inspect
            quant=inspect(file,lab.ENC,lab.PROBE)
            row={'index':INDEX,'variant':f'forced_{plan}_{name}',
                 'file':str(file),'coded_frames':n,'video_bytes':sum(pk),
                 'i_frames':quant['i_frames'],
                 'cut_frame_is_i':quant['frames'][CUT-INDEX*96]['type']=='I',
                 'peak_1s_bytes':max((sum(pk[i:i+48]) for i in range(0,n,48)),default=0),
                 'seconds':round(time.monotonic()-start,2),
                 **lab.metrics(orig,dec,n=n),
                 **cut.postcut_metrics(orig,dec,INDEX,[CUT],n),
                 'boundary_excess':lab.blockiness(orig,dec,n)}
            all.append(row)
            print('PASS',row['variant'],'I=',row['i_frames'],'cut_I=',row['cut_frame_is_i'],
                  'MSE=',round(row['actual_postcut_mse'],3),'bytes=',row['video_bytes'],flush=True)
    (OUT/'V14_FORCED_KEYFRAME_RESULTS.json').write_text(json.dumps(all,indent=2))


if __name__=='__main__':main()
