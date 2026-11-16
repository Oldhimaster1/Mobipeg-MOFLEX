#!/usr/bin/env python3
"""Make a reversible, opt-in MobiClip intra prediction cost experiment.

MOBI_RDO_PRED_COST=0 original V5 behavior (default)
MOBI_RDO_PRED_COST=1 map H264 estimated neighbor/mode to MobiClip signaling
MOBI_RDO_PRED_COST=2 use MobiClip writer's current predictor state (may be stale during RDO)

Never changes bitstream writer; only the estimated bit rate in mode search.
"""
import argparse,pathlib
p=argparse.ArgumentParser();p.add_argument('cavlc');args=p.parse_args()
f=pathlib.Path(args.cavlc)
s=f.read_text()
old='''static int cavlc_intra4x4_pred_size( x264_t *h, int i4, int i_mode )
{
    if( x264_mb_predict_intra4x4_mode( h, i4 ) == x264_mb_pred_mode4x4_fix( i_mode ) )
        return 1;
    else
        return 4;
}'''
new='''/* V7 opt-in: use the MobiClip VLC mode alphabet when estimating the
 * 1-bit 'same as predicted' vs 4-bit 'explicit' mode signal. The original
 * H.264 predictor differs because this fork uses its own intra-mode remap.
 * The bitstream writer is deliberately unchanged.
 *
 * 0: V5 estimator (default, bit-exact baseline)
 * 1: H.264 neighbor predictor + MobiClip remapping (candidate)
 * 2: current MobiClip bit-writer state (experimental; may lag analysis)
 */
static int cavlc_intra4x4_pred_size( x264_t *h, int i4, int i_mode )
{
    if( h->param.i_mobiclip )
    {
        static int mode_cost_policy = -1;
        if( mode_cost_policy < 0 )
        {
            const char *env = getenv("MOBI_RDO_PRED_COST");
            mode_cost_policy = env ? atoi(env) : 0;
        }
        if( mode_cost_policy == 1 || mode_cost_policy == 2 )
        {
            int idx = i_mode + 1;
            int coded_h264 = idx >= 0 && idx < (int)sizeof(mobi_intra_to_h264)
                           ? mobi_intra_to_h264[idx] : 2;
            int coded_mobi = h264_to_mobiclip_mode[coded_h264 < 9 ? coded_h264 : 2];
            int predicted_mobi;
            if( mode_cost_policy == 1 )
            {
                int pred_h264 = x264_mb_predict_intra4x4_mode( h, i4 );
                /* The upstream result is a standardized H264 mode. */
                predicted_mobi = h264_to_mobiclip_mode[pred_h264 >= 0 && pred_h264 < 9 ? pred_h264 : 2];
            }
            else
            {
                /* Unlike mode_cost_policy 1, this can use the previous MB's
                 * writer state before the current MB has been serialized. */
                static const uint8_t block_x[16] =
                    {0,1,0,1,2,3,2,3,0,1,0,1,2,3,2,3};
                static const uint8_t block_y[16] =
                    {0,0,1,1,0,0,1,1,2,2,3,3,2,2,3,3};
                int bx = h->mb.i_mb_x*16 + 4*block_x[i4 & 15];
                int by = h->mb.i_mb_y*16 + 4*block_y[i4 & 15];
                predicted_mobi = mobi_get_predicted(h,bx,by);
            }
            return predicted_mobi == coded_mobi ? 1 : 4;
        }
    }
    return x264_mb_predict_intra4x4_mode( h, i4 ) == x264_mb_pred_mode4x4_fix( i_mode ) ? 1 : 4;
}'''
if old not in s:
 raise SystemExit('cavlc predictor function not found; no changes applied')
s=s.replace(old,new,1)
f.write_text(s)
print(f'Applied V7 reversible intra prediction RDO estimate to {f}')
