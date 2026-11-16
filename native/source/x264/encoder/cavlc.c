/*****************************************************************************
 * cavlc.c: cavlc bitstream writing
 *****************************************************************************
 * Copyright (C) 2003-2025 x264 project
 *
 * Authors: Laurent Aimar <fenrir@via.ecp.fr>
 *          Loren Merritt <lorenm@u.washington.edu>
 *          Fiona Glaser <fiona@x264.com>
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02111, USA.
 *
 * This program is also available under a commercial proprietary license.
 * For more information, contact us at licensing@x264.com.
 *****************************************************************************/

#include "common/common.h"
#include "macroblock.h"

/* A2 DIAGNOSTIC PROBE ONLY -- not part of any A2 candidate build.
 * Hoists the repeated getenv("MOBI_*") debug-gate checks in this file to a
 * one-time cached lookup, using the SAME lazy-static-init pattern already
 * used elsewhere in this codebase (see mobi_round_off's "static int dz = -1"
 * in encoder/macroblock.h). Behavior is unchanged: whatever the environment
 * variable's state was at first use is what governs the rest of the process,
 * exactly as today -- this purely removes the redundant re-check cost on
 * every subsequent call. This file is NOT linked into any A2 overhead-gate
 * or measurement build; it exists solely to quantify how much of the
 * measured "encode_p_block/encode_i_block" time is attributable to these
 * getenv() calls versus the underlying bit-writing work. */
#define A2_CACHED_GETENV(name) ({                          \
    static int _c = -1;                                     \
    if( _c < 0 ) _c = getenv(name) ? 1 : 0;                  \
    _c; })

#ifndef RDO_SKIP_BS
#define RDO_SKIP_BS 0
#endif

/* H.264 8x8 intra modes -> Mobiclip intra modes
 * H264: 0=V,1=H,2=DC,3=DDL,4=DDR,5=VR,6=HD,7=VL,8=HU */
/*  x264 internal:  0=V  1=H  2=PLANE  3=DC  4=HU  5=HD  6=VR  7=DDR  8=DDL
 *  mobiclip modes:  0=V  1=H  2=plane  3=DC  4=HU  5=VR  6=HD  7=DDR  8=VL
 *  DDL has no exact mobiclip equivalent; map to VL (mode 8) as closest match.
 */
static const int h264_to_mobiclip_mode[9] = { 0, 1, 3, 3, 7, 6, 5, 8, 4 };

/* Corrected x264 internal → H.264 standard I4x4 mode conversion.
 * The global x264_mb_pred_mode4x4_fix table is BROKEN in this fork because
 * I_PRED_4x4_PLANE=2 was inserted into the enum, shifting values 3-8, but
 * the fix table was not updated.  This corrected version should be used
 * wherever the output is interpreted as an H.264 standard mode number. */
static const uint8_t mobi_intra_to_h264[13] =
    { 2,0,1,2,2,8,6,5,4,3,2,2,2 };

/* Mobiclip chroma 8x8 prediction-mode mapping (x264 chroma mode -> mobiclip).
 * MUST avoid mobiclip mode 2 (plane), whose extra se_golomb plane parameters
 * are NOT emitted by encode_i_block — writing mode 2 desyncs the decoder.
 * Maps x264 {DC,H,V,P,DC_left,DC_top,DC_128} all into {V,H,DC} = {0,1,3}.
 * The exact pixel mode is unimportant as long as the encoder reconstruction
 * (mobi_predict_chroma_8x8) and the decoder use the SAME written value.
 * The upstream-x264 rebase replaced this with {0,1,2,3,0,0,0}, re-introducing
 * plane mode (2) and the desync. */
static const uint8_t mobi_chroma_pred_mode_fix[7] = { 0, 1, 3, 3, 3, 3, 3 };

#if !RDO_SKIP_BS && !HIGH_BIT_DEPTH
void x264_mobiclip_reset_pre(x264_t *h)
{
    memset(h->mobi_pre, 9, sizeof(h->mobi_pre));
    /* The decoder memset()s its motion[] array to 0 at the start of every
     * P-frame; mirror that so our mid_pred() predictor matches. */
    memset(h->mobi_motion_x, 0, sizeof(h->mobi_motion_x));
    memset(h->mobi_motion_y, 0, sizeof(h->mobi_motion_y));
}
#endif

/* FFmpeg's mid_pred: the median of three values (matches the decoder). */
static inline int mobi_mid_pred(int a, int b, int c)
{
    if (a > b) {
        if (c > b) { if (c > a) b = a; else b = c; }
    } else {
        if (b > c) { if (c > a) b = c; else b = a; }
    }
    return b;
}

/* Compute the Mobiclip predicted mode for an 8x8/4x4 block at pixel (bx, by). */
static int mobi_get_predicted(x264_t *h, int bx, int by)
{
    int index = (by & 0xC) | ((bx / 4) % 4);
    int above = h->mobi_pre[index];
    int left  = (index % 4 == 0) ? 9 : h->mobi_pre[index + 3];
    int pred  = above < left ? above : left;
    return (pred == 9) ? 3 : pred;  /* 9 = unknown -> default DC=3 */
}

/* Update the Mobiclip pre[] state after encoding an 8x8 block at (bx, by). */
static void mobi_update_pre(x264_t *h, int bx, int by, int mobi_mode)
{
    int index = (by & 0xC) | ((bx / 4) % 4);
    h->mobi_pre[index + 4] = mobi_mode;
    h->mobi_pre[index + 5] = mobi_mode;
    h->mobi_pre[index + 8] = mobi_mode;
    h->mobi_pre[index + 9] = mobi_mode;
}

/* Encode a Mobiclip intra prediction mode for an 8x8 block. */
static int mobi_write_pred_mode(x264_t *h, bs_t *s, int bx, int by, int mobi_mode)
{
    int pred = mobi_get_predicted(h, bx, by);
    int mode = mobi_mode;
    if (A2_CACHED_GETENV("MOBI_PMTRACE")) fprintf(stderr, "PM %d %d 8 %d %d %d\n", bx, by, pred, mode, pred!=mode);
    if (pred == mode) {
        bs_write1(s, 1);  /* use predicted mode */
    } else {
        int encoded = mode - (mode - 1 >= pred ? 1 : 0);
        /* explicit mode = leading 0 bit + 3-bit index (decoder: !get_bits1 then get_bits(3)).
         * encoded is in [0,7] so a 4-bit write emits the required 0xxx pattern. */
        bs_write(s, 4, encoded);
    }
    mobi_update_pre(h, bx, by, mode);
    return mode;
}

/* Encode a Mobiclip intra prediction mode for a 4x4 block at pixel (bx, by). */
static int mobi_write_pred_mode_4x4(x264_t *h, bs_t *s, int bx, int by, int mobi_mode)
{
    int pred  = mobi_get_predicted(h, bx, by);
    int mode  = mobi_mode;
    int index = (by & 0xC) | ((bx / 4) % 4);
    if (A2_CACHED_GETENV("MOBI_PMTRACE")) fprintf(stderr, "PM %d %d 4 %d %d %d\n", bx, by, pred, mode, pred!=mode);
    if (pred == mode) {
        bs_write1(s, 1);  /* use predicted mode */
    } else {
        int encoded = mode - (mode - 1 >= pred ? 1 : 0);
        /* explicit mode = leading 0 bit + 3-bit index (decoder: !get_bits1 then get_bits(3)).
         * encoded is in [0,7] so a 4-bit write emits the required 0xxx pattern. */
        bs_write(s, 4, encoded);
    }
    h->mobi_pre[index + 4] = mode;
    return mode;
}

/* [400,420][inter,intra] */
static const uint8_t cbp_to_golomb[2][2][48] =
{
    {{ 0,  1,  2,  5,  3,  6, 14, 10,  4, 15,  7, 11,  8, 12, 13,  9 },
     { 1, 10, 11,  6, 12,  7, 14,  2, 13, 15,  8,  3,  9,  4,  5,  0 }},
    {{ 0,  2,  3,  7,  4,  8, 17, 13,  5, 18,  9, 14, 10, 15, 16, 11,
       1, 32, 33, 36, 34, 37, 44, 40, 35, 45, 38, 41, 39, 42, 43, 19,
       6, 24, 25, 20, 26, 21, 46, 28, 27, 47, 22, 29, 23, 30, 31, 12 },
     { 3, 29, 30, 17, 31, 18, 37,  8, 32, 38, 19,  9, 20, 10, 11,  2,
      16, 33, 34, 21, 35, 22, 39,  4, 36, 40, 23,  5, 24,  6,  7,  1,
      41, 42, 43, 25, 44, 26, 46, 12, 45, 47, 27, 13, 28, 14, 15,  0 }}
};

static const uint8_t mb_type_b_to_golomb[3][9]=
{
    { 4,  8, 12, 10,  6, 14, 16, 18, 20 }, /* D_16x8 */
    { 5,  9, 13, 11,  7, 15, 17, 19, 21 }, /* D_8x16 */
    { 1, -1, -1, -1,  2, -1, -1, -1,  3 }  /* D_16x16 */
};

static const uint8_t subpartition_p_to_golomb[4]=
{
    3, 1, 2, 0
};

static const uint8_t subpartition_b_to_golomb[13]=
{
    10,  4,  5,  1, 11,  6,  7,  2, 12,  8,  9,  3,  0
};

#define bs_write_vlc(s,v) bs_write( s, (v).i_size, (v).i_bits )

/****************************************************************************
 * x264_cavlc_block_residual:
 ****************************************************************************/
static inline int cavlc_block_residual_escape( x264_t *h, int i_suffix_length, int level )
{
    bs_t *s = &h->out.bs;
    static const uint16_t next_suffix[7] = { 0, 3, 6, 12, 24, 48, 0xffff };
    int i_level_prefix = 15;
    int mask = level >> 31;
    int abs_level = (level^mask)-mask;
    int i_level_code = abs_level*2-mask-2;
    if( ( i_level_code >> i_suffix_length ) < 15 )
    {
        bs_write( s, (i_level_code >> i_suffix_length) + 1 + i_suffix_length,
                 (1<<i_suffix_length) + (i_level_code & ((1<<i_suffix_length)-1)) );
    }
    else
    {
        i_level_code -= 15 << i_suffix_length;
        if( i_suffix_length == 0 )
            i_level_code -= 15;

        /* If the prefix size exceeds 15, High Profile is required. */
        if( i_level_code >= 1<<12 )
        {
            if( h->sps->i_profile_idc >= PROFILE_HIGH )
            {
                while( i_level_code >= 1<<(i_level_prefix-3) )
                {
                    i_level_code -= 1<<(i_level_prefix-3);
                    i_level_prefix++;
                }
            }
            else
            {
#if RDO_SKIP_BS
                /* Weight highly against overflows. */
                s->i_bits_encoded += 2000;
#else
                /* We've had an overflow; note it down and re-encode the MB later. */
                h->mb.b_overflow = 1;
#endif
            }
        }
        bs_write( s, i_level_prefix + 1, 1 );
        bs_write( s, i_level_prefix - 3, i_level_code & ((1<<(i_level_prefix-3))-1) );
    }
    if( i_suffix_length == 0 )
        i_suffix_length++;
    if( abs_level > next_suffix[i_suffix_length] )
        i_suffix_length++;
    return i_suffix_length;
}

static int cavlc_block_residual_internal( x264_t *h, int ctx_block_cat, dctcoef *l, int nC )
{
    bs_t *s = &h->out.bs;
    static const uint8_t ctz_index[8] = {3,0,1,0,2,0,1,0};
    static const uint8_t count_cat[14] = {16, 15, 16, 0, 15, 64, 16, 15, 16, 64, 16, 15, 16, 64};
    x264_run_level_t runlevel;
    int i_total, i_trailing, i_total_zero, i_suffix_length;
    unsigned int i_sign;

    /* level and run and total */
    i_total = h->quantf.coeff_level_run[ctx_block_cat]( l, &runlevel );
    x264_prefetch( &x264_run_before[runlevel.mask] );
    i_total_zero = runlevel.last + 1 - i_total;

    /* branchless i_trailing calculation */
    runlevel.level[i_total+0] = 2;
    runlevel.level[i_total+1] = 2;
    i_trailing = ((((runlevel.level[0]+1) | (1-runlevel.level[0])) >> 31) & 1) // abs(runlevel.level[0])>1
               | ((((runlevel.level[1]+1) | (1-runlevel.level[1])) >> 31) & 2)
               | ((((runlevel.level[2]+1) | (1-runlevel.level[2])) >> 31) & 4);
    i_trailing = ctz_index[i_trailing];
    i_sign = ((runlevel.level[2] >> 31) & 1)
           | ((runlevel.level[1] >> 31) & 2)
           | ((runlevel.level[0] >> 31) & 4);
    i_sign >>= 3-i_trailing;

    /* total/trailing */
    bs_write_vlc( s, x264_coeff_token[nC][i_total-1][i_trailing] );

    i_suffix_length = i_total > 10 && i_trailing < 3;
    bs_write( s, i_trailing, i_sign );

    if( i_trailing < i_total )
    {
        int val = runlevel.level[i_trailing];
        int val_original = runlevel.level[i_trailing]+LEVEL_TABLE_SIZE/2;
        val -= ((val>>31)|1) & -(i_trailing < 3); /* as runlevel.level[i] can't be 1 for the first one if i_trailing < 3 */
        val += LEVEL_TABLE_SIZE/2;

        if( (unsigned)val_original < LEVEL_TABLE_SIZE )
        {
            bs_write_vlc( s, x264_level_token[i_suffix_length][val] );
            i_suffix_length = x264_level_token[i_suffix_length][val_original].i_next;
        }
        else
            i_suffix_length = cavlc_block_residual_escape( h, i_suffix_length, val-LEVEL_TABLE_SIZE/2 );
        for( int i = i_trailing+1; i < i_total; i++ )
        {
            val = runlevel.level[i] + LEVEL_TABLE_SIZE/2;
            if( (unsigned)val < LEVEL_TABLE_SIZE )
            {
                bs_write_vlc( s, x264_level_token[i_suffix_length][val] );
                i_suffix_length = x264_level_token[i_suffix_length][val].i_next;
            }
            else
                i_suffix_length = cavlc_block_residual_escape( h, i_suffix_length, val-LEVEL_TABLE_SIZE/2 );
        }
    }

    if( ctx_block_cat == DCT_CHROMA_DC )
    {
        if( i_total < 8>>CHROMA_V_SHIFT )
        {
            vlc_t total_zeros = CHROMA_FORMAT == CHROMA_420 ? x264_total_zeros_2x2_dc[i_total-1][i_total_zero]
                                                            : x264_total_zeros_2x4_dc[i_total-1][i_total_zero];
            bs_write_vlc( s, total_zeros );
        }
    }
    else if( (uint8_t)i_total < count_cat[ctx_block_cat] )
        bs_write_vlc( s, x264_total_zeros[i_total-1][i_total_zero] );

    int zero_run_code = x264_run_before[runlevel.mask];
    bs_write( s, zero_run_code&0x1f, zero_run_code>>5 );

    return i_total;
}

static const uint8_t ct_index[17] = {0,0,1,1,2,2,2,2,3,3,3,3,3,3,3,3,3};

#define x264_cavlc_block_residual(h,cat,idx,l)\
{\
    int nC = cat == DCT_CHROMA_DC ? 5 - CHROMA_V_SHIFT\
                                  : ct_index[x264_mb_predict_non_zero_code( h, cat == DCT_LUMA_DC ? (idx - LUMA_DC)*16 : idx )];\
    uint8_t *nnz = &h->mb.cache.non_zero_count[x264_scan8[idx]];\
    if( !*nnz )\
        bs_write_vlc( &h->out.bs, x264_coeff0_token[nC] );\
    else\
        *nnz = cavlc_block_residual_internal(h,cat,l,nC);\
}

static void cavlc_qp_delta( x264_t *h )
{
    bs_t *s = &h->out.bs;
    int i_dqp = h->mb.i_qp - h->mb.i_last_qp;

    /* Avoid writing a delta quant if we have an empty i16x16 block, e.g. in a completely
     * flat background area. Don't do this if it would raise the quantizer, since that could
     * cause unexpected deblocking artifacts. */
    if( h->mb.i_type == I_16x16 && !(h->mb.i_cbp_luma | h->mb.i_cbp_chroma)
        && !h->mb.cache.non_zero_count[x264_scan8[LUMA_DC]]
        && !h->mb.cache.non_zero_count[x264_scan8[CHROMA_DC+0]]
        && !h->mb.cache.non_zero_count[x264_scan8[CHROMA_DC+1]]
        && h->mb.i_qp > h->mb.i_last_qp )
    {
#if !RDO_SKIP_BS
        h->mb.i_qp = h->mb.i_last_qp;
#endif
        i_dqp = 0;
    }

    if( i_dqp )
    {
        if( i_dqp < -(QP_MAX_SPEC+1)/2 )
            i_dqp += QP_MAX_SPEC+1;
        else if( i_dqp > QP_MAX_SPEC/2 )
            i_dqp -= QP_MAX_SPEC+1;
    }
    bs_write_se( s, i_dqp );
}

static void cavlc_mvd( x264_t *h, int i_list, int idx, int width )
{
    bs_t *s = &h->out.bs;
    ALIGNED_4( int16_t mvp[2] );
    x264_mb_predict_mv( h, i_list, idx, width, mvp );
    bs_write_se( s, h->mb.cache.mv[i_list][x264_scan8[idx]][0] - mvp[0] );
    bs_write_se( s, h->mb.cache.mv[i_list][x264_scan8[idx]][1] - mvp[1] );
}

static inline void cavlc_8x8_mvd( x264_t *h, int i )
{
    switch( h->mb.i_sub_partition[i] )
    {
        case D_L0_8x8:
            cavlc_mvd( h, 0, 4*i, 2 );
            break;
        case D_L0_8x4:
            cavlc_mvd( h, 0, 4*i+0, 2 );
            cavlc_mvd( h, 0, 4*i+2, 2 );
            break;
        case D_L0_4x8:
            cavlc_mvd( h, 0, 4*i+0, 1 );
            cavlc_mvd( h, 0, 4*i+1, 1 );
            break;
        case D_L0_4x4:
            cavlc_mvd( h, 0, 4*i+0, 1 );
            cavlc_mvd( h, 0, 4*i+1, 1 );
            cavlc_mvd( h, 0, 4*i+2, 1 );
            cavlc_mvd( h, 0, 4*i+3, 1 );
            break;
    }
}

static ALWAYS_INLINE void cavlc_macroblock_luma_residual( x264_t *h, int plane_count )
{
    if( h->mb.b_transform_8x8 )
    {
        /* shuffle 8x8 dct coeffs into 4x4 lists */
        for( int p = 0; p < plane_count; p++ )
            for( int i8 = 0; i8 < 4; i8++ )
                if( h->mb.cache.non_zero_count[x264_scan8[p*16+i8*4]] )
                    h->zigzagf.interleave_8x8_cavlc( h->dct.luma4x4[p*16+i8*4], h->dct.luma8x8[p*4+i8],
                                                     &h->mb.cache.non_zero_count[x264_scan8[p*16+i8*4]] );
    }

    for( int p = 0; p < plane_count; p++ )
        FOREACH_BIT( i8, 0, h->mb.i_cbp_luma )
            for( int i4 = 0; i4 < 4; i4++ )
                x264_cavlc_block_residual( h, DCT_LUMA_4x4, i4+i8*4+p*16, h->dct.luma4x4[i4+i8*4+p*16] );
}

#if RDO_SKIP_BS
static ALWAYS_INLINE void cavlc_partition_luma_residual( x264_t *h, int i8, int p )
{
    if( h->mb.b_transform_8x8 && h->mb.cache.non_zero_count[x264_scan8[i8*4+p*16]] )
        h->zigzagf.interleave_8x8_cavlc( h->dct.luma4x4[i8*4+p*16], h->dct.luma8x8[i8+p*4],
                                         &h->mb.cache.non_zero_count[x264_scan8[i8*4+p*16]] );

    if( h->mb.i_cbp_luma & (1 << i8) )
        for( int i4 = 0; i4 < 4; i4++ )
            x264_cavlc_block_residual( h, DCT_LUMA_4x4, i4+i8*4+p*16, h->dct.luma4x4[i4+i8*4+p*16] );
}
#endif

static void cavlc_mb_header_i( x264_t *h, int i_mb_type, int i_mb_i_offset, int chroma )
{
	//h->mb.
    bs_t *s = &h->out.bs;
    if( i_mb_type == I_16x16 )
    {
        bs_write_ue( s, i_mb_i_offset + 1 + x264_mb_pred_mode16x16_fix[h->mb.i_intra16x16_pred_mode] +
                        h->mb.i_cbp_chroma * 4 + ( h->mb.i_cbp_luma == 0 ? 0 : 12 ) );
    }
    else //if( i_mb_type == I_4x4 || i_mb_type == I_8x8 )
    {
        int di = i_mb_type == I_8x8 ? 4 : 1;
        if( h->param.i_mobiclip )
        {
            //check if all the same block type
            int type = x264_mb_pred_mode4x4_fix(h->mb.cache.intra4x4_pred_mode[x264_scan8[0]]);
            BOOL same = TRUE;
            for (int i = 0; i < 16; i += di)
            {
                if (x264_mb_pred_mode4x4_fix(h->mb.cache.intra4x4_pred_mode[x264_scan8[i]]) != type)
                {
                    same = FALSE;
                    break;
                }
            }
            if (same)
                bs_write1(s, 0);
            else
                bs_write1(s, 1);
        }
        else
        {
            bs_write_ue( s, i_mb_i_offset + 0 );
            if( h->pps->b_transform_8x8_mode )
                bs_write1( s, h->mb.b_transform_8x8 );
        }

        /* Prediction: Luma */
        for( int i = 0; i < 16; i += di )
        {
            int i_pred = x264_mb_predict_intra4x4_mode( h, i );
            int i_mode = x264_mb_pred_mode4x4_fix( h->mb.cache.intra4x4_pred_mode[x264_scan8[i]] );

            if( i_pred == i_mode )
                bs_write1( s, 1 );  /* b_prev_intra4x4_pred_mode */
            else
                bs_write( s, 4, i_mode - (i_mode > i_pred) );
        }

    }
    if( chroma )
        bs_write_ue( s, x264_mb_chroma_pred_mode_fix[h->mb.i_chroma_pred_mode] );
}

static ALWAYS_INLINE void cavlc_mb_header_p( x264_t *h, int i_mb_type, int chroma )
{
    bs_t *s = &h->out.bs;
    if( i_mb_type == P_L0 )
    {
        if( h->mb.i_partition == D_16x16 )
        {
            bs_write1( s, 1 );

            if( h->mb.pic.i_fref[0] > 1 )
                bs_write_te( s, h->mb.pic.i_fref[0] - 1, h->mb.cache.ref[0][x264_scan8[0]] );
            cavlc_mvd( h, 0, 0, 4 );
        }
        else if( h->mb.i_partition == D_16x8 )
        {
            bs_write_ue( s, 1 );
            if( h->mb.pic.i_fref[0] > 1 )
            {
                bs_write_te( s, h->mb.pic.i_fref[0] - 1, h->mb.cache.ref[0][x264_scan8[0]] );
                bs_write_te( s, h->mb.pic.i_fref[0] - 1, h->mb.cache.ref[0][x264_scan8[8]] );
            }
            cavlc_mvd( h, 0, 0, 4 );
            cavlc_mvd( h, 0, 8, 4 );
        }
        else if( h->mb.i_partition == D_8x16 )
        {
            bs_write_ue( s, 2 );
            if( h->mb.pic.i_fref[0] > 1 )
            {
                bs_write_te( s, h->mb.pic.i_fref[0] - 1, h->mb.cache.ref[0][x264_scan8[0]] );
                bs_write_te( s, h->mb.pic.i_fref[0] - 1, h->mb.cache.ref[0][x264_scan8[4]] );
            }
            cavlc_mvd( h, 0, 0, 2 );
            cavlc_mvd( h, 0, 4, 2 );
        }
    }
    else if( i_mb_type == P_8x8 )
    {
        int b_sub_ref;
        if( (h->mb.cache.ref[0][x264_scan8[0]] | h->mb.cache.ref[0][x264_scan8[ 4]] |
             h->mb.cache.ref[0][x264_scan8[8]] | h->mb.cache.ref[0][x264_scan8[12]]) == 0 )
        {
            bs_write_ue( s, 4 );
            b_sub_ref = 0;
        }
        else
        {
            bs_write_ue( s, 3 );
            b_sub_ref = 1;
        }

        /* sub mb type */
        if( h->param.analyse.inter & X264_ANALYSE_PSUB8x8 )
            for( int i = 0; i < 4; i++ )
                bs_write_ue( s, subpartition_p_to_golomb[ h->mb.i_sub_partition[i] ] );
        else
            bs_write( s, 4, 0xf );

        /* ref0 */
        if( b_sub_ref )
        {
            bs_write_te( s, h->mb.pic.i_fref[0] - 1, h->mb.cache.ref[0][x264_scan8[0]] );
            bs_write_te( s, h->mb.pic.i_fref[0] - 1, h->mb.cache.ref[0][x264_scan8[4]] );
            bs_write_te( s, h->mb.pic.i_fref[0] - 1, h->mb.cache.ref[0][x264_scan8[8]] );
            bs_write_te( s, h->mb.pic.i_fref[0] - 1, h->mb.cache.ref[0][x264_scan8[12]] );
        }

        for( int i = 0; i < 4; i++ )
            cavlc_8x8_mvd( h, i );
    }
    else //if( IS_INTRA( i_mb_type ) )
        cavlc_mb_header_i( h, i_mb_type, 5, chroma );
}

static ALWAYS_INLINE void cavlc_mb_header_b( x264_t *h, int i_mb_type, int chroma )
{
    bs_t *s = &h->out.bs;
    if( i_mb_type == B_8x8 )
    {
        bs_write_ue( s, 22 );

        /* sub mb type */
        for( int i = 0; i < 4; i++ )
            bs_write_ue( s, subpartition_b_to_golomb[ h->mb.i_sub_partition[i] ] );

        /* ref */
        if( h->mb.pic.i_fref[0] > 1 )
            for( int i = 0; i < 4; i++ )
                if( x264_mb_partition_listX_table[0][ h->mb.i_sub_partition[i] ] )
                    bs_write_te( s, h->mb.pic.i_fref[0] - 1, h->mb.cache.ref[0][x264_scan8[i*4]] );
        if( h->mb.pic.i_fref[1] > 1 )
            for( int i = 0; i < 4; i++ )
                if( x264_mb_partition_listX_table[1][ h->mb.i_sub_partition[i] ] )
                    bs_write_te( s, h->mb.pic.i_fref[1] - 1, h->mb.cache.ref[1][x264_scan8[i*4]] );

        /* mvd */
        for( int i = 0; i < 4; i++ )
            if( x264_mb_partition_listX_table[0][ h->mb.i_sub_partition[i] ] )
                cavlc_mvd( h, 0, 4*i, 2 );
        for( int i = 0; i < 4; i++ )
            if( x264_mb_partition_listX_table[1][ h->mb.i_sub_partition[i] ] )
                cavlc_mvd( h, 1, 4*i, 2 );
    }
    else if( i_mb_type >= B_L0_L0 && i_mb_type <= B_BI_BI )
    {
        /* All B mode */
        /* Motion Vector */
        const uint8_t (*b_list)[2] = x264_mb_type_list_table[i_mb_type];
        const int i_ref0_max = h->mb.pic.i_fref[0] - 1;
        const int i_ref1_max = h->mb.pic.i_fref[1] - 1;

        bs_write_ue( s, mb_type_b_to_golomb[ h->mb.i_partition - D_16x8 ][ i_mb_type - B_L0_L0 ] );
        if( h->mb.i_partition == D_16x16 )
        {
            if( i_ref0_max && b_list[0][0] ) bs_write_te( s, i_ref0_max, h->mb.cache.ref[0][x264_scan8[0]] );
            if( i_ref1_max && b_list[1][0] ) bs_write_te( s, i_ref1_max, h->mb.cache.ref[1][x264_scan8[0]] );
            if( b_list[0][0] ) cavlc_mvd( h, 0, 0, 4 );
            if( b_list[1][0] ) cavlc_mvd( h, 1, 0, 4 );
        }
        else
        {
            if( i_ref0_max && b_list[0][0] ) bs_write_te( s, i_ref0_max, h->mb.cache.ref[0][x264_scan8[ 0]] );
            if( i_ref0_max && b_list[0][1] ) bs_write_te( s, i_ref0_max, h->mb.cache.ref[0][x264_scan8[12]] );
            if( i_ref1_max && b_list[1][0] ) bs_write_te( s, i_ref1_max, h->mb.cache.ref[1][x264_scan8[ 0]] );
            if( i_ref1_max && b_list[1][1] ) bs_write_te( s, i_ref1_max, h->mb.cache.ref[1][x264_scan8[12]] );
            if( h->mb.i_partition == D_16x8 )
            {
                if( b_list[0][0] ) cavlc_mvd( h, 0, 0, 4 );
                if( b_list[0][1] ) cavlc_mvd( h, 0, 8, 4 );
                if( b_list[1][0] ) cavlc_mvd( h, 1, 0, 4 );
                if( b_list[1][1] ) cavlc_mvd( h, 1, 8, 4 );
            }
            else //if( h->mb.i_partition == D_8x16 )
            {
                if( b_list[0][0] ) cavlc_mvd( h, 0, 0, 2 );
                if( b_list[0][1] ) cavlc_mvd( h, 0, 4, 2 );
                if( b_list[1][0] ) cavlc_mvd( h, 1, 0, 2 );
                if( b_list[1][1] ) cavlc_mvd( h, 1, 4, 2 );
            }
        }
    }
    else if( i_mb_type == B_DIRECT )
        bs_write1( s, 1 );
    else //if( IS_INTRA( i_mb_type ) )
        cavlc_mb_header_i( h, i_mb_type, 23, chroma );
}

static int encode_dct(x264_t* h, dctcoef *l, int length, int table)
{
	bs_t *s = &h->out.bs;
	const uint16_t* r11A = table == 1 ? vx2_table1_a : vx2_table0_a;
	const uint8_t* r11B = table == 1 ? vx2_table1_b : vx2_table0_b;
	const int (*reftable)[64][2] = table == 1 ? vx2_table1_a_rev : vx2_table0_a_rev;
	int lastnonzero = 0;
	int nnz = 0;
	for (int i = 0; i < length; i++)
	{
		if (l[i] != 0)
		{
			lastnonzero = i;
			nnz++;
		}
	}
#if !RDO_SKIP_BS
	static int _dctblk = 0;
	int _dctstart = bs_pos(s);
	int _dctn = _dctblk;
	if (A2_CACHED_GETENV("MOBI_DCTDBG")) {
		fprintf(stderr, "DCTIN blk=%d len=%d nnz=%d last=%d:", _dctblk, length, nnz, lastnonzero);
		for (int i = 0; i < length; i++) if (l[i]) fprintf(stderr, " %d:%d", i, l[i]);
		fprintf(stderr, "\n");
	}
	_dctblk++;
#endif
	int skip = 0;
	for (int i = 0; i < length; i++)
	{
		if (l[i] == 0 && lastnonzero != 0)
		{
			skip++;
			continue;
		}
		int val = l[i];
		if (val < 0)
			val = -val;
		if (A2_CACHED_GETENV("MOBI_SIMPLEDCT")) goto explicit;
		if (val <= 31)
		{
			int idx = reftable[val][skip][(i == lastnonzero) ? 1 : 0];
			if (idx >= 0)
			{
				int nrbits = r11A[idx] & 0xF;
				uint32_t tidx = (uint32_t)idx;
				if (nrbits < 12)
					tidx >>= (12 - nrbits);
				else if (nrbits > 12)
					tidx <<= (nrbits - 12);
				if (l[i] < 0) 
					tidx |= 1;
				//x264_log(h, X264_LOG_ERROR, "DCT ENC: val=%d skip=%d last=%d -> sym=%x (bits: %x, len: %d)\n", val, skip, i==lastnonzero, idx, tidx, nrbits);
				bs_write(s, nrbits, tidx);
				skip = 0;
				goto end;
			}
			int newskip = skip - r11B[(val | (((i == lastnonzero) ? 1 : 0) << 6)) + 0x80];
			if (newskip >= 0)
			{
				idx = reftable[val][newskip][(i == lastnonzero) ? 1 : 0];
				if (idx >= 0)
				{
					{
					int esc_idx = reftable[0][0][0];
					int esc_nrbits = r11A[esc_idx] & 0xF;
					uint32_t esc_tidx = (uint32_t)esc_idx;
					if (esc_nrbits < 12)
						esc_tidx >>= (12 - esc_nrbits);
					else if (esc_nrbits > 12)
						esc_tidx <<= (esc_nrbits - 12);
					bs_write(s, esc_nrbits, esc_tidx);
				}
					bs_write1(s, 1);
					bs_write1(s, 0);
					int nrbits = r11A[idx] & 0xF;
					uint32_t tidx = (uint32_t)idx;
					if (nrbits < 12)
						tidx >>= (12 - nrbits);
					else if (nrbits > 12)
						tidx <<= (nrbits - 12);
					if (l[i] < 0)
						tidx |= 1;
					bs_write(s, nrbits, tidx);
					skip = 0;
					goto end;
				}
			}
		}
		int newval = val - r11B[skip | (((i == lastnonzero) ? 1 : 0) << 6)];
		if (newval >= 0 && newval <= 31)
		{
			int idx = reftable[newval][skip][(i == lastnonzero) ? 1 : 0];
			if (idx >= 0)
			{
				{
					int esc_idx = reftable[0][0][0];
					int esc_nrbits = r11A[esc_idx] & 0xF;
					uint32_t esc_tidx = (uint32_t)esc_idx;
					if (esc_nrbits < 12)
						esc_tidx >>= (12 - esc_nrbits);
					else if (esc_nrbits > 12)
						esc_tidx <<= (esc_nrbits - 12);
					bs_write(s, esc_nrbits, esc_tidx);
				}
				bs_write1(s, 0);
				int nrbits = r11A[idx] & 0xF;
				uint32_t tidx = (uint32_t)idx;
				if (nrbits < 12)
					tidx >>= (12 - nrbits);
				else if (nrbits > 12)
					tidx <<= (nrbits - 12);
				if (l[i] < 0) 
					tidx |= 1;
				bs_write(s, nrbits, tidx);
				skip = 0;
				goto end;
			}
		}
		//This is easiest way of writing the DCT, but also costs the most bits
explicit:
		{
			int esc_idx = reftable[0][0][0];
			int esc_nrbits = r11A[esc_idx] & 0xF;
			uint32_t esc_tidx = (uint32_t)esc_idx;
			if (esc_nrbits < 12)
				esc_tidx >>= (12 - esc_nrbits);
			else if (esc_nrbits > 12)
				esc_tidx <<= (esc_nrbits - 12);
			bs_write(s, esc_nrbits, esc_tidx);
		}
		bs_write1(s, 1);
		bs_write1(s, 1);
		if (i == lastnonzero)
			bs_write1(s, 1);
		else
			bs_write1(s, 0);
		bs_write(s, 6, skip);
		skip = 0;
		bs_write(s, 12, l[i] & 0xFFF);
	end:
		if (i == lastnonzero) 
			break;
	}
#if !RDO_SKIP_BS
	if (A2_CACHED_GETENV("MOBI_DCTDBG"))
		fprintf(stderr, "DCTLEN blk=%d bits=%d\n", _dctn, bs_pos(s) - _dctstart);
#endif
	return nnz;
}

static uint8_t block_mask_to_golomb_table[] =
{
	0, 7, 6, 12, 5, 19, 29, 13, 4, 27, 17, 8, 14, 11, 9, 3, 20, 33, 34, 24, 35, 30, 41, 15, 36, 40, 31, 10, 28, 16, 18, 1, 37, 55, 57, 52, 58, 56, 63, 46, 61, 62, 60, 48, 59, 49, 54, 21, 43, 44, 45, 32, 47, 39, 53, 22, 51, 50, 42, 23, 38, 25, 26, 2,
};

static uint8_t subblock_mask_to_golomb_table[] =
{
	2, 4, 3, 8, 5, 14, 16, 12, 6, 15, 13, 9, 7, 10, 11, 1
};

/* Forward declarations so encode_i_block (used for intra MBs inside P-frames)
 * can emit the mv_vlc INTRA prefix.  The full tables are defined later. */
static const uint8_t mobi_mv_enc_len[2][16][10];
static const uint8_t mobi_mv_enc_code[2][16][10];

/* Matches the decoder's get_index(): 16->0, 8->1, 4->2, 2->3 (else 0). */
static inline int mobi_size_index(int s)
{
	return s == 16 ? 0 : s == 8 ? 1 : s == 4 ? 2 : s == 2 ? 3 : 0;
}

#define mobi_encode_p_partition_mode(s, w, hh, mode)                                  \
	do {                                                                               \
		int _mf = h->param.b_moflex ? 1 : 0;                                           \
		int _ti = mobi_size_index(hh) * 4 + mobi_size_index(w);                        \
		bs_write((s), mobi_mv_enc_len[_mf][_ti][(mode)], mobi_mv_enc_code[_mf][_ti][(mode)]); \
	} while (0)

#if !RDO_SKIP_BS
/* ============================================================================
 * ACT24 Piece 1: P_INTRA_FULL candidate generation for MBs intra-coded
 * inside a P-slice (ACT23 Phase 1 audit: 0 occurrences vs official's 63,698).
 * Root cause (evidence\act24_modecoverage_investigation_20260825_111500\
 * step1_2_root_cause.md): encode_i_block's `equalPredict` was hardcoded
 * FALSE -- the write-side symbol emission for INTRA_FULL was already
 * correct, only the mode-decision was stubbed off, citing a boundary-
 * behaviour mismatch in x264's OWN stock 8x8 intra reconstruction. That
 * mismatch does not apply here: this evaluator reuses x264_mb_encode_i4x4()
 * -- the SAME already-proven, MobiClip-exact (mobi_predict_4x4/mobi_pget
 * -based) reconstruction the always-taken per-block path already uses in
 * production today -- called with a single forced mode across all 16 luma
 * 4x4 blocks instead of each block's own mode. No new prediction math.
 *
 * Scope: P-frame-embedded intra MBs only (h->sh.i_type != SLICE_TYPE_I --
 * real I-frame slices are untouched, equalPredict stays hardcoded FALSE for
 * them exactly as before), I_4x4 type only (I_8x8/I_16x16 luma excluded,
 * same b_transform_8x8-off boundary every ACT2x phase in this file
 * respects), luma only -- chroma pmode signaling (mobi_chroma_pred_mode_fix,
 * bs_write(s,3,...) a few lines below) is unconditional regardless of the
 * luma equalPredict flag, confirmed from mobiclip.c's decode_macroblock, so
 * chroma cannot be affected by this decision at all.
 *
 * Bit measurement calls the REAL encode_i_block() itself into a scratch bs
 * buffer with the decision forced -- not a hand-mirrored cost model -- so
 * there is zero risk of the measurement drifting from what actually gets
 * written; chroma bits are identical in both scratch calls (chroma state is
 * never touched here) and cancel exactly in the bits-saved delta.
 *
 * Env: MOBI_ACT24_INTRAFULL_SIM[_OUT], MOBI_ACT24_INTRAFULL_ENABLE.
 * ============================================================================ */

static void encode_i_block( x264_t *h ); /* forward decl: eval calls the real writer to measure bits */
static int mobi_act24_force_equal_predict = -1; /* -1 = no override (real decision path runs); else forces equalPredict for a scratch measurement */

static FILE *mobi_act24_intrafull_sim_fp( void )
{
    static int enabled = -1;
    static FILE *fp = NULL;
    if( enabled < 0 )
    {
        const char *prefix = getenv( "MOBI_ACT24_INTRAFULL_SIM" );
        enabled = ( prefix && atoi(prefix) ) ? 1 : 0;
        if( enabled )
        {
            char path[4096];
            const char *outpfx = getenv( "MOBI_ACT24_INTRAFULL_SIM_OUT" );
            snprintf( path, sizeof(path), "%s_intrafull.csv", outpfx ? outpfx : "mobi_act24" );
            fp = fopen( path, "w" );
            if( fp )
                fprintf( fp, "frame_index,mb_x,mb_y,forced_mode,cur_bits,cand_bits,bits_saved,cur_sse,cand_sse,max_abs_pixel_diff,classification,rejection_reason\n" );
        }
        enabled = fp ? 1 : 0;
    }
    return enabled ? fp : NULL;
}

/* R1 RELEASE DEFAULT CHANGE: P_INTRA_FULL is now ON by default, same
 * override discipline as the ACT36 gates (explicit MOBI_ACT24_INTRAFULL_ENABLE
 * always wins; every pre-existing reproduction command sets it explicitly
 * and is unaffected). Deliberately NOT gated by MOBI_LEGACY_COMPAT: per
 * ACT37 Step 0's counterfactual-reencode proof, P_INTRA_FULL has been part
 * of "the established baseline" this whole investigation has ever compared
 * against since ACT24/ACT25 -- it predates and is independent of ACT36's
 * transform work. MOBI_LEGACY_COMPAT reproduces the old TRANSFORM behavior
 * specifically (see macroblock.h), not a return to a state that was never
 * actually the baseline. */
static int mobi_act24_intrafull_activate_enabled( void )
{
    static int enabled = -1;
    if( enabled < 0 )
    {
        const char *v = getenv( "MOBI_ACT24_INTRAFULL_ENABLE" );
        enabled = v ? ( atoi(v) ? 1 : 0 ) : 1;
    }
    return enabled;
}

static int mobi_act24_scratch_bits( x264_t *h, int force )
{
    bs_t save_bs = h->out.bs;
    uint8_t scratch[4096];
    bs_init( &h->out.bs, scratch, sizeof(scratch) );
    mobi_act24_force_equal_predict = force;
    encode_i_block( h );
    mobi_act24_force_equal_predict = -1;
    int bits = bs_pos( &h->out.bs );
    h->out.bs = save_bs;
    return bits;
}

/* Returns the equalPredict decision the real write should use (0 or 1).
 * do_activate=0: read-only -- restores all state before returning, never
 * leaves a mutation behind. do_activate=1: on a win, leaves the winning
 * (forced-single-mode) reconstruction in place for the real write to use;
 * on a loss, restores the original per-block reconstruction. */
static int mobi_act24_intrafull_eval( x264_t *h, FILE *sim_fp, int do_activate )
{
    if( h->mb.i_type != I_4x4 || h->mb.b_transform_8x8 )
        return 0;

    pixel *p_fdec = h->mb.pic.p_fdec[0];
    pixel *p_fenc = h->mb.pic.p_fenc[0];

    pixel saved_fdec[16*FDEC_STRIDE];
    for( int y = 0; y < 16; y++ )
        memcpy( &saved_fdec[y*FDEC_STRIDE], &p_fdec[y*FDEC_STRIDE], 16*sizeof(pixel) );
    ALIGNED_ARRAY_16( dctcoef, saved_luma4x4, [16], [16] );
    memcpy( saved_luma4x4, h->dct.luma4x4, sizeof(dctcoef)*16*16 );
    uint8_t saved_nnz[16];
    for( int i = 0; i < 16; i++ )
        saved_nnz[i] = h->mb.cache.non_zero_count[x264_scan8[i]];
    int saved_cbp_luma = h->mb.i_cbp_luma;
    int forced_mode = h->mb.cache.intra4x4_pred_mode[x264_scan8[0]];

    double cur_sse = 0;
    for( int y = 0; y < 16; y++ )
        for( int x = 0; x < 16; x++ )
        {
            int d = (int)saved_fdec[y*FDEC_STRIDE+x] - (int)p_fenc[y*FENC_STRIDE+x];
            cur_sse += (double)(d*d);
        }
    int cur_bits = mobi_act24_scratch_bits( h, 0 );

    for( int i = 0; i < 16; i++ )
    {
        pixel *p_dst = &h->mb.pic.p_fdec[0][block_idx_xy_fdec[i]];
        if( (h->mb.i_neighbour4[i] & (MB_TOPRIGHT|MB_TOP)) == MB_TOP )
            MPIXEL_X4( &p_dst[4-FDEC_STRIDE] ) = PIXEL_SPLAT_X4( p_dst[3-FDEC_STRIDE] );
        x264_mb_encode_i4x4( h, 0, i, h->mb.i_qp, forced_mode, 1 );
    }
    {
        int cbp = 0;
        for( int g = 0; g < 4; g++ )
        {
            int any = 0;
            for( int k = 0; k < 4; k++ )
                if( h->mb.cache.non_zero_count[x264_scan8[g*4+k]] ) any = 1;
            if( any ) cbp |= 1 << g;
        }
        h->mb.i_cbp_luma = cbp;
    }

    double cand_sse = 0; int max_abs = 0;
    for( int y = 0; y < 16; y++ )
        for( int x = 0; x < 16; x++ )
        {
            int d = (int)p_fdec[y*FDEC_STRIDE+x] - (int)p_fenc[y*FENC_STRIDE+x];
            cand_sse += (double)(d*d);
            int ad = abs( (int)p_fdec[y*FDEC_STRIDE+x] - (int)saved_fdec[y*FDEC_STRIDE+x] );
            if( ad > max_abs ) max_abs = ad;
        }
    int cand_bits = mobi_act24_scratch_bits( h, 1 );
    int bits_saved = cur_bits - cand_bits;

    int pixel_exact = ( max_abs == 0 );
    const char *classification; const char *reason = "";
    if( pixel_exact && bits_saved > 0 )
        classification = "EXACT_WIN";
    else if( bits_saved > 0 && cand_sse <= cur_sse )
        classification = "STRICT_DOMINANCE";
    else if( bits_saved >= 0 && cand_sse < cur_sse )
        classification = "QUALITY_WIN";
    else if( bits_saved > 0 && cand_sse > cur_sse )
    {
        /* NEAR_LOSSLESS bound scaled from ACT22.9's <=32.0-per-16-pixel-block
         * to this whole 256-pixel MB: 2.0 SSE units/pixel * 256 = 512.0. */
        if( (cand_sse - cur_sse) <= 512.0 )
            classification = "NEAR_LOSSLESS";
        else { classification = "REJECT"; reason = "DISTORTION_TOO_LARGE"; }
    }
    else { classification = "REJECT"; reason = (bits_saved <= 0) ? "NO_BIT_SAVING" : "OTHER"; }

    if( sim_fp )
        fprintf( sim_fp, "%d,%d,%d,%d,%d,%d,%d,%.1f,%.1f,%d,%s,%s\n",
                 h->fdec->i_frame, h->mb.i_mb_x, h->mb.i_mb_y, forced_mode,
                 cur_bits, cand_bits, bits_saved, cur_sse, cand_sse, max_abs,
                 classification, reason );

    int activate_this = do_activate &&
        ( !strcmp(classification,"EXACT_WIN") || !strcmp(classification,"STRICT_DOMINANCE") || !strcmp(classification,"QUALITY_WIN") ) &&
        cand_bits < cur_bits;

    if( !activate_this )
    {
        for( int y = 0; y < 16; y++ )
            memcpy( &p_fdec[y*FDEC_STRIDE], &saved_fdec[y*FDEC_STRIDE], 16*sizeof(pixel) );
        memcpy( h->dct.luma4x4, saved_luma4x4, sizeof(dctcoef)*16*16 );
        for( int i = 0; i < 16; i++ )
            h->mb.cache.non_zero_count[x264_scan8[i]] = saved_nnz[i];
        h->mb.i_cbp_luma = saved_cbp_luma;
        return 0;
    }
    return 1;
}
#endif /* !RDO_SKIP_BS */

static void encode_i_block(x264_t *h)
{
	bs_t *s = &h->out.bs;
	const int i_mb_type = h->mb.i_type;
	const int i_mb_pos_start = bs_pos(s);
#if !RDO_SKIP_BS
	if (A2_CACHED_GETENV("MOBI_MBDBG"))
		fprintf(stderr, "MBSTART %d %d %d\n", h->mb.i_mb_x*16, h->mb.i_mb_y*16, i_mb_pos_start);
#endif

	int di = i_mb_type == I_8x8 ? 4 : 1;

	/* Mobiclip chroma plane order depends on moflex.  The decoder processes the
	 * two chroma planes as plane (1 + !moflex) then (2 - !moflex), i.e. U,V when
	 * moflex=1 and V,U when moflex=0.  x264 stores U in dct.luma8x8[4] (chroma
	 * idx 0) and V in dct.luma8x8[8] (chroma idx 1).  cf/cs are the chroma idx
	 * to emit first/second so both the has-coeff flag bits and the coefficient
	 * blocks match the decoder's read order. */
	int cf = h->param.b_moflex ? 0 : 1; /* chroma idx written first  */
	int cs = h->param.b_moflex ? 1 : 0; /* chroma idx written second */

	/* Default: per-block prediction mode encoding.  The equalPredict
	 * shortcut (single 3-bit mode for whole MB) used to be a permanent
	 * FALSE stub because x264's OWN stock 8x8 intra reconstruction differs
	 * from the decoder's per-4x4 boundary behaviour -- but ACT24 Piece 1's
	 * mobi_act24_intrafull_eval() sidesteps that entirely by reusing the
	 * already-correct per-4x4 MobiClip reconstruction (x264_mb_encode_i4x4)
	 * with a forced shared mode, so it's safe to make this a real decision
	 * now. Real (non-scratch) calls only: mobi_act24_force_equal_predict is
	 * set by mobi_act24_scratch_bits() while it measures candidate bits via
	 * a recursive scratch call to this same function, and takes priority so
	 * that inner call never re-enters the evaluator. */
	BOOL equalPredict = FALSE;
#if !RDO_SKIP_BS
	if( mobi_act24_force_equal_predict >= 0 )
		equalPredict = mobi_act24_force_equal_predict;
	else if( h->sh.i_type != SLICE_TYPE_I )
	{
		int sim_on = ( getenv("MOBI_ACT24_INTRAFULL_SIM") && atoi(getenv("MOBI_ACT24_INTRAFULL_SIM")) );
		int act_on = mobi_act24_intrafull_activate_enabled();
		if( sim_on || act_on )
			equalPredict = mobi_act24_intrafull_eval( h, sim_on ? mobi_act24_intrafull_sim_fp() : NULL, act_on );
	}
#endif
	int equalMode = mobi_intra_to_h264[(h->mb.cache.intra4x4_pred_mode[x264_scan8[0]])+1];
	if (h->sh.i_type == SLICE_TYPE_I)
	{
		bs_write1(s, !equalPredict);
		h->stat.frame.i_mv_bits++;
	}
	else
	{
		/* Intra MB inside a P-frame: the decoder selects intra via the
		 * mv_vlc[moflex][0] symbol.  idx==6 (INTRA_FULL) -> predict=0
		 * (equalPredict, single mode); idx==7 (INTRA_SUB) -> predict=1
		 * (per-block modes).  Emit the canonical VLC code, not a guess. */
		int _intra_mode = equalPredict ? MOBI_P_PART_INTRA_FULL : MOBI_P_PART_INTRA_SUB;
		int _bp = bs_pos(s);
		mobi_encode_p_partition_mode(s, 16, 16, _intra_mode);
		h->stat.frame.i_mv_bits += bs_pos(s) - _bp;
	}

	//which blocks are actually coded
#if !RDO_SKIP_BS
	int tmp = bs_pos(s);
#endif
	uint8_t mask =
		(!!h->mb.cache.non_zero_count[x264_scan8[0 * 4]]) |
		((!!h->mb.cache.non_zero_count[x264_scan8[1 * 4]]) << 1) |
		((!!h->mb.cache.non_zero_count[x264_scan8[2 * 4]]) << 2) |
		((!!h->mb.cache.non_zero_count[x264_scan8[3 * 4]]) << 3);
	bs_write_ue(s, block_mask_to_golomb_table[(!!h->mb.cache.non_zero_count[x264_scan8[16 + cs * 16]] << 5) | (!!h->mb.cache.non_zero_count[x264_scan8[16 + cf * 16]] << 4) | (i_mb_type == I_8x8 ? mask : 0xF)]);
#if !RDO_SKIP_BS
	h->stat.frame.i_tex_bits += bs_pos(s) - tmp;
	if (A2_CACHED_GETENV("MOBI_MBDBG")) {
		int _cb = (!!h->mb.cache.non_zero_count[x264_scan8[16 + cs * 16]] << 5) | (!!h->mb.cache.non_zero_count[x264_scan8[16 + cf * 16]] << 4) | (i_mb_type == I_8x8 ? mask : 0xF);
		fprintf(stderr, "MB %d %d type=%d t8=%d mask=%d eq=%d di=%d cbits=%d golomb=%d\n",
			h->mb.i_mb_x*16, h->mb.i_mb_y*16, i_mb_type, h->mb.b_transform_8x8, mask, equalPredict, di, _cb, block_mask_to_golomb_table[_cb]);
	}
#endif

	if (equalPredict)
	{
		int mobi_equal = h264_to_mobiclip_mode[equalMode < 9 ? equalMode : 8];
		bs_write(s, 3, mobi_equal);
		h->stat.frame.i_mv_bits += 3;
	}

	if (h->mb.b_transform_8x8)
	{
		for (int i8 = 0; i8 < 4; i8++)
		{
#if !RDO_SKIP_BS
			tmp = bs_pos(s);
#endif
			if (h->mb.cache.non_zero_count[x264_scan8[i8 * 4]])
				bs_write1(s, 1);//don't subdivide into 4x4

			if (!equalPredict)
			{
				/* Use Mobiclip prediction state machine with H.264->Mobiclip remapping. */
				int i_mode_h264 = mobi_intra_to_h264[(h->mb.cache.intra4x4_pred_mode[x264_scan8[i8 * 4]])+1];
				int mobi_mode = h264_to_mobiclip_mode[i_mode_h264 < 9 ? i_mode_h264 : 8];
				int bx = h->mb.i_mb_x * 16 + (i8 & 1) * 8;
				int by = h->mb.i_mb_y * 16 + (i8 >> 1) * 8;
				mobi_write_pred_mode(h, s, bx, by, mobi_mode);
			}

			//todo: write plane param here when implemented and mode == 2
#if !RDO_SKIP_BS
			h->stat.frame.i_mv_bits += bs_pos(s) - tmp;
#endif
			if (h->mb.cache.non_zero_count[x264_scan8[i8 * 4]])
			{
#if !RDO_SKIP_BS
				tmp = bs_pos(s);
#endif			
				//if (h->mb.cache.non_zero_count[x264_scan8[i8 * 4]])
				//{
					h->mb.cache.non_zero_count[x264_scan8[i8 * 4]] = encode_dct(h, h->dct.luma8x8[i8], 64, h->sh.i_type == SLICE_TYPE_I ? 1 : 0);
				//}
				/*else
				{
					dctcoef zero[64] = { 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 };
					encode_dct(h, zero, 64, h->sh.i_type == SLICE_TYPE_I ? 1 : 0);
				}*/

#if !RDO_SKIP_BS
				h->stat.frame.i_tex_bits += bs_pos(s) - tmp;
#endif
			}
		}
	}
	else
	{
		for (int i8 = 0; i8 < 4; i8++)
		{
#if !RDO_SKIP_BS
			tmp = bs_pos(s);
#endif
			uint8_t mask =
				(!!h->mb.cache.non_zero_count[x264_scan8[i8 * 4 + 0]]) |
				((!!h->mb.cache.non_zero_count[x264_scan8[i8 * 4 + 1]]) << 1) |
				((!!h->mb.cache.non_zero_count[x264_scan8[i8 * 4 + 2]]) << 2) |
				((!!h->mb.cache.non_zero_count[x264_scan8[i8 * 4 + 3]]) << 3);
			bs_write_ue(s, subblock_mask_to_golomb_table[mask]);
#if !RDO_SKIP_BS
			h->stat.frame.i_tex_bits += bs_pos(s) - tmp;
#endif
			/* The decoder's process_block() reads the 4x4 coeff golomb (always >0
			 * here, since subblock_mask_to_golomb_table[] never maps to 0) and then
			 * unconditionally reads a 4x4 prediction mode for EACH of the 4 sub-blocks.
			 * So we must always emit 4 per-4x4 modes — even when mask==0 (no coeffs).
			 * The mask==0 single-8x8-mode special case desynced the stream (FAIL 457). */
			for (int i4 = 0; i4 < 4; i4++)
			{
#if !RDO_SKIP_BS
				tmp = bs_pos(s);
#endif
				if (!equalPredict)
				{
					/* Use Mobiclip prediction state machine with H.264->Mobiclip remapping. */
					int i_mode_h264 = mobi_intra_to_h264[(h->mb.cache.intra4x4_pred_mode[x264_scan8[i8 * 4 + i4]])+1];
					int mobi_mode = h264_to_mobiclip_mode[i_mode_h264 < 9 ? i_mode_h264 : 8];
					int bx = h->mb.i_mb_x * 16 + (i8 & 1) * 8 + (i4 & 1) * 4;
					int by = h->mb.i_mb_y * 16 + (i8 >> 1) * 8 + (i4 >> 1) * 4;
					mobi_write_pred_mode_4x4(h, s, bx, by, mobi_mode);
				}

#if !RDO_SKIP_BS
				h->stat.frame.i_mv_bits += bs_pos(s) - tmp;
#endif

				//todo: write plane param here when implemented and mode == 2
				if (h->mb.cache.non_zero_count[x264_scan8[i8 * 4 + i4]])
				{
#if !RDO_SKIP_BS
					tmp = bs_pos(s);
#endif
					h->mb.cache.non_zero_count[x264_scan8[i8 * 4 + i4]] = encode_dct(h, h->dct.luma4x4[i8 * 4 + i4], 16, h->sh.i_type == SLICE_TYPE_I ? 1 : 0);
#if !RDO_SKIP_BS
					h->stat.frame.i_tex_bits += bs_pos(s) - tmp;
#endif
				}
			}
		}
	}

	//chroma prediction mode
#if !RDO_SKIP_BS
	tmp = bs_pos(s);
#endif
	bs_write(s, 3, mobi_chroma_pred_mode_fix[h->mb.i_chroma_pred_mode]);
	//todo: write plane params here when implemented and mode == 2
#if !RDO_SKIP_BS
	h->stat.frame.i_mv_bits += bs_pos(s) - tmp;
#endif		
	for (int k = 0; k < 2; k++)
	{
		int i = k == 0 ? cf : cs;
		if (h->mb.cache.non_zero_count[x264_scan8[16 + i * 16]])
		{
			bs_write1(s, 1);//don't subdivide into 4x4
			h->stat.frame.i_mv_bits++;
#if !RDO_SKIP_BS
				tmp = bs_pos(s);
#endif
				h->mb.cache.non_zero_count[x264_scan8[16 + i * 16]] = encode_dct(h, h->dct.luma8x8[4 + 4 * i], 64, h->sh.i_type == SLICE_TYPE_I ? 1 : 0);
#if !RDO_SKIP_BS
				h->stat.frame.i_tex_bits += bs_pos(s) - tmp;
#endif
		}
	}
}

/* Mobiclip motion-partition VLC encode tables, generated as the exact inverse
 * of the decoder's mv_vlc[moflex][tidx] (built by ff_init_vlc_from_lengths from
 * mobiclip.c's mv_bits/mv_syms).  Indexed [moflex][tidx][mode] where
 *   tidx = mobi_size_index(height) * 4 + mobi_size_index(width)
 * and mode is a MOBI_P_PART_* symbol (0..9).  A length of 0 means that symbol
 * is not present in that VLC (e.g. INTRA modes only exist for some sizes). */
static const uint8_t mobi_mv_enc_len[2][16][10] =
{
	{
		{2, 2, 4, 5, 5, 5, 5, 4, 3, 3},
		{2, 2, 3, 4, 4, 4, 0, 0, 4, 3},
		{2, 2, 3, 3, 4, 4, 0, 0, 4, 4},
		{3, 1, 3, 3, 4, 5, 0, 0, 5, 0},
		{2, 2, 3, 4, 4, 4, 0, 0, 3, 4},
		{2, 2, 3, 3, 4, 4, 0, 0, 4, 4},
		{2, 2, 3, 3, 4, 4, 0, 0, 4, 4},
		{2, 2, 2, 3, 4, 5, 0, 0, 5, 0},
		{2, 2, 3, 3, 4, 4, 0, 0, 4, 4},
		{3, 2, 2, 3, 4, 4, 0, 0, 4, 4},
		{2, 2, 3, 3, 3, 4, 0, 0, 5, 5},
		{2, 2, 3, 3, 3, 4, 0, 0, 4, 0},
		{3, 1, 3, 4, 4, 4, 0, 0, 0, 4},
		{3, 2, 2, 3, 3, 4, 0, 0, 0, 4},
		{2, 2, 3, 3, 3, 4, 0, 0, 0, 4},
		{2, 2, 3, 3, 3, 3, 0, 0, 0, 0},
	},
	{
		{1, 3, 4, 5, 6, 6, 5, 5, 3, 4},
		{3, 2, 3, 4, 5, 5, 0, 0, 3, 2},
		{2, 2, 3, 4, 4, 4, 0, 0, 4, 3},
		{3, 1, 3, 4, 4, 4, 0, 0, 4, 0},
		{3, 2, 3, 4, 5, 5, 0, 0, 2, 3},
		{3, 2, 3, 3, 4, 4, 0, 0, 3, 3},
		{3, 1, 3, 4, 5, 5, 0, 0, 4, 4},
		{3, 1, 3, 4, 4, 4, 0, 0, 4, 0},
		{2, 2, 3, 4, 4, 4, 0, 0, 3, 4},
		{3, 1, 3, 4, 5, 5, 0, 0, 4, 4},
		{2, 2, 3, 3, 4, 4, 0, 0, 4, 4},
		{2, 2, 3, 3, 3, 4, 0, 0, 4, 0},
		{3, 1, 3, 4, 4, 4, 0, 0, 0, 4},
		{3, 1, 3, 4, 4, 4, 0, 0, 0, 4},
		{2, 2, 3, 3, 4, 3, 0, 0, 0, 4},
		{2, 2, 3, 3, 3, 3, 0, 0, 0, 0},
	},
};

static const uint8_t mobi_mv_enc_code[2][16][10] =
{
	{
		{3, 0, 9, 17, 16, 22, 23, 10, 2, 3},
		{0, 3, 4, 10, 7, 6, 0, 0, 11, 2},
		{1, 3, 5, 0, 8, 3, 0, 0, 9, 2},
		{7, 0, 6, 4, 10, 23, 0, 0, 22, 0},
		{0, 3, 4, 10, 5, 4, 0, 0, 3, 11},
		{0, 3, 5, 2, 8, 6, 0, 0, 9, 7},
		{0, 3, 5, 2, 9, 7, 0, 0, 8, 6},
		{0, 3, 1, 4, 10, 23, 0, 0, 22, 0},
		{0, 3, 4, 2, 7, 10, 0, 0, 6, 11},
		{5, 3, 0, 3, 9, 8, 0, 0, 4, 5},
		{0, 3, 5, 3, 2, 9, 0, 0, 16, 17},
		{0, 3, 5, 4, 2, 7, 0, 0, 6, 0},
		{6, 0, 5, 15, 9, 14, 0, 0, 0, 8},
		{5, 3, 0, 4, 2, 7, 0, 0, 0, 6},
		{0, 3, 5, 4, 2, 7, 0, 0, 0, 6},
		{2, 1, 7, 6, 1, 0, 0, 0, 0, 0},
	},
	{
		{1, 2, 2, 6, 27, 26, 7, 12, 0, 7},
		{7, 2, 2, 6, 15, 14, 0, 0, 6, 0},
		{0, 3, 3, 10, 5, 4, 0, 0, 11, 4},
		{7, 0, 5, 13, 9, 8, 0, 0, 12, 0},
		{5, 3, 0, 8, 19, 18, 0, 0, 1, 1},
		{5, 3, 2, 0, 3, 2, 0, 0, 4, 3},
		{5, 0, 4, 14, 31, 30, 0, 0, 13, 12},
		{6, 0, 5, 15, 14, 9, 0, 0, 8, 0},
		{0, 3, 3, 10, 5, 4, 0, 0, 4, 11},
		{5, 0, 4, 14, 31, 30, 0, 0, 13, 12},
		{0, 3, 5, 2, 9, 8, 0, 0, 7, 6},
		{0, 3, 5, 3, 2, 9, 0, 0, 8, 0},
		{6, 0, 5, 15, 9, 8, 0, 0, 0, 14},
		{6, 0, 5, 15, 14, 9, 0, 0, 0, 8},
		{0, 3, 5, 3, 9, 2, 0, 0, 0, 8},
		{0, 3, 5, 4, 2, 3, 0, 0, 0, 0},
	},
};

static void mobi_encode_p_partition(x264_t *h, int idx, int width, int height, int px, int py, int* lastMv)
{
	int idx44 = ((idx >> 1) & 1) | (((idx >> 4) & 1) << 1);
	bs_t *s = &h->out.bs;
	if (width == 16 && height == 16 && (h->mb.i_partition == D_16x8 || h->mb.i_type == P_8x8))
	{
		mobi_encode_p_partition_mode(s, 16, 16, MOBI_P_PART_H_SPLIT);
		mobi_encode_p_partition(h, 0, 16, 8, px, py, NULL);
		mobi_encode_p_partition(h, 2 * 8, 16, 8, px, py, lastMv);
	}
	else if (width == 16 && height == 16 && h->mb.i_partition == D_8x16)
	{
		mobi_encode_p_partition_mode(s, 16, 16, MOBI_P_PART_V_SPLIT);
		mobi_encode_p_partition(h, 0, 8, 16, px, py, NULL);
		mobi_encode_p_partition(h, 2, 8, 16, px, py, lastMv);
	}
	else if (width == 16 && height == 8 && h->mb.i_partition == D_8x8)
	{
		mobi_encode_p_partition_mode(s, 16, 8, MOBI_P_PART_V_SPLIT);
		mobi_encode_p_partition(h, idx, 8, 8, px, py, NULL);
		mobi_encode_p_partition(h, idx + 2, 8, 8, px, py, lastMv);
	}
	else if (width == 8 && height == 8 && (h->mb.i_sub_partition[idx44] == D_L0_8x4 || h->mb.i_sub_partition[idx44] == D_L0_4x4))
	{
		mobi_encode_p_partition_mode(s, 8, 8, MOBI_P_PART_H_SPLIT);
		mobi_encode_p_partition(h, idx, 8, 4, px, py, NULL);
		mobi_encode_p_partition(h, idx + 8, 8, 4, px, py, lastMv);
	}
	else if (width == 8 && height == 8 && h->mb.i_sub_partition[idx44] == D_L0_4x8)
	{
		mobi_encode_p_partition_mode(s, 8, 8, MOBI_P_PART_V_SPLIT);
		mobi_encode_p_partition(h, idx, 4, 8, px, py, NULL);
		mobi_encode_p_partition(h, idx + 1, 4, 8, px, py, lastMv);
	}
	else if (width == 8 && height == 4 && h->mb.i_sub_partition[idx44] == D_L0_4x4)
	{
		mobi_encode_p_partition_mode(s, 8, 4, MOBI_P_PART_V_SPLIT);
		mobi_encode_p_partition(h, idx, 4, 4, px, py, NULL);
		mobi_encode_p_partition(h, idx + 1, 4, 4, px, py, lastMv);
	}
	else
	{
		int ref = h->mb.cache.ref[0][x264_scan8[0] + idx];
		int mvx = h->mb.cache.mv[0][x264_scan8[0] + idx][0] >> 1;
		int mvy = h->mb.cache.mv[0][x264_scan8[0] + idx][1] >> 1;
		int dx = mvx - px;
		int dy = mvy - py;
		if (ref == 0 && dx == 0 && dy == 0)
			mobi_encode_p_partition_mode(s, width, height, MOBI_P_PART_FRAME0_DELTA0);
		else
		{
			switch (ref)
			{
				case 0:
					mobi_encode_p_partition_mode(s, width, height, MOBI_P_PART_FRAME0);
					break;
				case 1:
					mobi_encode_p_partition_mode(s, width, height, MOBI_P_PART_FRAME1);
					break;
				case 2:
					mobi_encode_p_partition_mode(s, width, height, MOBI_P_PART_FRAME2);
					break;
				case 3:
					mobi_encode_p_partition_mode(s, width, height, MOBI_P_PART_FRAME3);
					break;
				case 4:
					mobi_encode_p_partition_mode(s, width, height, MOBI_P_PART_FRAME4);
					break;
				default:
					printf("Invalid reference (%d)!", ref);
					while (1);
					break;
			}
			bs_write_se(s, dx);
			bs_write_se(s, dy);
		}
		if (lastMv)
		{
			lastMv[0] = mvx;
			lastMv[1] = mvy;
		}
	}
}

static const uint8_t REV_byte_116160[] =
{
	0, 3, 5, 7, 2, 8, 16, 11, 4, 15, 9, 13, 6, 10, 12, 1,
	17, 28, 27, 24, 29, 30, 33, 20, 25, 34, 26, 22, 23, 21,
	19, 14, 31, 42, 44, 46, 43, 51, 61, 49, 45, 60, 55, 53,
	47, 50, 54, 32, 48, 56, 59, 40, 57, 41, 63, 35, 58, 62,
	52, 38, 39, 36, 37, 18
};

static const uint8_t REV_byte_1165C4[] =
{
	0, 2, 4, 6, 1, 7, 15, 10, 3, 14, 8, 13, 5, 11, 12, 9,
};

#if !RDO_SKIP_BS
/* ============================================================================
 * ACT24 Piece 3: P_L0 split candidate simulate/activate.
 *
 * Unlike P_INTRA_FULL (a wholly new candidate that never existed before),
 * this re-scores a decision x264's OWN stock partition search already made
 * (H_SPLIT/V_SPLIT via i_partition/i_sub_partition, now able to run at all
 * only because of the ACT24 Piece 2 chroma-MC-granularity bugfix ported
 * into this worktree below). That search picks between whole-MB and split
 * using x264's SATD+lambda cost estimate, not real MobiClip bits -- exactly
 * the kind of stock cost-model bias ACT22.1B already found once. So this
 * does not trust that choice: for every MB the search left split, it
 * re-scores the REAL alternative (force D_16x16, single MV = block 0's
 * already-computed MV/ref, real MobiClip bits via the scratch-writer, real
 * decoder-domain distortion) against what's actually there, and only
 * activates where that real scoring shows a genuine win by the same
 * EXACT_WIN/STRICT_DOMINANCE/QUALITY_WIN gate as every other phase.
 *
 * Scope: P_L0/P_8x8 only (P_SKIP and intra excluded), b_transform_8x8
 * excluded (same boundary every ACT2x phase respects), luma-only for
 * classification (matching every prior phase's scope discipline) --
 * chroma pixels ARE touched transiently by mobi_motion_compensate() during
 * the trial (it recomputes both planes together) but are restored
 * unconditionally unless the candidate is actually activated, in which
 * case chroma residual is properly re-encoded via x264_mb_encode_chroma()
 * for the new prediction rather than left stale.
 *
 * Env: MOBI_ACT24_PLSPLIT_SIM[_OUT], MOBI_ACT24_PLSPLIT_ENABLE.
 * ============================================================================ */

static void encode_p_block( x264_t *h ); /* forward decl: eval calls the real writer to measure bits for both the current (split) and candidate (forced D_16x16) states */

static FILE *mobi_act24_plsplit_sim_fp( void )
{
    static int enabled = -1;
    static FILE *fp = NULL;
    if( enabled < 0 )
    {
        const char *prefix = getenv( "MOBI_ACT24_PLSPLIT_SIM" );
        enabled = ( prefix && atoi(prefix) ) ? 1 : 0;
        if( enabled )
        {
            char path[4096];
            const char *outpfx = getenv( "MOBI_ACT24_PLSPLIT_SIM_OUT" );
            snprintf( path, sizeof(path), "%s_plsplit.csv", outpfx ? outpfx : "mobi_act24" );
            fp = fopen( path, "w" );
            if( fp )
                fprintf( fp, "frame_index,mb_x,mb_y,orig_type,orig_partition,cur_bits,cand_bits,bits_saved,cur_sse,cand_sse,max_abs_pixel_diff,classification,rejection_reason\n" );
        }
        enabled = fp ? 1 : 0;
    }
    return enabled ? fp : NULL;
}

static int mobi_act24_plsplit_activate_enabled( void )
{
    static int enabled = -1;
    if( enabled < 0 )
    {
        const char *v = getenv( "MOBI_ACT24_PLSPLIT_ENABLE" );
        enabled = ( v && atoi(v) ) ? 1 : 0;
    }
    return enabled;
}

static int mobi_act24_plsplit_scratch_bits( x264_t *h )
{
    bs_t save_bs = h->out.bs;
    uint8_t scratch[4096];
    bs_init( &h->out.bs, scratch, sizeof(scratch) );
    encode_p_block( h );
    int bits = bs_pos( &h->out.bs );
    h->out.bs = save_bs;
    return bits;
}

static ALWAYS_INLINE void mobi_act24_interp_block( pixel *dst, int ds, pixel *src, int ss, int w, int hgt, int method )
{
    /* Self-contained copy of macroblock.c's (private/static) mobi_interp_block
     * -- xs is always 1 for every caller here so that parameter is dropped,
     * formula otherwise byte-for-byte identical. */
    for( int y = 0; y < hgt; y++ )
    {
        for( int x = 0; x < w; x++ )
        {
            pixel *s = src + x;
            int v;
            switch( method )
            {
            default:
            case 0: v = s[0]; break;
            case 1: v = (s[0] >> 1) + (s[1] >> 1); break;
            case 2: v = (s[0] >> 1) + (s[ss] >> 1); break;
            case 3: v = (((s[0] >> 1) + (s[1] >> 1)) >> 1) +
                        (((s[ss] >> 1) + (s[1 + ss] >> 1)) >> 1); break;
            }
            dst[x] = v;
        }
        dst += ds;
        src += ss;
    }
}

/* Self-contained copy of the relevant part of macroblock.c's (private,
 * static) mobi_motion_compensate(), specialized for this evaluator's one
 * use: motion-compensate the WHOLE MB (luma 16x16 + both chroma planes,
 * post ACT24 Piece 2's chroma-granularity fix applied at the caller's
 * level -- every sub-block uses the SAME mv/ref here) using a single given
 * mv/ref, exactly matching what a real D_16x16 P_L0 MB's motion
 * compensation produces. mv is assumed already MB-bounds-clamped (true for
 * the caller, which copies an already-clamped value straight from the real
 * encode's own cache.mv[]). Duplicated rather than called across
 * translation units deliberately: mobi_motion_compensate is static to
 * macroblock.c, and every other MobiClip-specific primitive this
 * investigation has added to cavlc.c (mobi_act22_9_dequant_recon and
 * friends) is likewise self-contained in this file, avoiding a cross-file
 * symbol that would collide between the -8 and -10 bit-depth compilation
 * units this codebase links into one archive. */
static void mobi_act24_plsplit_mc_forced( x264_t *h, int mvx, int mvy, int iref )
{
    if( iref < 0 ) iref = 0;
    int sy = h->mb.pic.i_stride[0];
    int sc = h->mb.pic.i_stride[1];
    int method = (mvx & 1) | ((mvy & 1) << 1);
    pixel *ref = h->mb.pic.p_fref[0][iref][0];
    pixel *src = ref + (mvy >> 1) * sy + (mvx >> 1);
    mobi_act24_interp_block( h->mb.pic.p_fdec[0], FDEC_STRIDE, src, sy, 16, 16, method );

    int cmvx = (mvx >> 1) >> 1;
    int cmvy = (mvy >> 1) >> 1;
    int cmethod = (cmvx & 1) | ((cmvy & 1) << 1);
    int srcoff = (cmvy >> 1) * sc + (cmvx >> 1);
    for( int ch = 0; ch < 2; ch++ )
    {
        pixel *refc = h->mb.pic.p_fref[0][iref][4 + ch*4];
        mobi_act24_interp_block( h->mb.pic.p_fdec[1 + ch], FDEC_STRIDE, refc + srcoff, sc, 8, 8, cmethod );
    }
}

static void mobi_act24_plsplit_eval( x264_t *h, FILE *sim_fp, int do_activate )
{
    if( h->mb.i_type == P_SKIP ) return;
    if( h->mb.i_type == P_L0 && h->mb.i_partition == D_16x16 ) return;
    if( h->mb.i_type != P_L0 && h->mb.i_type != P_8x8 ) return;
    if( h->mb.b_transform_8x8 ) return;

    pixel *p_fdec = h->mb.pic.p_fdec[0];
    pixel *p_fenc = h->mb.pic.p_fenc[0];

    pixel saved_fdec_y[16*FDEC_STRIDE];
    for( int y = 0; y < 16; y++ )
        memcpy( &saved_fdec_y[y*FDEC_STRIDE], &p_fdec[y*FDEC_STRIDE], 16*sizeof(pixel) );
    pixel saved_fdec_c[2][8*FDEC_STRIDE];
    for( int ch = 0; ch < 2; ch++ )
        for( int y = 0; y < 8; y++ )
            memcpy( &saved_fdec_c[ch][y*FDEC_STRIDE], &h->mb.pic.p_fdec[1+ch][y*FDEC_STRIDE], 8*sizeof(pixel) );
    __typeof__(h->dct) saved_dct = h->dct;
    __typeof__(h->mb.cache) saved_cache = h->mb.cache;
    int saved_type = h->mb.i_type;
    int saved_partition = h->mb.i_partition;
    int saved_sub[4]; for( int i = 0; i < 4; i++ ) saved_sub[i] = h->mb.i_sub_partition[i];
    int saved_cbp_luma = h->mb.i_cbp_luma;
    int saved_cbp_chroma = h->mb.i_cbp_chroma;
    /* mobi_motion_x/y[mb_col+2] is the decoder-matching "last sub-block MV"
     * context encode_p_block() writes as a side effect on EVERY call (real
     * or scratch) for MV-predictor threading into the NEXT MB (mpx/mpy at
     * the top of encode_p_block). Both scratch bit-measurement calls below
     * go through the real encode_p_block(), so BOTH overwrite this global,
     * per-column array -- the second (candidate) call's write must not be
     * allowed to leak into the real predictor context if the candidate is
     * rejected. Must be saved/restored explicitly; it is not part of
     * h->mb.cache/h->dct/h->mb.pic and was missed on the first pass (see
     * evidence\act24_plsplit_24f_20260825_140000 for the decoder-rejection
     * failure this caused and the fix confirmation). */
    int mb_col = h->mb.i_mb_x;
    int saved_motion_x = h->mobi_motion_x[mb_col + 2];
    int saved_motion_y = h->mobi_motion_y[mb_col + 2];

    double cur_sse = 0;
    for( int y = 0; y < 16; y++ )
        for( int x = 0; x < 16; x++ )
        {
            int d = (int)saved_fdec_y[y*FDEC_STRIDE+x] - (int)p_fenc[y*FENC_STRIDE+x];
            cur_sse += (double)(d*d);
        }
    int cur_bits = mobi_act24_plsplit_scratch_bits( h );

    /* Candidate: force whole-MB single MV/ref = block 0's already-computed
     * value (same "block 0 is representative" convention Piece 1 used for
     * P_INTRA_FULL's forced mode), i_type/i_partition forced to plain P_L0
     * D_16x16 so mobi_encode_p_partition's leaf (no-split) branch fires and
     * encode_p_block's residual-mask logic reads the freshly re-encoded
     * single-block state below. */
    int cand_ref = h->mb.cache.ref[0][x264_scan8[0]];
    int16_t cand_mv[2] = { h->mb.cache.mv[0][x264_scan8[0]][0], h->mb.cache.mv[0][x264_scan8[0]][1] };
    for( int i = 0; i < 16; i++ )
    {
        int i8 = x264_scan8[0] + (i&3) + (i>>2)*8;
        h->mb.cache.mv[0][i8][0] = cand_mv[0];
        h->mb.cache.mv[0][i8][1] = cand_mv[1];
        h->mb.cache.ref[0][i8]   = cand_ref;
    }
    h->mb.i_type = P_L0;
    h->mb.i_partition = D_16x16;

    mobi_act24_plsplit_mc_forced( h, cand_mv[0], cand_mv[1], cand_ref ); /* recomputes luma AND chroma prediction for the forced single MV; chroma is restored below regardless of the outcome unless activated */

    for( int i = 0; i < 16; i++ )
        x264_mb_encode_i4x4( h, 0, i, h->mb.i_qp, 0, 0 ); /* residual only (b_predict=0), same reuse as the real inter-luma path (macroblock.c ~line 1178) */
    {
        int cbp = 0;
        for( int g = 0; g < 4; g++ )
        {
            int any = 0;
            for( int k = 0; k < 4; k++ )
                if( h->mb.cache.non_zero_count[x264_scan8[g*4+k]] ) any = 1;
            if( any ) cbp |= 1 << g;
        }
        h->mb.i_cbp_luma = cbp;
    }

    double cand_sse = 0; int max_abs = 0;
    for( int y = 0; y < 16; y++ )
        for( int x = 0; x < 16; x++ )
        {
            int d = (int)p_fdec[y*FDEC_STRIDE+x] - (int)p_fenc[y*FENC_STRIDE+x];
            cand_sse += (double)(d*d);
            int ad = abs( (int)p_fdec[y*FDEC_STRIDE+x] - (int)saved_fdec_y[y*FDEC_STRIDE+x] );
            if( ad > max_abs ) max_abs = ad;
        }
    int cand_bits = mobi_act24_plsplit_scratch_bits( h );
    int bits_saved = cur_bits - cand_bits;

    int pixel_exact = ( max_abs == 0 );
    const char *classification; const char *reason = "";
    if( pixel_exact && bits_saved > 0 ) classification = "EXACT_WIN";
    else if( bits_saved > 0 && cand_sse <= cur_sse ) classification = "STRICT_DOMINANCE";
    else if( bits_saved >= 0 && cand_sse < cur_sse ) classification = "QUALITY_WIN";
    else if( bits_saved > 0 && cand_sse > cur_sse )
    {
        if( (cand_sse - cur_sse) <= 512.0 ) classification = "NEAR_LOSSLESS";
        else { classification = "REJECT"; reason = "DISTORTION_TOO_LARGE"; }
    }
    else { classification = "REJECT"; reason = (bits_saved <= 0) ? "NO_BIT_SAVING" : "OTHER"; }

    if( sim_fp )
        fprintf( sim_fp, "%d,%d,%d,%d,%d,%d,%d,%d,%.1f,%.1f,%d,%s,%s\n",
                 h->fdec->i_frame, h->mb.i_mb_x, h->mb.i_mb_y, saved_type, saved_partition,
                 cur_bits, cand_bits, bits_saved, cur_sse, cand_sse, max_abs,
                 classification, reason );

    int activate_this = do_activate &&
        ( !strcmp(classification,"EXACT_WIN") || !strcmp(classification,"STRICT_DOMINANCE") || !strcmp(classification,"QUALITY_WIN") ) &&
        cand_bits < cur_bits;

    if( activate_this )
    {
        /* Commit: luma is already the winning (candidate) reconstruction.
         * Chroma prediction was updated by mobi_motion_compensate() above
         * but its residual/nnz/cbp still reflect the OLD (split) coding --
         * re-encode chroma for real against the new prediction rather than
         * leave it inconsistent. */
        x264_mb_encode_chroma( h, 1, h->mb.i_qp );
        return;
    }

    /* Reject: restore everything. */
    for( int y = 0; y < 16; y++ )
        memcpy( &p_fdec[y*FDEC_STRIDE], &saved_fdec_y[y*FDEC_STRIDE], 16*sizeof(pixel) );
    for( int ch = 0; ch < 2; ch++ )
        for( int y = 0; y < 8; y++ )
            memcpy( &h->mb.pic.p_fdec[1+ch][y*FDEC_STRIDE], &saved_fdec_c[ch][y*FDEC_STRIDE], 8*sizeof(pixel) );
    h->dct = saved_dct;
    h->mb.cache = saved_cache;
    h->mb.i_type = saved_type;
    h->mb.i_partition = saved_partition;
    for( int i = 0; i < 4; i++ ) h->mb.i_sub_partition[i] = saved_sub[i];
    h->mobi_motion_x[mb_col + 2] = saved_motion_x;
    h->mobi_motion_y[mb_col + 2] = saved_motion_y;
    h->mb.i_cbp_luma = saved_cbp_luma;
    h->mb.i_cbp_chroma = saved_cbp_chroma;
}

static void mobi_act24_plsplit_rdo( x264_t *h )
{
    int sim_on = ( getenv("MOBI_ACT24_PLSPLIT_SIM") && atoi(getenv("MOBI_ACT24_PLSPLIT_SIM")) );
    int act_on = mobi_act24_plsplit_activate_enabled();
    if( !sim_on && !act_on ) return;
    FILE *sim_fp = sim_on ? mobi_act24_plsplit_sim_fp() : NULL;
    mobi_act24_plsplit_eval( h, sim_fp, act_on );
}
#endif /* !RDO_SKIP_BS */

static void encode_p_block(x264_t *h)
{
	bs_t *s = &h->out.bs;
	/* Mobiclip MV predictor: the decoder uses mid_pred() of three entries of
	 * its motion[] array (left / above / above-right), the same predictor for
	 * every sub-block of the MB.  We mirror that array here.  The decoder
	 * resets motion[c+2] to 0 before decoding the MB (so intra MBs leave 0),
	 * then predict_motion() stores the final MV there. */
	int mb_col = h->mb.i_mb_x;
	int mpx = mobi_mid_pred(h->mobi_motion_x[mb_col + 1], h->mobi_motion_x[mb_col + 2], h->mobi_motion_x[mb_col + 3]);
	int mpy = mobi_mid_pred(h->mobi_motion_y[mb_col + 1], h->mobi_motion_y[mb_col + 2], h->mobi_motion_y[mb_col + 3]);
#if !RDO_SKIP_BS
	if (A2_CACHED_GETENV("MOBI_ENCDBG"))
		fprintf(stderr, "[ENC] MB(%d,%d) type=%d part=%d pred=(%d,%d) bitpos=%d\n",
			h->mb.i_mb_x * 16, h->mb.i_mb_y * 16, h->mb.i_type, h->mb.i_partition, mpx, mpy,
			bs_pos(&h->out.bs));
#endif

	if (IS_INTRA(h->mb.i_type))
	{
		encode_i_block(h);
#if !RDO_SKIP_BS
		/* Intra MB: decoder leaves motion[c+2] at the reset value 0. */
		h->mobi_motion_x[mb_col + 2] = 0;
		h->mobi_motion_y[mb_col + 2] = 0;
#endif
	}
	else if (h->mb.i_type == P_L0 || h->mb.i_type == P_8x8 || h->mb.i_type == P_SKIP)
	{
#if !RDO_SKIP_BS
		int tmp = bs_pos(s);
#endif
		int lastMv[2] = { mpx, mpy };
		mobi_encode_p_partition(h, 0, 16, 16, mpx, mpy, lastMv);
#if !RDO_SKIP_BS
		h->stat.frame.i_mv_bits += bs_pos(s) - tmp;
		/* Store the final (last sub-block) MV as the decoder does. */
		h->mobi_motion_x[mb_col + 2] = lastMv[0];
		h->mobi_motion_y[mb_col + 2] = lastMv[1];
#endif
		//which blocks are actually coded
#if !RDO_SKIP_BS
		tmp = bs_pos(s);
#endif
		BOOL use8x8 = x264_mb_transform_8x8_allowed(h) && h->mb.b_transform_8x8;
		uint8_t mask =
			(!!h->mb.cache.non_zero_count[x264_scan8[0 * 4]]) |
			((!!h->mb.cache.non_zero_count[x264_scan8[1 * 4]]) << 1) |
			((!!h->mb.cache.non_zero_count[x264_scan8[2 * 4]]) << 2) |
			((!!h->mb.cache.non_zero_count[x264_scan8[3 * 4]]) << 3);
		uint8_t masks[] =
		{
			(!!h->mb.cache.non_zero_count[x264_scan8[0 * 4 + 0]]) |
			((!!h->mb.cache.non_zero_count[x264_scan8[0 * 4 + 1]]) << 1) |
			((!!h->mb.cache.non_zero_count[x264_scan8[0 * 4 + 2]]) << 2) |
			((!!h->mb.cache.non_zero_count[x264_scan8[0 * 4 + 3]]) << 3),
			(!!h->mb.cache.non_zero_count[x264_scan8[1 * 4 + 0]]) |
			((!!h->mb.cache.non_zero_count[x264_scan8[1 * 4 + 1]]) << 1) |
			((!!h->mb.cache.non_zero_count[x264_scan8[1 * 4 + 2]]) << 2) |
			((!!h->mb.cache.non_zero_count[x264_scan8[1 * 4 + 3]]) << 3),
			(!!h->mb.cache.non_zero_count[x264_scan8[2 * 4 + 0]]) |
			((!!h->mb.cache.non_zero_count[x264_scan8[2 * 4 + 1]]) << 1) |
			((!!h->mb.cache.non_zero_count[x264_scan8[2 * 4 + 2]]) << 2) |
			((!!h->mb.cache.non_zero_count[x264_scan8[2 * 4 + 3]]) << 3),
			(!!h->mb.cache.non_zero_count[x264_scan8[3 * 4 + 0]]) |
			((!!h->mb.cache.non_zero_count[x264_scan8[3 * 4 + 1]]) << 1) |
			((!!h->mb.cache.non_zero_count[x264_scan8[3 * 4 + 2]]) << 2) |
			((!!h->mb.cache.non_zero_count[x264_scan8[3 * 4 + 3]]) << 3)
		};
		uint8_t mask4x4 = (!!masks[0]) | (!!masks[1] << 1) | (!!masks[2] << 2) | (!!masks[3] << 3);
		/* moflex-aware chroma order: decoder reads bit4 = plane(1+!moflex), bit5 = plane(2-!moflex).
		 * For moflex=0: bit4 = V (x264 chroma idx 1), bit5 = U (x264 chroma idx 0). */
		int cf = h->param.b_moflex ? 0 : 1;
		int cs = h->param.b_moflex ? 1 : 0;
		int _enc_flags = (!!h->mb.cache.non_zero_count[x264_scan8[16 + cs * 16]] << 5) | (!!h->mb.cache.non_zero_count[x264_scan8[16 + cf * 16]] << 4) | (use8x8 ? mask : mask4x4);
		bs_write_ue(s, REV_byte_116160[_enc_flags]);
#if !RDO_SKIP_BS
		h->stat.frame.i_tex_bits += bs_pos(s) - tmp;
		if (A2_CACHED_GETENV("MOBI_ENCDBG"))
			fprintf(stderr, "[ENC2] MB(%d,%d) use8x8=%d flags=0x%02x idx2=%d pos_after_idx2=%d\n",
				h->mb.i_mb_x*16, h->mb.i_mb_y*16, use8x8, _enc_flags,
				REV_byte_116160[_enc_flags], bs_pos(s));
#endif
		
		if (use8x8)
		{
			for (int i8 = 0; i8 < 4; i8++)
			{
				if (h->mb.cache.non_zero_count[x264_scan8[i8 * 4]])
				{
					bs_write1(s, 1);//don't subdivide into 4x4
					h->stat.frame.i_mv_bits++;
#if !RDO_SKIP_BS
					int tmp = bs_pos(s);
#endif
					h->mb.cache.non_zero_count[x264_scan8[i8 * 4]] = encode_dct(h, h->dct.luma8x8[i8], 64, h->sh.i_type == SLICE_TYPE_I ? 1 : 0);
#if !RDO_SKIP_BS
					h->stat.frame.i_tex_bits += bs_pos(s) - tmp;
					if (A2_CACHED_GETENV("MOBI_ENCDBG"))
						fprintf(stderr, "[ENC3] MB(%d,%d) luma8x8[%d] pos_after=%d\n",
							h->mb.i_mb_x*16, h->mb.i_mb_y*16, i8, bs_pos(s));
#endif
				}
			}
		}
		else
		{
			for (int i8 = 0; i8 < 4; i8++)
			{
				if (!((mask4x4 >> i8) & 1))
					continue;
#if !RDO_SKIP_BS
				int tmp = bs_pos(s);
#endif
				bs_write_ue(s, REV_byte_1165C4[masks[i8]]);
#if !RDO_SKIP_BS
				h->stat.frame.i_tex_bits += bs_pos(s) - tmp;
				if (A2_CACHED_GETENV("MOBI_ENCDBG"))
					fprintf(stderr, "[ENC3] MB(%d,%d) luma4x4grp[%d] sub=0x%x sub_idx=%d pos_after_sub=%d\n",
						h->mb.i_mb_x*16, h->mb.i_mb_y*16, i8, masks[i8],
						REV_byte_1165C4[masks[i8]], bs_pos(s));
#endif
				for (int i4 = 0; i4 < 4; i4++)
				{
					if (h->mb.cache.non_zero_count[x264_scan8[i8 * 4 + i4]])
					{
#if !RDO_SKIP_BS
						tmp = bs_pos(s);
#endif
						h->mb.cache.non_zero_count[x264_scan8[i8 * 4 + i4]] = encode_dct(h, h->dct.luma4x4[i8 * 4 + i4], 16, h->sh.i_type == SLICE_TYPE_I ? 1 : 0);
#if !RDO_SKIP_BS
						h->stat.frame.i_tex_bits += bs_pos(s) - tmp;
						if (A2_CACHED_GETENV("MOBI_ENCDBG"))
							fprintf(stderr, "[ENC4] MB(%d,%d) luma4x4[%d][%d] pos_after=%d\n",
								h->mb.i_mb_x*16, h->mb.i_mb_y*16, i8, i4, bs_pos(s));
#endif
					}
				}
#if !RDO_SKIP_BS
				if (A2_CACHED_GETENV("MOBI_ENCDBG"))
					fprintf(stderr, "[ENC3] MB(%d,%d) luma4x4grp[%d] pos_after_grp=%d\n",
						h->mb.i_mb_x*16, h->mb.i_mb_y*16, i8, bs_pos(s));
#endif
			}
		}
	
		for (int k = 0; k < 2; k++)
		{
			int i = k == 0 ? cf : cs;
			if (h->mb.cache.non_zero_count[x264_scan8[16 + i * 16]])
			{
				bs_write1(s, 1);//don't subdivide into 4x4
				h->stat.frame.i_mv_bits++;
#if !RDO_SKIP_BS
				int tmp = bs_pos(s);
#endif
				h->mb.cache.non_zero_count[x264_scan8[16 + i * 16]] = encode_dct(h, h->dct.luma8x8[4 + 4 * i], 64, h->sh.i_type == SLICE_TYPE_I ? 1 : 0);
#if !RDO_SKIP_BS
				h->stat.frame.i_tex_bits += bs_pos(s) - tmp;
				if (A2_CACHED_GETENV("MOBI_ENCDBG"))
					fprintf(stderr, "[ENC3] MB(%d,%d) chroma[%d] pos_after=%d\n",
						h->mb.i_mb_x*16, h->mb.i_mb_y*16, k, bs_pos(s));
#endif
			}
		}
	}
	else //if( IS_INTRA( i_mb_type ) )
		encode_i_block(h);
}

#if !RDO_SKIP_BS
/* ACT22.1B rate-model bias trace, Hook B: actual written bits.
 * Read-only observability, following the exact pattern of mobi_coeff_dump()
 * in encoder/macroblock.h (and Hook A above in encoder/analyse.c): lazy-init
 * static FILE* opened from a getenv() path, no-op if MOBI_ACT22_RATE_TRACE
 * is unset (zero behavioral change when disabled). bits_actual is measured
 * with the same bs_pos(s) pattern already used throughout this file (e.g.
 * _dctstart above) -- a safe, established, zero-cost read that does not
 * touch bitstream state. Only READS h->mb.* fields already finalized by the
 * real write path; never writes anything that can influence the encode.
 * This whole block is compiled only in the real (RDO_SKIP_BS=0) translation
 * unit -- rdo.c re-includes this file with RDO_SKIP_BS=1 and
 * x264_macroblock_write_cavlc macro-renamed to a static RD-trial variant
 * that runs many times per MB and never writes real bits; guarding here
 * keeps this trace strictly to the one real, final write per MB. */
static ALWAYS_INLINE FILE *mobi_act22_rate_trace_writer_fp( void )
{
    static int enabled = -1;
    static FILE *fp = NULL;
    if( enabled < 0 )
    {
        const char *prefix = getenv( "MOBI_ACT22_RATE_TRACE" );
        enabled = prefix ? 1 : 0;
        if( enabled )
        {
            char path[4096];
            snprintf( path, sizeof(path), "%s_writer.csv", prefix );
            fp = fopen( path, "w" );
            if( fp )
                fprintf( fp, "frame_index,mb_x,mb_y,slice_type,i_type,cbp_luma,cbp_chroma,nnz_sum,qp,mv_x,mv_y,bits_actual\n" );
        }
        enabled = fp ? 1 : 0;
    }
    return enabled ? fp : NULL;
}

static ALWAYS_INLINE void mobi_act22_rate_trace_writer( x264_t *h, int bits_actual )
{
    FILE *fp = mobi_act22_rate_trace_writer_fp();
    if( !fp ) return;

    /* nnz_sum: sum of non_zero_count over the whole MB's coded-block range --
     * 16 luma 4x4/8x8 slots + 16 chroma-U slots + 16 chroma-V slots (only
     * some populated for 4:2:0, the rest read as 0), plus luma DC and the
     * two chroma DC slots. All indices go through the standard x264_scan8[]
     * lookup table, so this never touches the array's unused/padding cells
     * (which hold an unrelated 0x80 sentinel, see common/common.h). */
    const uint8_t *nzc = h->mb.cache.non_zero_count;
    int nnz_sum = 0;
    for( int i = 0; i < 48; i++ )
        nnz_sum += nzc[x264_scan8[i]];
    nnz_sum += nzc[x264_scan8[LUMA_DC]];
    nnz_sum += nzc[x264_scan8[CHROMA_DC+0]];
    nnz_sum += nzc[x264_scan8[CHROMA_DC+1]];

    /* Representative MV (list 0, top-left 4x4 partition): meaningful for
     * P_L0/P_SKIP/P_8x8; 0 for intra. Raw quarter-pel x/y -- magnitude is
     * computed in the offline analysis, not here. */
    int mv_x = 0, mv_y = 0;
    if( !IS_INTRA( h->mb.i_type ) )
    {
        mv_x = h->mb.cache.mv[0][x264_scan8[0]][0];
        mv_y = h->mb.cache.mv[0][x264_scan8[0]][1];
    }

    fprintf( fp, "%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d\n",
             h->fdec->i_frame, h->mb.i_mb_x, h->mb.i_mb_y, h->sh.i_type,
             h->mb.i_type, h->mb.i_cbp_luma, h->mb.i_cbp_chroma, nnz_sum,
             h->mb.i_qp, mv_x, mv_y, bits_actual );
}
#endif /* !RDO_SKIP_BS */

#if !RDO_SKIP_BS
/* ACT22.3: MobiClip-exact prediction-refinement simulation (env
 * MOBI_ACT22_3_SIM). Pure simulation: for each eligible P_L0 16x16 P-slice
 * MB, evaluates a fixed candidate MV set using MobiClip's REAL half-pel
 * motion-compensation filter and the REAL decoder-exact residual path, and
 * measures ACTUAL bits via the REAL MV writer (mobi_encode_p_partition,
 * already defined above in this file) and REAL residual writer (encode_dct,
 * ditto), both redirected to a throwaway scratch bs_t (never h->out.bs).
 * Every piece of real encoder state this touches (p_fdec, dct.luma4x4,
 * cache.non_zero_count, i_cbp_luma, cache.mv, h->out.bs) is snapshotted
 * before and restored after every single candidate. Guarded to
 * !RDO_SKIP_BS for the same reason as Hook B above. */

static ALWAYS_INLINE void mobi_act22_3_interp4x4( pixel *dst, int ds, pixel *src, int ss, int method )
{
    /* Verbatim duplicate of mobi_interp_block()'s arithmetic (encoder/
     * macroblock.c ~line 335-358) -- that function has file-static linkage
     * there and is not callable from this translation unit. Same 4-case
     * half-pel filter, byte-for-byte, not a reimplementation. xs=1 (luma). */
    for( int y = 0; y < 4; y++ )
    {
        for( int x = 0; x < 4; x++ )
        {
            pixel *s = src + x;
            int v;
            switch( method )
            {
            default:
            case 0: v = s[0]; break;
            case 1: v = (s[0]>>1) + (s[1]>>1); break;
            case 2: v = (s[0]>>1) + (s[ss]>>1); break;
            case 3: v = (((s[0]>>1)+(s[1]>>1))>>1) + (((s[ss]>>1)+(s[1+ss]>>1))>>1); break;
            }
            dst[x] = v;
        }
        dst += ds;
        src += ss;
    }
}

static ALWAYS_INLINE void mobi_act22_3_clamp( x264_t *h, int mvx, int mvy, int *out_x, int *out_y )
{
    /* Verbatim duplicate of mobi_motion_compensate()'s border clamp
     * (encoder/macroblock.c ~line 389-399). */
    int W = h->param.i_width, He = h->param.i_height;
    int ox = h->mb.i_mb_x*16, oy = h->mb.i_mb_y*16;
    int hxmin = -2*ox,          hxmax = 2*(W  - 16 - ox);
    int hymin = -2*oy,          hymax = 2*(He - 16 - oy);
    int hx = x264_clip3( mvx >> 1, hxmin, hxmax );
    int hy = x264_clip3( mvy >> 1, hymin, hymax );
    *out_x = hx << 1;
    *out_y = hy << 1;
}

static FILE *mobi_act22_3_fp( void )
{
    static int enabled = -1;
    static FILE *fp = NULL;
    if( enabled < 0 )
    {
        const char *prefix = getenv( "MOBI_ACT22_3_SIM" );
        enabled = prefix ? 1 : 0;
        if( enabled )
        {
            char path[4096];
            snprintf( path, sizeof(path), "%s_pred.csv", prefix );
            fp = fopen( path, "w" );
            if( fp )
                fprintf( fp,
                    "frame_index,mb_x,mb_y,candidate_label,current_mv_x,current_mv_y,candidate_mv_x,candidate_mv_y,"
                    "reference_index,prediction_sse,decoder_domain_reconstruction_distortion,residual_coefficient_count,"
                    "actual_residual_bits,actual_mv_bits,total_bits,lambda,corrected_rd_cost,classification,rejection_reason\n" );
        }
        enabled = fp ? 1 : 0;
    }
    return enabled ? fp : NULL;
}

/* Evaluate one candidate (already-clamped) MV against the CURRENT real MB
 * state. Snapshots and restores everything it touches; provably a no-op on
 * the real encode. */
static void mobi_act22_3_eval( x264_t *h, int cx, int cy,
                                double *out_pred_sse, double *out_recon_sse,
                                int *out_nnz, int *out_residual_bits, int *out_mv_bits )
{
    int iref = h->mb.cache.ref[0][x264_scan8[0]];
    if( iref < 0 ) iref = 0;

    /* ---- snapshot ---- */
    ALIGNED_ARRAY_16( pixel, save_fdec, [256] );
    for( int y = 0; y < 16; y++ )
        memcpy( save_fdec + y*16, h->mb.pic.p_fdec[0] + y*FDEC_STRIDE, 16*sizeof(pixel) );
    dctcoef save_dct[16][16];
    for( int i = 0; i < 16; i++ )
        for( int zz = 0; zz < 16; zz++ )
            save_dct[i][zz] = h->dct.luma4x4[i][zz];
    uint8_t save_nnz[16];
    for( int i = 0; i < 16; i++ ) save_nnz[i] = h->mb.cache.non_zero_count[x264_scan8[i]];
    int save_cbp = h->mb.i_cbp_luma;
    int16_t save_mv[16][2];
    for( int i = 0; i < 16; i++ )
    {
        int i8 = x264_scan8[0] + (i&3) + (i>>2)*8;
        save_mv[i][0] = h->mb.cache.mv[0][i8][0];
        save_mv[i][1] = h->mb.cache.mv[0][i8][1];
    }

    /* ---- apply candidate MV to cache.mv (mobi_encode_p_partition below
     * reads it directly, same as mobi_motion_compensate does for real) ---- */
    for( int i = 0; i < 16; i++ )
    {
        int i8 = x264_scan8[0] + (i&3) + (i>>2)*8;
        h->mb.cache.mv[0][i8][0] = cx;
        h->mb.cache.mv[0][i8][1] = cy;
    }

    /* ---- prediction: MobiClip half-pel filter, matches mobi_motion_compensate's luma loop ---- */
    int sy = h->mb.pic.i_stride[0];
    int hmvx = cx >> 1, hmvy = cy >> 1;
    int method = (hmvx & 1) | ((hmvy & 1) << 1);
    pixel *ref = h->mb.pic.p_fref[0][iref][0];
    for( int by = 0; by < 16; by += 4 )
        for( int bx = 0; bx < 16; bx += 4 )
        {
            pixel *src = ref + (by + (hmvy>>1))*sy + (bx + (hmvx>>1));
            pixel *dst = h->mb.pic.p_fdec[0] + by*FDEC_STRIDE + bx;
            mobi_act22_3_interp4x4( dst, FDEC_STRIDE, src, sy, method );
        }

    double pred_sse = 0;
    {
        pixel *pf = h->mb.pic.p_fdec[0];
        pixel *pe = h->mb.pic.p_fenc[0];
        for( int y = 0; y < 16; y++ )
            for( int x = 0; x < 16; x++ )
            {
                int d = (int)pf[y*FDEC_STRIDE+x] - (int)pe[y*FENC_STRIDE+x];
                pred_sse += (double)(d*d);
            }
    }

    /* ---- residual: REAL decoder-exact 4x4 path (x264_mb_encode_i4x4,
     * encoder/macroblock.h ~line 630), b_predict=0 keeps the MC prediction
     * just written above and overwrites p_fdec with the full reconstruction
     * -- this is the exact function the real inter path already uses
     * (encoder/macroblock.c ~line 1178), already gate-proven decoder-exact
     * by every ACT22.1B/2A byte-identity gate. ---- */
    h->mb.i_cbp_luma = 0;
    for( int i4 = 0; i4 < 16; i4++ )
        x264_mb_encode_i4x4( h, 0, i4, h->mb.i_qp, 0, 0 );

    double recon_sse = 0;
    {
        pixel *pf = h->mb.pic.p_fdec[0];
        pixel *pe = h->mb.pic.p_fenc[0];
        for( int y = 0; y < 16; y++ )
            for( int x = 0; x < 16; x++ )
            {
                int d = (int)pf[y*FDEC_STRIDE+x] - (int)pe[y*FENC_STRIDE+x];
                recon_sse += (double)(d*d);
            }
    }
    int nnz_sum = 0;
    for( int i = 0; i < 16; i++ ) nnz_sum += h->mb.cache.non_zero_count[x264_scan8[i]];

    /* ---- actual residual bits: replicate encode_p_block()'s non-8x8-luma
     * path exactly (this content forces b_transform_8x8=0, so that path is
     * the only one ever exercised for real) using the just-computed
     * candidate dct/nnz. Chroma nnz flag bits are read from the REAL/
     * current (untouched) cache -- identical across every candidate for
     * this MB, so this is a constant per-MB offset in total_bits, not a
     * source of candidate-to-candidate bias (documented simplification:
     * chroma reconstruction/MC itself is out of scope for this act). ---- */
    int residual_bits = 0;
    {
        bs_t save_bs = h->out.bs;
        uint8_t scratch[4096];
        bs_init( &h->out.bs, scratch, sizeof(scratch) );
        bs_t *s = &h->out.bs;

        uint8_t masks[4];
        for( int g = 0; g < 4; g++ )
            masks[g] = (uint8_t)( (!!h->mb.cache.non_zero_count[x264_scan8[g*4+0]])
                     | ((!!h->mb.cache.non_zero_count[x264_scan8[g*4+1]])<<1)
                     | ((!!h->mb.cache.non_zero_count[x264_scan8[g*4+2]])<<2)
                     | ((!!h->mb.cache.non_zero_count[x264_scan8[g*4+3]])<<3) );
        uint8_t mask4x4 = (uint8_t)((!!masks[0])|(!!masks[1]<<1)|(!!masks[2]<<2)|(!!masks[3]<<3));
        int cf = h->param.b_moflex ? 0 : 1;
        int cs = h->param.b_moflex ? 1 : 0;
        int chroma_cs = !!h->mb.cache.non_zero_count[x264_scan8[16 + cs*16]];
        int chroma_cf = !!h->mb.cache.non_zero_count[x264_scan8[16 + cf*16]];
        int _enc_flags = (chroma_cs<<5)|(chroma_cf<<4)|mask4x4;
        bs_write_ue( s, REV_byte_116160[_enc_flags] );
        for( int g = 0; g < 4; g++ )
        {
            if( !((mask4x4>>g)&1) ) continue;
            bs_write_ue( s, REV_byte_1165C4[masks[g]] );
            for( int i4 = 0; i4 < 4; i4++ )
                if( h->mb.cache.non_zero_count[x264_scan8[g*4+i4]] )
                    encode_dct( h, h->dct.luma4x4[g*4+i4], 16, 0 );
        }
        residual_bits = bs_pos( s );
        h->out.bs = save_bs;
    }

    /* ---- actual MV bits: REAL MobiClip MV writer (mobi_encode_p_partition,
     * already defined above), scratch bs. The predictor used here (mpx,mpy
     * via mobi_mid_pred over h->mobi_motion_x/y) is MobiClip's OWN real
     * predictor -- the one that actually governs MV-delta bit cost -- NOT
     * x264's stock x264_mb_predict_mv, which this encoder computes only for
     * its own (unused, since mobiclip forces its own MV coding) H.264-style
     * cost machinery. This is a deliberate, source-grounded correction; see
     * the report for the discrepancy this resolves. ---- */
    int mv_bits = 0;
    {
        bs_t save_bs = h->out.bs;
        uint8_t scratch2[256];
        bs_init( &h->out.bs, scratch2, sizeof(scratch2) );
        int mb_col = h->mb.i_mb_x;
        int mpx = mobi_mid_pred( h->mobi_motion_x[mb_col+1], h->mobi_motion_x[mb_col+2], h->mobi_motion_x[mb_col+3] );
        int mpy = mobi_mid_pred( h->mobi_motion_y[mb_col+1], h->mobi_motion_y[mb_col+2], h->mobi_motion_y[mb_col+3] );
        int lastMv[2] = { 0, 0 };
        mobi_encode_p_partition( h, 0, 16, 16, mpx, mpy, lastMv );
        mv_bits = bs_pos( &h->out.bs );
        h->out.bs = save_bs;
    }

    /* ---- restore everything ---- */
    for( int y = 0; y < 16; y++ )
        memcpy( h->mb.pic.p_fdec[0] + y*FDEC_STRIDE, save_fdec + y*16, 16*sizeof(pixel) );
    for( int i = 0; i < 16; i++ )
        for( int zz = 0; zz < 16; zz++ )
            h->dct.luma4x4[i][zz] = save_dct[i][zz];
    for( int i = 0; i < 16; i++ ) h->mb.cache.non_zero_count[x264_scan8[i]] = save_nnz[i];
    h->mb.i_cbp_luma = save_cbp;
    for( int i = 0; i < 16; i++ )
    {
        int i8 = x264_scan8[0] + (i&3) + (i>>2)*8;
        h->mb.cache.mv[0][i8][0] = save_mv[i][0];
        h->mb.cache.mv[0][i8][1] = save_mv[i][1];
    }

    *out_pred_sse = pred_sse;
    *out_recon_sse = recon_sse;
    *out_nnz = nnz_sum;
    *out_residual_bits = residual_bits;
    *out_mv_bits = mv_bits;
}

static void mobi_act22_3_sim( x264_t *h )
{
    FILE *fp = mobi_act22_3_fp();
    if( !fp ) return;
    if( h->sh.i_type != SLICE_TYPE_P || h->mb.i_type != P_L0 || h->mb.i_partition != D_16x16 )
        return;

    int cur_x = h->mb.cache.mv[0][x264_scan8[0]][0];
    int cur_y = h->mb.cache.mv[0][x264_scan8[0]][1];
    int iref  = h->mb.cache.ref[0][x264_scan8[0]];
    if( iref < 0 ) iref = 0;
    int lambda = h->mb.i_qp >= 0 ? x264_lambda_tab[h->mb.i_qp] : 0;

    /* Candidate list: (label, mvx, mvy, available). Steps of 2 in cache.mv
     * (quarter-pel) units = 1 half-pel step, since mobi_motion_compensate
     * only ever reads cache.mv>>1 -- an odd-quarter-pel candidate is not a
     * new phase, just a wasted duplicate of an even neighbor (see report). */
    struct { const char *label; int x, y; int avail; } cand[16];
    int nc = 0;

    /* median: MobiClip's OWN real predictor (see mv_bits comment above) */
    {
        int mb_col = h->mb.i_mb_x;
        int mpx = mobi_mid_pred( h->mobi_motion_x[mb_col+1], h->mobi_motion_x[mb_col+2], h->mobi_motion_x[mb_col+3] );
        int mpy = mobi_mid_pred( h->mobi_motion_y[mb_col+1], h->mobi_motion_y[mb_col+2], h->mobi_motion_y[mb_col+3] );
        /* mpx/mpy are already in half-pel units (mirrors decoder's motion[]
         * array, which stores hmv); convert to cache.mv (quarter-pel) units. */
        cand[nc++] = (typeof(cand[0])){ "median", mpx*2, mpy*2, 1 };
    }
    cand[nc++] = (typeof(cand[0])){ "zero", 0, 0, 1 };

    /* neighbors: exact x264_mb_predict_mv availability indexing (common/mvpred.c
     * ~line 34-39), ref==-2 means unavailable -- never invented. */
    {
        int i8 = x264_scan8[0];
        int refa = h->mb.cache.ref[0][i8-1];
        int refb = h->mb.cache.ref[0][i8-8];
        int refc = h->mb.cache.ref[0][i8-8+4];
        if( refc == -2 ) refc = h->mb.cache.ref[0][i8-8-1]; /* topleft fallback, same as x264_mb_predict_mv */
        cand[nc++] = (typeof(cand[0])){ "left",     h->mb.cache.mv[0][i8-1][0],   h->mb.cache.mv[0][i8-1][1],   refa != -2 };
        cand[nc++] = (typeof(cand[0])){ "top",      h->mb.cache.mv[0][i8-8][0],   h->mb.cache.mv[0][i8-8][1],   refb != -2 };
        cand[nc++] = (typeof(cand[0])){ "topright", h->mb.cache.mv[0][i8-8+4][0], h->mb.cache.mv[0][i8-8+4][1], refc != -2 };
    }

    /* +-2 (1 half-pel step) and +-4 (2 half-pel steps), 4 axis-aligned directions */
    cand[nc++] = (typeof(cand[0])){ "+x2", cur_x+2, cur_y,   1 };
    cand[nc++] = (typeof(cand[0])){ "-x2", cur_x-2, cur_y,   1 };
    cand[nc++] = (typeof(cand[0])){ "+x4", cur_x+4, cur_y,   1 };
    cand[nc++] = (typeof(cand[0])){ "-x4", cur_x-4, cur_y,   1 };
    cand[nc++] = (typeof(cand[0])){ "+y2", cur_x,   cur_y+2, 1 };
    cand[nc++] = (typeof(cand[0])){ "-y2", cur_x,   cur_y-2, 1 };
    cand[nc++] = (typeof(cand[0])){ "+y4", cur_x,   cur_y+4, 1 };
    cand[nc++] = (typeof(cand[0])){ "-y4", cur_x,   cur_y-4, 1 };

    /* the other 3 half-pel phases at the current integer position */
    {
        int base_x = cur_x & ~3, base_y = cur_y & ~3; /* strip to integer-pel (quarter-pel units, step 4) */
        cand[nc++] = (typeof(cand[0])){ "phase_01", base_x,   base_y+2, !(base_x==cur_x && base_y+2==cur_y) };
        cand[nc++] = (typeof(cand[0])){ "phase_10", base_x+2, base_y,   !(base_x+2==cur_x && base_y==cur_y) };
        cand[nc++] = (typeof(cand[0])){ "phase_11", base_x+2, base_y+2, !(base_x+2==cur_x && base_y+2==cur_y) };
    }

    /* current (baseline) row, evaluated the same way for apples-to-apples comparison */
    double cur_pred_sse, cur_recon_sse; int cur_nnz, cur_res_bits, cur_mv_bits;
    {
        int ccx, ccy; mobi_act22_3_clamp( h, cur_x, cur_y, &ccx, &ccy );
        mobi_act22_3_eval( h, ccx, ccy, &cur_pred_sse, &cur_recon_sse, &cur_nnz, &cur_res_bits, &cur_mv_bits );
    }
    int cur_total_bits = cur_res_bits + cur_mv_bits;
    double cur_rd = cur_recon_sse + (double)lambda * cur_total_bits;

    fprintf( fp, "%d,%d,%d,current,%d,%d,%d,%d,%d,%.1f,%.1f,%d,%d,%d,%d,%d,%.2f,BASELINE,\n",
             h->fdec->i_frame, h->mb.i_mb_x, h->mb.i_mb_y, cur_x, cur_y, cur_x, cur_y, iref,
             cur_pred_sse, cur_recon_sse, cur_nnz, cur_res_bits, cur_mv_bits, cur_total_bits, lambda, cur_rd );

    /* dedup by clamped MV already seen for this MB */
    int seen_x[16], seen_y[16], n_seen = 0;
    { int ccx, ccy; mobi_act22_3_clamp( h, cur_x, cur_y, &ccx, &ccy ); seen_x[n_seen]=ccx; seen_y[n_seen]=ccy; n_seen++; }

    for( int i = 0; i < nc; i++ )
    {
        if( !cand[i].avail )
        {
            fprintf( fp, "%d,%d,%d,%s,%d,%d,,,,,,,,,,,,REJECT,CANDIDATE_UNAVAILABLE\n",
                     h->fdec->i_frame, h->mb.i_mb_x, h->mb.i_mb_y, cand[i].label, cur_x, cur_y );
            continue;
        }
        int ccx, ccy;
        mobi_act22_3_clamp( h, cand[i].x, cand[i].y, &ccx, &ccy );

        int dup = 0;
        for( int k = 0; k < n_seen; k++ )
            if( seen_x[k] == ccx && seen_y[k] == ccy ) { dup = 1; break; }
        if( dup )
        {
            fprintf( fp, "%d,%d,%d,%s,%d,%d,%d,%d,%d,,,,,,,,,REJECT,DUPLICATE_OF_ALREADY_EVALUATED\n",
                     h->fdec->i_frame, h->mb.i_mb_x, h->mb.i_mb_y, cand[i].label, cur_x, cur_y, ccx, ccy, iref );
            continue;
        }
        seen_x[n_seen] = ccx; seen_y[n_seen] = ccy; n_seen++;

        double pred_sse, recon_sse; int nnz, res_bits, mv_bits;
        mobi_act22_3_eval( h, ccx, ccy, &pred_sse, &recon_sse, &nnz, &res_bits, &mv_bits );
        int total_bits = res_bits + mv_bits;
        double rd = recon_sse + (double)lambda * total_bits;

        int strict = ( total_bits < cur_total_bits ) && ( recon_sse <= cur_recon_sse );
        int quality_win = ( recon_sse < cur_recon_sse ) && ( total_bits <= cur_total_bits );
        int positive_rd = !strict && !quality_win && ( rd < cur_rd );

        const char *classification;
        const char *reason = "";
        if( strict )            classification = "STRICT_DOMINANCE";
        else if( quality_win )  classification = "QUALITY_WIN";
        else if( positive_rd )  classification = "POSITIVE_RD";
        else
        {
            classification = "REJECT";
            if( total_bits >= cur_total_bits && recon_sse >= cur_recon_sse )
                reason = "HIGHER_BITS_AND_DISTORTION";
            else if( rd >= cur_rd )
                reason = "MARGINAL_RD_NEGATIVE";
            else
                reason = "OTHER";
        }

        fprintf( fp, "%d,%d,%d,%s,%d,%d,%d,%d,%d,%.1f,%.1f,%d,%d,%d,%d,%d,%.2f,%s,%s\n",
                 h->fdec->i_frame, h->mb.i_mb_x, h->mb.i_mb_y, cand[i].label, cur_x, cur_y, ccx, ccy, iref,
                 pred_sse, recon_sse, nnz, res_bits, mv_bits, total_bits, lambda, rd, classification, reason );
    }
}
#endif /* !RDO_SKIP_BS */

#if !RDO_SKIP_BS
/* ============================================================================
 * ACT22.9 Phases 2/3/4: decoder-domain residual coefficient RDO.
 *
 * Simulation: env MOBI_ACT22_RDO_SIM=1 (read-only, no state mutation).
 * Activation: env MOBI_ACT22_RDO_ENABLE=1 (mutates real encoder state, see
 * mobi_act22_9_apply() below). Independent flags, mutually exclusive in
 * practice (activation implies the simulation's own decision logic is
 * reused, but activation does not also emit the simulation CSV).
 *
 * Scope: LUMA 4x4 coefficient blocks only ("safe-4x4" -- this codec's term
 * for the always-4x4-never-8x8 luma transform, b_transform_8x8 forced 0 for
 * every mobiclip encode). Chroma in this codec uses 64-coefficient (8x8)
 * blocks via a completely different code path (encode_dct(...,64,...) on
 * h->dct.luma8x8[4+4*i]), so it is outside "safe-4x4" by the term's own
 * definition, not merely skipped for time -- see report for confirmation.
 *
 * Context-state check (done, not assumed, per the explicit instruction to
 * be careful here): encode_dct() below (this file, ~line 627) is a pure
 * function of (coefficient vector, length, table-selector) -- table is a
 * per-SLICE constant (I-slice vs P-slice), not neighbor-dependent. There is
 * no coeff_token/nC-style neighbor lookup anywhere in it. The only
 * cross-block dependency is at the GROUP level (an 8x8 group's 4 sibling
 * 4x4 blocks share one mask/golomb header -- REV_byte_1165C4 for P_L0,
 * subblock_mask_to_golomb_table for I_4x4), which this code accounts for
 * explicitly by recomputing the whole group's header on every candidate
 * evaluation, not by hand-deriving a delta. */

#define MOBI_ACT22_9_MAX_CAND 24

/* Verbatim replication of the dequant+inverse4+reconstruct arithmetic in
 * x264_mb_encode_i4x4 (encoder/macroblock.h ~line 688-794), operating on a
 * scratch prediction buffer and scratch output -- never touches real
 * h->mb.pic.p_fdec. pred/out are row-major 4x4 (stride 4). coef_zigzag is
 * in the same scan order as h->dct.luma4x4[idx][] (i.e. directly usable
 * with encode_dct). out_coef_zigzag_final receives the (rarely) attenuated
 * coefficients actually reconstructed from, in the same zigzag order --
 * this is what activation must store back into h->dct.luma4x4 to keep the
 * bitstream and the encoder's own reconstruction consistent. */
static void mobi_act22_9_dequant_recon2( x264_t *h, const dctcoef *coef_zigzag, int i_qp,
                                          const pixel *pred, pixel *out, dctcoef *out_coef_zigzag_final,
                                          int *out_mat_raw, int skip_attenuation )
{
    int qx = i_qp % 6;
    int shift = mobi_qyx( h );
    int qtab64[16];
    int dct4x4[16];
    for( int zz = 0; zz < 16; zz++ )
    {
        int npos = mobi_zigzag4x4[zz];
        qtab64[npos] = mobi_q4[qx][zz] << (2 + shift);
        dct4x4[npos] = coef_zigzag[zz];
    }

    int mat[16];
    for( int mobi_pass = 0; ; mobi_pass++ )
    {
        for( int i = 0; i < 16; i++ )
            mat[i] = dct4x4[i] * qtab64[i];
        mat[0] += 32;
        for( int i = 0; i < 4; i++ )
        {
            unsigned a = (unsigned)mat[i*4+0] + mat[i*4+2];
            unsigned b = (unsigned)mat[i*4+0] - mat[i*4+2];
            unsigned c = (unsigned)mat[i*4+1] + (mat[i*4+3] >> 1);
            unsigned d = (mat[i*4+1] >> 1) - (unsigned)mat[i*4+3];
            mat[i*4+0] = a + c;
            mat[i*4+1] = b + d;
            mat[i*4+2] = b - d;
            mat[i*4+3] = a - c;
        }
        for( int y = 0; y < 4; y++ )
            for( int x = y+1; x < 4; x++ )
            {
                int tmp = mat[y*4+x]; mat[y*4+x] = mat[x*4+y]; mat[x*4+y] = tmp;
            }
        for( int y = 0; y < 4; y++ )
        {
            unsigned a = (unsigned)mat[y*4+0] + mat[y*4+2];
            unsigned b = (unsigned)mat[y*4+0] - mat[y*4+2];
            unsigned c = (unsigned)mat[y*4+1] + (mat[y*4+3] >> 1);
            unsigned d = (mat[y*4+1] >> 1) - (unsigned)mat[y*4+3];
            mat[y*4+0] = (int)(a + c) >> 6;
            mat[y*4+1] = (int)(b + d) >> 6;
            mat[y*4+2] = (int)(b - d) >> 6;
            mat[y*4+3] = (int)(a - c) >> 6;
        }
        int oob = 0;
        if( !skip_attenuation )
            for( int y = 0; y < 4 && !oob; y++ )
                for( int x = 0; x < 4; x++ )
                {
                    int sv = (int)pred[y*4+x] + mat[y*4+x];
                    if( sv < -64 || sv > 319 ) { oob = 1; break; }
                }
        if( !oob || mobi_pass >= 16 )
            break;
        int has_ac = 0;
        for( int i = 1; i < 16; i++ ) if( dct4x4[i] ) { has_ac = 1; break; }
        if( has_ac )
            for( int i = 1; i < 16; i++ ) dct4x4[i] /= 2;
        else
            dct4x4[0] /= 2;
    }
    for( int y = 0; y < 4; y++ )
        for( int x = 0; x < 4; x++ )
            out[y*4+x] = x264_clip_pixel( pred[y*4+x] + mat[y*4+x] );
    if( out_coef_zigzag_final )
        for( int zz = 0; zz < 16; zz++ )
            out_coef_zigzag_final[zz] = (dctcoef)dct4x4[mobi_zigzag4x4[zz]];
    if( out_mat_raw )
        memcpy( out_mat_raw, mat, sizeof(mat) );
}

/* Normal entry point: full attenuation-loop behavior, exactly matching the
 * real x264_mb_encode_i4x4 path. Used for every genuine candidate
 * evaluation (a NEW coefficient set against a genuine prediction base, for
 * which the oob check is meaningful and must run as designed). */
static void mobi_act22_9_dequant_recon( x264_t *h, const dctcoef *coef_zigzag, int i_qp,
                                          const pixel *pred, pixel *out, dctcoef *out_coef_zigzag_final,
                                          int *out_mat_raw )
{
    mobi_act22_9_dequant_recon2( h, coef_zigzag, i_qp, pred, out, out_coef_zigzag_final, out_mat_raw, 0 );
}

/* Scratch-measure the WHOLE MB's luma residual bits (all 16 blocks, 4
 * groups of 4), optionally substituting ONE block's coefficients/nnz with
 * an override. Branches on P_L0(D_16x16) vs I_4x4 -- the only two modes
 * this content exercises (P_8x8/16x8/8x16/I_8x8/I_16x16/I_PCM/skip/B_* are
 * all 0% per every mb-type histogram measured across ACT22.1B-8). Mode-
 * signaling and MV bits are intentionally NOT replicated here: they are
 * identical between "current" and every candidate (coefficient-only
 * changes never alter mode/MV), so they cancel exactly in any bits-saved
 * delta: this function's return value is the luma-residual bit component
 * only, not the whole-MB total -- documented explicitly in the CSV header
 * and the report, not silently redefined as "total". */
static int mobi_act22_9_luma_mb_bits( x264_t *h, int override_idx, const dctcoef *override_coef, int override_nnz )
{
    bs_t save_bs = h->out.bs;
    uint8_t scratch[8192];
    bs_init( &h->out.bs, scratch, sizeof(scratch) );
    bs_t *s = &h->out.bs;

    int table = h->sh.i_type == SLICE_TYPE_I ? 1 : 0;
    #define MOBI_ACT22_9_NNZ(idx) ((idx)==override_idx ? override_nnz : h->mb.cache.non_zero_count[x264_scan8[idx]])
    #define MOBI_ACT22_9_COEF(idx) ((idx)==override_idx ? override_coef : h->dct.luma4x4[idx])

    if( h->mb.i_type == P_L0 )
    {
        uint8_t masks[4];
        for( int g = 0; g < 4; g++ )
            masks[g] = (uint8_t)( (!!MOBI_ACT22_9_NNZ(g*4+0))
                     | ((!!MOBI_ACT22_9_NNZ(g*4+1))<<1)
                     | ((!!MOBI_ACT22_9_NNZ(g*4+2))<<2)
                     | ((!!MOBI_ACT22_9_NNZ(g*4+3))<<3) );
        uint8_t mask4x4 = (uint8_t)((!!masks[0])|(!!masks[1]<<1)|(!!masks[2]<<2)|(!!masks[3]<<3));
        int cf = h->param.b_moflex ? 0 : 1;
        int cs = h->param.b_moflex ? 1 : 0;
        int chroma_cs = !!h->mb.cache.non_zero_count[x264_scan8[16 + cs*16]];
        int chroma_cf = !!h->mb.cache.non_zero_count[x264_scan8[16 + cf*16]];
        int _enc_flags = (chroma_cs<<5)|(chroma_cf<<4)|mask4x4;
        bs_write_ue( s, REV_byte_116160[_enc_flags] );
        for( int g = 0; g < 4; g++ )
        {
            if( !((mask4x4>>g)&1) ) continue;
            bs_write_ue( s, REV_byte_1165C4[masks[g]] );
            for( int i4 = 0; i4 < 4; i4++ )
                if( MOBI_ACT22_9_NNZ(g*4+i4) )
                    encode_dct( h, (dctcoef*)MOBI_ACT22_9_COEF(g*4+i4), 16, table );
        }
    }
    else /* I_4x4 */
    {
        for( int g = 0; g < 4; g++ )
        {
            uint8_t mask = (uint8_t)( (!!MOBI_ACT22_9_NNZ(g*4+0))
                     | ((!!MOBI_ACT22_9_NNZ(g*4+1))<<1)
                     | ((!!MOBI_ACT22_9_NNZ(g*4+2))<<2)
                     | ((!!MOBI_ACT22_9_NNZ(g*4+3))<<3) );
            bs_write_ue( s, subblock_mask_to_golomb_table[mask] );
            for( int i4 = 0; i4 < 4; i4++ )
                if( MOBI_ACT22_9_NNZ(g*4+i4) )
                    encode_dct( h, (dctcoef*)MOBI_ACT22_9_COEF(g*4+i4), 16, table );
        }
    }
    #undef MOBI_ACT22_9_NNZ
    #undef MOBI_ACT22_9_COEF

    int bits = bs_pos( s );
    h->out.bs = save_bs;
    return bits;
}

typedef struct
{
    const char *label;
    dctcoef coef[16];
    int nnz;
    int scan_pos; /* representative scan position touched, -1 if n/a */
} mobi_act22_9_cand_t;

/* Candidate generation per Phase 2's exact list. cur[] is zigzag-order,
 * cur_nnz its nonzero count. Returns candidate count (excludes "current"
 * itself, which the caller always evaluates separately as the baseline). */
static int mobi_act22_9_gen_candidates( const dctcoef *cur, int cur_nnz, mobi_act22_9_cand_t *out )
{
    int n = 0;
    int nz_pos[16], nnz_found = 0;
    for( int zz = 0; zz < 16; zz++ )
        if( cur[zz] ) nz_pos[nnz_found++] = zz;
    if( nnz_found == 0 ) return 0;
    int last = nz_pos[nnz_found-1];

    /* 1) remove trailing nonzero coefficient */
    {
        mobi_act22_9_cand_t *c = &out[n++];
        c->label = "remove_trailing";
        memcpy( c->coef, cur, sizeof(c->coef) );
        c->coef[last] = 0;
        c->nnz = cur_nnz - 1;
        c->scan_pos = last;
    }

    /* 2) reduce one nonzero magnitude toward zero by one -- one candidate
     * per existing nonzero position (bounded by nnz <= 16). */
    for( int k = 0; k < nnz_found && n < MOBI_ACT22_9_MAX_CAND - 4; k++ )
    {
        int zz = nz_pos[k];
        mobi_act22_9_cand_t *c = &out[n++];
        c->label = "reduce_mag1";
        memcpy( c->coef, cur, sizeof(c->coef) );
        dctcoef v = c->coef[zz];
        c->coef[zz] = v > 0 ? v - 1 : v + 1;
        c->nnz = c->coef[zz] == 0 ? cur_nnz - 1 : cur_nnz;
        c->scan_pos = zz;
    }

    /* 3) zero isolated high-frequency coefficients: nonzero, scan position
     * >= 8 (upper half of the 4x4 zigzag = the higher-frequency half), and
     * "isolated" meaning its immediate zigzag neighbours (zz-1, zz+1) are
     * both zero. */
    for( int k = 0; k < nnz_found && n < MOBI_ACT22_9_MAX_CAND - 2; k++ )
    {
        int zz = nz_pos[k];
        if( zz < 8 ) continue;
        int left_zero  = ( zz == 0 )  || ( cur[zz-1] == 0 );
        int right_zero = ( zz == 15 ) || ( cur[zz+1] == 0 );
        if( !left_zero || !right_zero ) continue;
        mobi_act22_9_cand_t *c = &out[n++];
        c->label = "zero_isolated_hf";
        memcpy( c->coef, cur, sizeof(c->coef) );
        c->coef[zz] = 0;
        c->nnz = cur_nnz - 1;
        c->scan_pos = zz;
    }

    /* 4) bounded combinations of the last two/three nonzero coefficients */
    if( nnz_found >= 2 && n < MOBI_ACT22_9_MAX_CAND - 2 )
    {
        mobi_act22_9_cand_t *c = &out[n++];
        c->label = "zero_last2";
        memcpy( c->coef, cur, sizeof(c->coef) );
        c->coef[nz_pos[nnz_found-1]] = 0;
        c->coef[nz_pos[nnz_found-2]] = 0;
        c->nnz = cur_nnz - 2;
        c->scan_pos = nz_pos[nnz_found-1];
    }
    if( nnz_found >= 3 && n < MOBI_ACT22_9_MAX_CAND - 1 )
    {
        mobi_act22_9_cand_t *c = &out[n++];
        c->label = "zero_last3";
        memcpy( c->coef, cur, sizeof(c->coef) );
        c->coef[nz_pos[nnz_found-1]] = 0;
        c->coef[nz_pos[nnz_found-2]] = 0;
        c->coef[nz_pos[nnz_found-3]] = 0;
        c->nnz = cur_nnz - 3;
        c->scan_pos = nz_pos[nnz_found-1];
    }

    /* 5) zero the full residual -- generated unconditionally; it is only
     * ACCEPTED (see classification) when reconstructed pixels turn out to
     * be exactly preserved, per the literal instruction. Most of the time
     * this will simply score as REJECT/NEAR_LOSSLESS like any other
     * candidate; the eligibility gate is enforced at classification time,
     * not here. */
    if( n < MOBI_ACT22_9_MAX_CAND )
    {
        mobi_act22_9_cand_t *c = &out[n++];
        c->label = "zero_full";
        memset( c->coef, 0, sizeof(c->coef) );
        c->nnz = 0;
        c->scan_pos = -1;
    }

    return n;
}

static FILE *mobi_act22_9_sim_fp( void )
{
    static int enabled = -1;
    static FILE *fp = NULL;
    if( enabled < 0 )
    {
        const char *prefix = getenv( "MOBI_ACT22_RDO_SIM" );
        enabled = ( prefix && atoi(prefix) ) ? 1 : 0;
        if( enabled )
        {
            char path[4096];
            const char *outpfx = getenv( "MOBI_ACT22_RDO_SIM_OUT" );
            snprintf( path, sizeof(path), "%s_rdo.csv", outpfx ? outpfx : "mobi_act22_9" );
            fp = fopen( path, "w" );
            if( fp )
                fprintf( fp,
                    "frame_index,mb_x,mb_y,blk_idx,plane,candidate_label,cur_coef_hash,cand_coef_hash,"
                    "luma_residual_bits_cur,luma_residual_bits_cand,bits_saved,cur_recon_sse,cand_recon_sse,"
                    "max_abs_pixel_diff,scan_pos,cur_nnz,cand_nnz,cbp_effect,context_changes,exact_eligible,"
                    "classification,rejection_reason\n" );
        }
        enabled = fp ? 1 : 0;
    }
    return enabled ? fp : NULL;
}

static int mobi_act22_9_activate_enabled( void )
{
    static int enabled = -1;
    if( enabled < 0 )
    {
        const char *v = getenv( "MOBI_ACT22_RDO_ENABLE" );
        enabled = ( v && atoi(v) ) ? 1 : 0;
    }
    return enabled;
}

static unsigned mobi_act22_9_coef_hash( const dctcoef *c )
{
    unsigned h2 = 2166136261u;
    for( int i = 0; i < 16; i++ )
    {
        h2 ^= (unsigned)(uint16_t)c[i];
        h2 *= 16777619u;
    }
    return h2;
}

/* Evaluate every candidate for one eligible 4x4 luma block. In SIM mode,
 * logs every candidate's row (read-only -- never mutates dct.luma4x4,
 * non_zero_count, i_cbp_luma, or p_fdec; the only external state touched
 * is h->out.bs, saved/restored by mobi_act22_9_luma_mb_bits() itself).
 * In ACTIVATE mode, applies the best EXACT_WIN/STRICT_DOMINANCE/
 * QUALITY_WIN candidate (if any) by mutating exactly the state Phase 4
 * requires: dct.luma4x4[idx], cache.non_zero_count[idx], i_cbp_luma (the
 * whole group's bit, recomputed from all 4 sibling blocks so a
 * newly-all-zero group correctly clears it), and the block's 4x4 region
 * of p_fdec[0] (so the encoder's own reconstructed reference matches
 * exactly what will be decoded -- this is what keeps the P-frame
 * reference chain correct for every later frame). Runs BEFORE the real
 * encode_p_block/encode_i_block call (see call site in
 * x264_macroblock_write_cavlc), so the natural write emits whatever this
 * function decided. */
static void mobi_act22_9_eval_block( x264_t *h, int blk_idx, int i_qp, FILE *sim_fp, int do_activate )
{
    int i8 = x264_scan8[blk_idx];
    int cur_nnz = h->mb.cache.non_zero_count[i8];
    if( !cur_nnz ) return; /* nothing to reduce -- not an eligible block */

    dctcoef cur[16];
    memcpy( cur, h->dct.luma4x4[blk_idx], sizeof(cur) );

    pixel *p_dst = &h->mb.pic.p_fdec[0][block_idx_xy_fdec[blk_idx]];
    pixel *p_src = &h->mb.pic.p_fenc[0][block_idx_xy_fenc[blk_idx]];
    pixel fenc[16], cur_recon[16];
    for( int y = 0; y < 4; y++ )
        for( int x = 0; x < 4; x++ )
        {
            fenc[y*4+x] = p_src[y*FENC_STRIDE+x];
            cur_recon[y*4+x] = p_dst[y*FDEC_STRIDE+x];
        }
    /* Recover the pure (pre-residual) prediction exactly, using the RAW
     * (unclipped) inverse-transform output rather than the clipped pixel
     * values -- p_dst already holds clip(pred + mat_orig), and mat_orig
     * can be negative, so subtracting the CLIPPED reconstruction of a
     * zero-base pass would lose sign/magnitude information for negative
     * residuals. Using out_mat_raw avoids that: pred = cur_recon -
     * mat_orig_raw is exact for every pixel where cur_recon itself was
     * not clipped (the overwhelming majority of blocks at this QP).
     * Bounded, documented limitation: if the ORIGINAL reconstruction was
     * itself saturated (pred+mat_orig outside [0,255]), this recovers a
     * pred slightly off from the true value for that pixel only -- the
     * classification and any activation remain internally self-consistent
     * (both computed from the same recovered pred), so this cannot cause
     * a bitstream/reconstruction mismatch; it can only make the candidate
     * evaluation slightly conservative/imprecise for already-saturated
     * pixels (dark/bright extremes), which is exactly the content the
     * task asks to protect via low-frequency preservation anyway. */
    int mat_orig_raw[16];
    pixel dummy_out[16];
    /* skip_attenuation=1: cur[] is ALREADY the final, real-encode-vetted
     * coefficient set (already safely inside the decoder's reconstruction
     * range by construction -- the real encode already ran its own
     * attenuation loop against the TRUE prediction when it originally
     * produced these coefficients). Passing cur_recon (which already has
     * mat_orig added once) as "pred" here would make the oob check test
     * pred_true + 2*mat_orig instead of pred_true + mat_orig -- a
     * double-count that can spuriously trigger attenuation and corrupt the
     * recovered mat_orig_raw. Since re-attenuation is unneeded (cur is
     * already safe) and actively wrong here, this call skips the oob/
     * attenuation loop entirely and just reads mat[] from one direct pass. */
    mobi_act22_9_dequant_recon2( h, cur, i_qp, cur_recon, dummy_out, NULL, mat_orig_raw, 1 );
    pixel pred[16];
    for( int i = 0; i < 16; i++ )
    {
        int p = (int)cur_recon[i] - mat_orig_raw[i];
        pred[i] = (pixel)x264_clip3( p, 0, PIXEL_MAX );
    }

    double cur_sse = 0;
    for( int i = 0; i < 16; i++ )
    {
        int d = (int)cur_recon[i] - (int)fenc[i];
        cur_sse += (double)(d*d);
    }
    int cur_bits = mobi_act22_9_luma_mb_bits( h, -1, NULL, 0 );

    mobi_act22_9_cand_t cands[MOBI_ACT22_9_MAX_CAND];
    int nc = mobi_act22_9_gen_candidates( cur, cur_nnz, cands );

    int best_bits = cur_bits;
    double best_sse = cur_sse;
    int best_valid = 0;
    dctcoef best_coef[16]; int best_nnz = cur_nnz;
    pixel best_recon[16];
    const char *best_label = NULL;

    for( int ci = 0; ci < nc; ci++ )
    {
        mobi_act22_9_cand_t *c = &cands[ci];
        pixel cand_recon[16];
        dctcoef cand_final[16];
        mobi_act22_9_dequant_recon( h, c->coef, i_qp, pred, cand_recon, cand_final, NULL );

        double cand_sse = 0; int max_abs = 0;
        for( int i = 0; i < 16; i++ )
        {
            int d = (int)cand_recon[i] - (int)fenc[i];
            cand_sse += (double)(d*d);
            int ad = abs( (int)cand_recon[i] - (int)cur_recon[i] );
            if( ad > max_abs ) max_abs = ad;
        }
        int cand_nnz_final = 0;
        for( int zz = 0; zz < 16; zz++ ) if( cand_final[zz] ) cand_nnz_final++;

        int cand_bits = mobi_act22_9_luma_mb_bits( h, blk_idx, cand_final, cand_nnz_final );
        int bits_saved = cur_bits - cand_bits;

        int pixel_exact = 1;
        for( int i = 0; i < 16 && pixel_exact; i++ )
            if( cand_recon[i] != cur_recon[i] ) pixel_exact = 0;

        const char *classification;
        const char *reason = "";
        int exact_eligible = (c->label[0]=='z' && c->label[4]=='f') ? 1 : 0; /* "zero_full" only, per spec */
        if( pixel_exact && bits_saved > 0 )
            classification = "EXACT_WIN";
        else if( bits_saved > 0 && cand_sse <= cur_sse )
            classification = "STRICT_DOMINANCE";
        else if( bits_saved >= 0 && cand_sse < cur_sse )
            classification = "QUALITY_WIN";
        else if( bits_saved > 0 && cand_sse > cur_sse )
        {
            /* NEAR_LOSSLESS: fewer bits, tiny bounded distortion increase.
             * Bound: <=2 SSE units per pixel on average (32 total for a
             * 16-pixel block) -- conservative, documented in the report.
             * Not activatable in this phase (Phase 3 explicit rule). */
            if( (cand_sse - cur_sse) <= 32.0 )
                classification = "NEAR_LOSSLESS";
            else
            {
                classification = "REJECT";
                reason = "DISTORTION_TOO_LARGE";
            }
        }
        else
        {
            classification = "REJECT";
            reason = (bits_saved <= 0) ? "NO_BIT_SAVING" : "OTHER";
        }
        /* "zero_full" is only ever accepted (as EXACT_WIN) when it is
         * genuinely pixel-exact -- otherwise force REJECT regardless of
         * what the generic rule above computed, per the literal
         * instruction ("zero the full residual only when exact
         * reconstructed pixels are preserved"). */
        if( c->nnz == 0 && !(pixel_exact) )
        {
            classification = "REJECT";
            reason = "ZERO_FULL_NOT_PIXEL_EXACT";
        }

        int cbp_effect = 0; /* 0=unchanged, 1=group would clear */
        {
            int g = blk_idx & ~3;
            int any_left = 0;
            for( int i4 = 0; i4 < 4; i4++ )
            {
                int bi = g + i4;
                int nz = (bi == blk_idx) ? cand_nnz_final : h->mb.cache.non_zero_count[x264_scan8[bi]];
                if( nz ) any_left = 1;
            }
            int group_had_any = 0;
            for( int i4 = 0; i4 < 4; i4++ )
                if( h->mb.cache.non_zero_count[x264_scan8[g+i4]] ) group_had_any = 1;
            if( group_had_any && !any_left ) cbp_effect = 1;
        }

        if( sim_fp )
        {
            fprintf( sim_fp, "%d,%d,%d,%d,Y,%s,%u,%u,%d,%d,%d,%.1f,%.1f,%d,%d,%d,%d,%d,NONE,%d,%s,%s\n",
                     h->fdec->i_frame, h->mb.i_mb_x, h->mb.i_mb_y, blk_idx, c->label,
                     mobi_act22_9_coef_hash(cur), mobi_act22_9_coef_hash(c->coef),
                     cur_bits, cand_bits, bits_saved, cur_sse, cand_sse, max_abs, c->scan_pos,
                     cur_nnz, cand_nnz_final, cbp_effect, exact_eligible, classification, reason );
        }

        if( do_activate &&
            ( !strcmp(classification,"EXACT_WIN") || !strcmp(classification,"STRICT_DOMINANCE") || !strcmp(classification,"QUALITY_WIN") ) &&
            cand_bits < best_bits )
        {
            best_bits = cand_bits;
            best_sse = cand_sse;
            best_valid = 1;
            memcpy( best_coef, cand_final, sizeof(best_coef) );
            best_nnz = cand_nnz_final;
            memcpy( best_recon, cand_recon, sizeof(best_recon) );
            best_label = c->label;
        }
    }
    (void)best_sse; (void)best_label;

    if( do_activate && best_valid )
    {
        memcpy( h->dct.luma4x4[blk_idx], best_coef, sizeof(best_coef) );
        h->mb.cache.non_zero_count[i8] = (uint8_t)best_nnz;
        for( int y = 0; y < 4; y++ )
            for( int x = 0; x < 4; x++ )
                p_dst[y*FDEC_STRIDE+x] = best_recon[y*4+x];
        /* Recompute this block's 8x8 group's CBP bit from all 4 siblings
         * (only this one block's nnz could have changed). */
        int g = blk_idx & ~3;
        int any = 0;
        for( int i4 = 0; i4 < 4; i4++ )
            if( h->mb.cache.non_zero_count[x264_scan8[g+i4]] ) any = 1;
        if( any ) h->mb.i_cbp_luma |= 1 << (g>>2);
        else      h->mb.i_cbp_luma &= ~(1 << (g>>2));
    }
}

static void mobi_act22_9_rdo( x264_t *h )
{
    int sim_on = ( getenv("MOBI_ACT22_RDO_SIM") && atoi(getenv("MOBI_ACT22_RDO_SIM")) );
    int act_on = mobi_act22_9_activate_enabled();
    if( !sim_on && !act_on ) return;
    if( h->mb.i_type != P_L0 && h->mb.i_type != I_4x4 ) return;
    if( h->mb.i_type == P_L0 && h->mb.i_partition != D_16x16 ) return;
    if( h->mb.b_transform_8x8 ) return; /* no experimental-8x8 activation, ever */

    /* CONFIRMED BUG, PERMANENT FIX (ACT22.9 Phase 5 bug hunt): I_4x4's
     * intra prediction reads spatially-adjacent, potentially-already-
     * ACTIVATED blocks within the SAME frame (this MB's own earlier
     * blocks, or an earlier-processed neighboring MB) -- the per-block-
     * independent pred-recovery this evaluator uses does not re-derive
     * prediction against the post-activation neighbor state, so I_4x4
     * candidates were being accepted/applied against a stale prediction
     * basis. Isolation test (diagnostic env MOBI_ACT22_RDO_P_L0_ONLY,
     * evidence\act22_9_rdo_phase5_24f_fixed_20260822_114500\actPL0only_*)
     * confirmed this precisely: restricting ACTIVATION to P_L0 only
     * (P_L0's motion-compensated prediction source is the PRIOR frame,
     * unaffected by same-frame activations) eliminated the regression
     * entirely -- luma PSNR/SSIM versus the un-activated control actually
     * IMPROVED slightly (36.88->37.02 dB, SSIM 0.9724->0.9731) while still
     * saving 4.23% bytes. I_4x4 ACTIVATION is therefore PERMANENTLY
     * disabled here, not just diagnostic-flag-gated -- fixing it properly
     * would require re-deriving each I_4x4 block's prediction in true
     * decode order against already-activated neighbors, out of scope for
     * this act. SIMULATION still evaluates and records I_4x4 candidates
     * (real, honest data for future work); only ACTIVATION excludes them. */
    int activate_this_mb = act_on && ( h->mb.i_type == P_L0 );

    FILE *sim_fp = sim_on ? mobi_act22_9_sim_fp() : NULL;
    for( int blk = 0; blk < 16; blk++ )
        mobi_act22_9_eval_block( h, blk, h->mb.i_qp, sim_fp, activate_this_mb );
}
#endif /* !RDO_SKIP_BS */

#if !RDO_SKIP_BS
/* ============================================================================
 * ACT23 Phase 3: MobiClip-native coefficient trellis, P_L0 luma-only.
 *
 * Reuse-investigation verdict (see evidence\act23_trellis_design_*\
 * checkpoint_00_design.md for the full writeup): x264_quant_4x4_trellis was
 * read in full (encoder/rdo.c, quant_trellis_cabac ~line 642,
 * quant_trellis_cavlc ~line 920) before writing a single line here.
 * REJECTED for reuse: the CABAC path's entire state/edge-cost model is
 * CABAC adaptive-context machinery with no MobiClip counterpart (no
 * arithmetic coding at all in this format). The CAVLC path -- structurally
 * closer since it is VLC-table-based like MobiClip -- is, by x264's own
 * header comment on quant_trellis_cavlc, NOT actually a trellis: "this
 * 'trellis' isn't: it's just a QNS search", a greedy 2-roundings-per-coef
 * local search hardwired to H.264 CAVLC's five-part syntax (coeff_token,
 * total_zeros, run_before, all nC-neighbor-context-dependent) via
 * cavlc_block_residual_internal. MobiClip's actual residual writer,
 * encode_dct() (this file, line 627), is a table lookup per symbol with up
 * to two escape tiers and NO block-level joint symbol and NO cross-block
 * context at all -- confirmed by direct read, cross-validated against
 * ACT22.9's own comment on encode_dct's context-independence a few hundred
 * lines above. Net: reusing either x264 path would mean discarding its
 * actual algorithm and its actual cost oracle, i.e. a rewrite wearing a
 * reuse label, not a real adaptation. Building new, below.
 *
 * What IS reused, directly (not duplicated): mobi_act22_9_dequant_recon /
 * _dequant_recon2 (exact MobiClip dequant+IDCT+reconstruct) and
 * mobi_act22_9_luma_mb_bits (the scratch-writer whole-block exact bit
 * oracle) from the ACT22.9 block immediately above -- both are pure
 * functions of encoder state already proven correct there, no reason to
 * re-derive. Classification thresholds/labels and the env-gated
 * sim/activate/CSV shape are copied verbatim from mobi_act22_9_eval_block.
 * Scope guard is identical to ACT22.9's final safe scope: P_L0 D_16x16
 * only, b_transform_8x8 excluded, I_4x4 simulated-only-never-activated for
 * the same same-frame-neighbor-prediction reason ACT22.9 found and fixed
 * (true decode-order re-derivation is out of scope here too -- the user's
 * own later phase).
 *
 * Env vars (independent of ACT22.9's; mutual exclusion enforced at the top
 * of mobi_act23_trellis_rdo so the two ACTIVATE paths can never both mutate
 * the same block in one run, keeping each phase's contribution separately
 * attributable): MOBI_ACT23_TRELLIS_SIM[_OUT], MOBI_ACT23_TRELLIS_ENABLE.
 * ============================================================================ */

/* Direct arithmetic transcription of encode_dct()'s (this file, line 627)
 * per-symbol branch logic -- same reftable/r11A/r11B tables, same
 * direct/escape-1/escape-2/raw-literal tiers, in the same order -- rewritten
 * to return a bit count instead of calling bs_write. Provably bit-identical
 * to what encode_dct() would actually emit for this (val,skip,is_last)
 * triple since it walks the identical tables via the identical branches;
 * not a new approximation of the format. val must be > 0 (level 0 is never
 * itself an emitted symbol -- zeros are accounted for via skip). */
static int mobi_act23_symbol_bits( int val, int skip, int is_last, int table )
{
    const uint16_t *r11A = table == 1 ? vx2_table1_a : vx2_table0_a;
    const uint8_t  *r11B = table == 1 ? vx2_table1_b : vx2_table0_b;
    const int (*reftable)[64][2] = table == 1 ? vx2_table1_a_rev : vx2_table0_a_rev;

    if( val <= 31 )
    {
        int idx = reftable[val][skip][is_last];
        if( idx >= 0 )
            return r11A[idx] & 0xF;

        int newskip = skip - r11B[(val | (is_last << 6)) + 0x80];
        if( newskip >= 0 )
        {
            idx = reftable[val][newskip][is_last];
            if( idx >= 0 )
            {
                int esc_idx = reftable[0][0][0];
                return (r11A[esc_idx] & 0xF) + 2 + (r11A[idx] & 0xF);
            }
        }
    }
    {
        int newval = val - r11B[skip | (is_last << 6)];
        if( newval >= 0 && newval <= 31 )
        {
            int idx = reftable[newval][skip][is_last];
            if( idx >= 0 )
            {
                int esc_idx = reftable[0][0][0];
                return (r11A[esc_idx] & 0xF) + 1 + (r11A[idx] & 0xF);
            }
        }
    }
    {
        /* raw literal fallback: escape marker + 1(=1) + 1(=1) + last(1) +
         * skip(6) + level(12) = esc_nrbits + 21, matching encode_dct's
         * explicit: path exactly. */
        int esc_idx = reftable[0][0][0];
        return (r11A[esc_idx] & 0xF) + 21;
    }
}

typedef struct
{
    int64_t cost;
    int last_kept_pos;
    dctcoef coef[16];
} mobi_act23_cell_t;

/* Trellis-quantize one 4x4 luma block. cur[]/cur_nnz: current zigzag-order
 * coefficients (matches h->dct.luma4x4[idx][]) and their nonzero count.
 * table: encode_dct's table selector (0/1, I-slice vs P-slice). qstep_zz:
 * per-zigzag-position dequant weight, mobi_q4[qx][zz]<<(2+shift) -- same
 * values mobi_act22_9_dequant_recon2 computes, passed in zz order (not
 * remapped to natural order) since this DP works entirely in scan-position
 * space. lambda2: x264_lambda2_tab[h->mb.i_qp] (fixed-point <<8, per
 * common/tables.c:112 -- the same lambda domain already used elsewhere in
 * this codebase, e.g. macroblock.c:537, for plain-integer-bit RD costs, so
 * no rescale beyond the existing >>8 de-scale is needed).
 *
 * DP: for each of the nnz_found original nonzero positions, choose to drop
 * it to 0 or keep it at one of {orig-1, orig, orig+1} (covers "keep",
 * "reduce by one step", and "occasionally test the adjacent level" from
 * the spec; "zero the coefficient" is the drop option) -- an explicit
 * outer loop over "which position is the highest kept" (m) resolves the
 * is_last flag exactly (it's a fact about what's ABOVE a position), while
 * an inner forward sweep 0..m resolves skip exactly (a fact about what's
 * BELOW a position, i.e. distance since the nearest lower kept position) --
 * doing both in a single sweep direction isn't possible since they depend
 * on opposite directions; nnz_found is small (<=16) so the O(nnz^2) total
 * cost of trying every m is trivial. Each DP cell carries the actual
 * partial coefficient vector (copy-on-write, 16 ints) rather than
 * backpointers -- simpler to get right than backpointer reconstruction,
 * and cheap at this size.
 *
 * Honest, explicit design note (not silently assumed): "distortion" here
 * is a coefficient-domain quadratic proxy (weighted squared delta of the
 * dequantized coefficient, same shape x264's own CABAC trellis already
 * uses for the same reason), NOT a true joint pixel-domain SSE recomputed
 * via full IDCT at every DP state -- true pixel SSE is not separable
 * across scan positions (IDCT mixes every coefficient into every pixel),
 * so tracking it exactly at each intermediate DP state is not a
 * polynomial-time trellis at all. This proxy only steers the search. It
 * never decides acceptance: the caller re-verifies the DP's winning
 * candidate with the REAL dequant+IDCT+reconstruct+SSE and REAL
 * scratch-writer bit count before it can affect classification or
 * activation, exactly matching ACT22.9's own rigor at the decision
 * boundary. */
static int mobi_act23_trellis_search( const dctcoef *cur, int cur_nnz, int table,
                                       const int *qstep_zz, int lambda2,
                                       dctcoef *out_coef, int *out_nnz )
{
    if( cur_nnz <= 0 )
        return 0;

    int nz_pos[16], nnz_found = 0;
    for( int zz = 0; zz < 16; zz++ )
        if( cur[zz] ) nz_pos[nnz_found++] = zz;

    int64_t best_total_cost = INT64_MAX;
    dctcoef best_total_coef[16];
    int found_any = 0;

    for( int m = 0; m < nnz_found; m++ )
    {
        mobi_act23_cell_t prev;
        prev.cost = 0;
        prev.last_kept_pos = -1;
        memset( prev.coef, 0, sizeof(prev.coef) );

        int valid = 1;
        for( int j = 0; j <= m; j++ )
        {
            int P = nz_pos[j];
            int V = abs( cur[P] );
            int sign = cur[P] < 0 ? -1 : 1;
            int is_last = ( j == m );

            mobi_act23_cell_t best_here;
            best_here.cost = INT64_MAX;

            if( j != m )
                best_here = prev; /* "drop this coefficient to 0" -- not legal at the forced-kept position m */

            int mags[3], nmag = 0;
            mags[nmag++] = V;
            if( V > 1 ) mags[nmag++] = V - 1;
            mags[nmag++] = V + 1;

            for( int mi = 0; mi < nmag; mi++ )
            {
                int mval = mags[mi];
                if( mval <= 0 ) continue;
                int skip = P - prev.last_kept_pos - 1;
                if( skip < 0 || skip > 63 ) continue;
                int bits = mobi_act23_symbol_bits( mval, skip, is_last, table );
                int64_t dnew = (int64_t)(mval - V) * qstep_zz[P];
                int64_t distortion = dnew * dnew;
                int64_t cost = prev.cost + distortion + ( ( (int64_t)lambda2 * bits + 128 ) >> 8 );
                if( cost < best_here.cost )
                {
                    best_here.cost = cost;
                    best_here.last_kept_pos = P;
                    memcpy( best_here.coef, prev.coef, sizeof(best_here.coef) );
                    best_here.coef[P] = (dctcoef)( sign * mval );
                }
            }

            if( best_here.cost == INT64_MAX ) { valid = 0; break; }
            prev = best_here;
        }

        if( valid && prev.cost < best_total_cost )
        {
            best_total_cost = prev.cost;
            memcpy( best_total_coef, prev.coef, sizeof(best_total_coef) );
            found_any = 1;
        }
    }

    if( !found_any )
        return 0;

    memcpy( out_coef, best_total_coef, sizeof(best_total_coef) );
    int nnz = 0;
    for( int zz = 0; zz < 16; zz++ ) if( out_coef[zz] ) nnz++;
    *out_nnz = nnz;
    return 1;
}

static FILE *mobi_act23_sim_fp( void )
{
    static int enabled = -1;
    static FILE *fp = NULL;
    if( enabled < 0 )
    {
        const char *prefix = getenv( "MOBI_ACT23_TRELLIS_SIM" );
        enabled = ( prefix && atoi(prefix) ) ? 1 : 0;
        if( enabled )
        {
            char path[4096];
            const char *outpfx = getenv( "MOBI_ACT23_TRELLIS_SIM_OUT" );
            snprintf( path, sizeof(path), "%s_trellis.csv", outpfx ? outpfx : "mobi_act23" );
            fp = fopen( path, "w" );
            if( fp )
                fprintf( fp,
                    "frame_index,mb_x,mb_y,blk_idx,candidate_label,"
                    "cur_bits,cand_bits,bits_saved,cur_sse,cand_sse,max_abs_pixel_diff,"
                    "cur_nnz,cand_nnz,dp_predicted_bits,dp_bits_selfcheck_ok,"
                    "classification,rejection_reason\n" );
        }
        enabled = fp ? 1 : 0;
    }
    return enabled ? fp : NULL;
}

static int mobi_act23_activate_enabled( void )
{
    static int enabled = -1;
    if( enabled < 0 )
    {
        const char *v = getenv( "MOBI_ACT23_TRELLIS_ENABLE" );
        enabled = ( v && atoi(v) ) ? 1 : 0;
    }
    return enabled;
}

/* Evaluate + (optionally) activate the trellis for one eligible 4x4 luma
 * block. Structure mirrors mobi_act22_9_eval_block closely (same
 * pred-recovery technique, same classification thresholds) -- the only
 * real difference is candidate generation: two candidates instead of
 * ACT22.9's ~24 enumerated ones -- (1) the DP-trellis optimum, (2) an
 * explicit whole-block CBP-drop, evaluated the same way and put through
 * the same strict gate. This directly implements the spec's "after finding
 * the trellis-optimal set, jointly test whether the block can be dropped
 * from CBP entirely". */
static void mobi_act23_eval_block( x264_t *h, int blk_idx, int i_qp, FILE *sim_fp, int do_activate )
{
    int i8 = x264_scan8[blk_idx];
    int cur_nnz = h->mb.cache.non_zero_count[i8];
    if( !cur_nnz ) return;

    dctcoef cur[16];
    memcpy( cur, h->dct.luma4x4[blk_idx], sizeof(cur) );

    pixel *p_dst = &h->mb.pic.p_fdec[0][block_idx_xy_fdec[blk_idx]];
    pixel *p_src = &h->mb.pic.p_fenc[0][block_idx_xy_fenc[blk_idx]];
    pixel fenc[16], cur_recon[16];
    for( int y = 0; y < 4; y++ )
        for( int x = 0; x < 4; x++ )
        {
            fenc[y*4+x] = p_src[y*FENC_STRIDE+x];
            cur_recon[y*4+x] = p_dst[y*FDEC_STRIDE+x];
        }

    int mat_orig_raw[16];
    pixel dummy_out[16];
    mobi_act22_9_dequant_recon2( h, cur, i_qp, cur_recon, dummy_out, NULL, mat_orig_raw, 1 );
    pixel pred[16];
    for( int i = 0; i < 16; i++ )
    {
        int p = (int)cur_recon[i] - mat_orig_raw[i];
        pred[i] = (pixel)x264_clip3( p, 0, PIXEL_MAX );
    }

    double cur_sse = 0;
    for( int i = 0; i < 16; i++ )
    {
        int d = (int)cur_recon[i] - (int)fenc[i];
        cur_sse += (double)(d*d);
    }
    int cur_bits = mobi_act22_9_luma_mb_bits( h, -1, NULL, 0 );

    int qx = i_qp % 6;
    int shift = mobi_qyx( h );
    int qstep_zz[16];
    for( int zz = 0; zz < 16; zz++ )
        qstep_zz[zz] = mobi_q4[qx][zz] << (2 + shift);
    int lambda2 = x264_lambda2_tab[i_qp];
    int table = h->sh.i_type == SLICE_TYPE_I ? 1 : 0;

    typedef struct { const char *label; dctcoef coef[16]; int nnz; int dp_bits; } cand_t;
    cand_t cands[2];
    int nc = 0;

    dctcoef dp_coef[16]; int dp_nnz = 0;
    if( mobi_act23_trellis_search( cur, cur_nnz, table, qstep_zz, lambda2, dp_coef, &dp_nnz ) )
    {
        cand_t *c = &cands[nc++];
        c->label = "trellis";
        memcpy( c->coef, dp_coef, sizeof(c->coef) );
        c->nnz = dp_nnz;
        c->dp_bits = -1; /* self-check filled below once symbol costs can be summed identically to encode_dct's own traversal */
    }
    {
        cand_t *c = &cands[nc++];
        c->label = "cbp_drop";
        memset( c->coef, 0, sizeof(c->coef) );
        c->nnz = 0;
        c->dp_bits = -1;
    }

    int best_bits = cur_bits;
    double best_sse = cur_sse;
    int best_valid = 0;
    dctcoef best_coef[16]; int best_nnz = cur_nnz;
    pixel best_recon[16];

    for( int ci = 0; ci < nc; ci++ )
    {
        cand_t *c = &cands[ci];
        pixel cand_recon[16];
        dctcoef cand_final[16];
        mobi_act22_9_dequant_recon( h, c->coef, i_qp, pred, cand_recon, cand_final, NULL );

        double cand_sse = 0; int max_abs = 0;
        for( int i = 0; i < 16; i++ )
        {
            int d = (int)cand_recon[i] - (int)fenc[i];
            cand_sse += (double)(d*d);
            int ad = abs( (int)cand_recon[i] - (int)cur_recon[i] );
            if( ad > max_abs ) max_abs = ad;
        }
        int cand_nnz_final = 0;
        for( int zz = 0; zz < 16; zz++ ) if( cand_final[zz] ) cand_nnz_final++;

        int cand_bits = mobi_act22_9_luma_mb_bits( h, blk_idx, cand_final, cand_nnz_final );
        int bits_saved = cur_bits - cand_bits;

        /* DP self-check (trellis candidate only): sum this candidate's own
         * per-symbol costs via mobi_act23_symbol_bits and compare against
         * the real scratch-writer's measurement of the SAME coefficient
         * vector -- these must match exactly, since both walk the same
         * tables; any mismatch is a hard bug in the cost function or the
         * DP's skip/is_last bookkeeping, not a tuning issue. Reported, not
         * silently swallowed: logged to the sim CSV every time, and would
         * be an immediate red flag in the reconciliation gate. */
        int dp_predicted_bits = -1;
        int selfcheck_ok = 1;
        if( !strcmp( c->label, "trellis" ) )
        {
            int nzp[16], nf = 0;
            for( int zz = 0; zz < 16; zz++ ) if( cand_final[zz] ) nzp[nf++] = zz;
            dp_predicted_bits = 0;
            int prev_pos = -1;
            for( int k = 0; k < nf; k++ )
            {
                int P = nzp[k];
                int is_last = ( k == nf - 1 );
                int skip = P - prev_pos - 1;
                dp_predicted_bits += mobi_act23_symbol_bits( abs(cand_final[P]), skip, is_last, table );
                prev_pos = P;
            }
            /* cand_bits is the WHOLE-MB delta (includes this block's group
             * header re-emission and sibling blocks); isolate just this
             * block's own residual contribution by diffing against a
             * same-header baseline: re-measure with this block forced to
             * its OWN cand_final (already done, cand_bits) vs a version
             * with this block's nnz temporarily zero would double the
             * scratch-writer calls per candidate for no real gain here, so
             * the self-check instead validates against a direct
             * single-block encode_dct scratch call, matching mode/context
             * fully (no group-header/CBP ambiguity: table + coefficients
             * only). */
            {
                bs_t save_bs = h->out.bs;
                uint8_t scratch[512];
                bs_init( &h->out.bs, scratch, sizeof(scratch) );
                encode_dct( h, cand_final, 16, table );
                int real_bits = bs_pos( &h->out.bs );
                h->out.bs = save_bs;
                selfcheck_ok = ( real_bits == dp_predicted_bits );
                if( !selfcheck_ok )
                    x264_log( h, X264_LOG_ERROR,
                        "[ACT23_TRELLIS_SELFCHECK_MISMATCH] frame=%d mb=(%d,%d) blk=%d dp=%d real=%d\n",
                        h->fdec->i_frame, h->mb.i_mb_x, h->mb.i_mb_y, blk_idx, dp_predicted_bits, real_bits );
            }
        }

        int pixel_exact = 1;
        for( int i = 0; i < 16 && pixel_exact; i++ )
            if( cand_recon[i] != cur_recon[i] ) pixel_exact = 0;

        const char *classification;
        const char *reason = "";
        if( pixel_exact && bits_saved > 0 )
            classification = "EXACT_WIN";
        else if( bits_saved > 0 && cand_sse <= cur_sse )
            classification = "STRICT_DOMINANCE";
        else if( bits_saved >= 0 && cand_sse < cur_sse )
            classification = "QUALITY_WIN";
        else if( bits_saved > 0 && cand_sse > cur_sse )
        {
            if( (cand_sse - cur_sse) <= 32.0 )
                classification = "NEAR_LOSSLESS";
            else { classification = "REJECT"; reason = "DISTORTION_TOO_LARGE"; }
        }
        else { classification = "REJECT"; reason = (bits_saved <= 0) ? "NO_BIT_SAVING" : "OTHER"; }

        if( c->nnz == 0 && !pixel_exact )
        {
            classification = "REJECT";
            reason = "ZERO_FULL_NOT_PIXEL_EXACT";
        }
        if( !selfcheck_ok )
        {
            /* never allow a candidate whose own bit-cost model failed
             * self-verification to be considered, regardless of what the
             * classification above computed -- correctness over gain. */
            classification = "REJECT";
            reason = "DP_SELFCHECK_MISMATCH";
        }

        if( sim_fp )
        {
            fprintf( sim_fp, "%d,%d,%d,%d,%s,%d,%d,%d,%.1f,%.1f,%d,%d,%d,%d,%d,%s,%s\n",
                     h->fdec->i_frame, h->mb.i_mb_x, h->mb.i_mb_y, blk_idx, c->label,
                     cur_bits, cand_bits, bits_saved, cur_sse, cand_sse, max_abs,
                     cur_nnz, cand_nnz_final, dp_predicted_bits, selfcheck_ok,
                     classification, reason );
        }

        if( do_activate && selfcheck_ok &&
            ( !strcmp(classification,"EXACT_WIN") || !strcmp(classification,"STRICT_DOMINANCE") || !strcmp(classification,"QUALITY_WIN") ) &&
            cand_bits < best_bits )
        {
            best_bits = cand_bits;
            best_sse = cand_sse;
            best_valid = 1;
            memcpy( best_coef, cand_final, sizeof(best_coef) );
            best_nnz = cand_nnz_final;
            memcpy( best_recon, cand_recon, sizeof(best_recon) );
        }
    }
    (void)best_sse;

    if( do_activate && best_valid )
    {
        memcpy( h->dct.luma4x4[blk_idx], best_coef, sizeof(best_coef) );
        h->mb.cache.non_zero_count[i8] = (uint8_t)best_nnz;
        for( int y = 0; y < 4; y++ )
            for( int x = 0; x < 4; x++ )
                p_dst[y*FDEC_STRIDE+x] = best_recon[y*4+x];
        int g = blk_idx & ~3;
        int any = 0;
        for( int i4 = 0; i4 < 4; i4++ )
            if( h->mb.cache.non_zero_count[x264_scan8[g+i4]] ) any = 1;
        if( any ) h->mb.i_cbp_luma |= 1 << (g>>2);
        else      h->mb.i_cbp_luma &= ~(1 << (g>>2));
    }
}

static void mobi_act23_trellis_rdo( x264_t *h )
{
    int sim_on = ( getenv("MOBI_ACT23_TRELLIS_SIM") && atoi(getenv("MOBI_ACT23_TRELLIS_SIM")) );
    int act_on = mobi_act23_activate_enabled();
    if( !sim_on && !act_on ) return;
    /* mutual exclusion with ACT22.9's own activation -- never stack both on
     * the same block in the same run, see header comment above. */
    if( act_on && mobi_act22_9_activate_enabled() ) return;
    if( h->mb.i_type != P_L0 && h->mb.i_type != I_4x4 ) return;
    if( h->mb.i_type == P_L0 && h->mb.i_partition != D_16x16 ) return;
    if( h->mb.b_transform_8x8 ) return;

    int activate_this_mb = act_on && ( h->mb.i_type == P_L0 );

    FILE *sim_fp = sim_on ? mobi_act23_sim_fp() : NULL;
    for( int blk = 0; blk < 16; blk++ )
        mobi_act23_eval_block( h, blk, h->mb.i_qp, sim_fp, activate_this_mb );
}
#endif /* !RDO_SKIP_BS */

/*****************************************************************************
 * x264_macroblock_write:
 *****************************************************************************/
void x264_macroblock_write_cavlc( x264_t *h )
{
    bs_t *s = &h->out.bs;
    const int i_mb_type = h->mb.i_type;
    int plane_count = CHROMA444 ? 3 : 1;
    int chroma = !CHROMA444;
#if RDO_SKIP_BS
    s->i_bits_encoded = 0;
#else
    /* ACT22.9 Phase 4 activation must run BEFORE the real write below so
     * that encode_p_block()/encode_i_block() naturally emit whatever this
     * decided. Simulation-only mode (MOBI_ACT22_RDO_SIM without ACTIVATE)
     * also runs here since dct.luma4x4/cache state is already final for
     * this MB (macroblock.c's encode already ran) -- it is read-only and
     * changes nothing. Guarded to !RDO_SKIP_BS for the same established
     * reason as every other ACT22.x hook in this file. */
    mobi_act22_9_rdo( h );
    mobi_act23_trellis_rdo( h );
    mobi_act24_plsplit_rdo( h );

    /* ACT22.1B rate-model bias trace, Hook B entry capture. Guarded to
     * !RDO_SKIP_BS: rdo.c re-includes this whole file with
     * RDO_SKIP_BS=1 and x264_macroblock_write_cavlc macro-renamed to a
     * static RD-trial variant (see encoder/rdo.c ~line 52) that is called
     * many times per MB during mode decision and never writes real bits
     * (bs_write* are redefined to just tally s->i_bits_encoded). This trace
     * must only observe the single real, final write per MB -- so it is
     * compiled out entirely in that RDO_SKIP_BS=1 translation unit. */
    const int _act22_bits_before = bs_pos( s );
    const int i_mb_pos_start = bs_pos( s );
    int       i_mb_pos_tex;
#endif

#if !RDO_SKIP_BS
    /*if( i_mb_type == I_PCM )
    {
        static const uint8_t i_offsets[3] = {5,23,0};
        uint8_t *p_start = s->p_start;
        bs_write_ue( s, i_offsets[h->sh.i_type] + 25 );
        i_mb_pos_tex = bs_pos( s );
        h->stat.frame.i_mv_bits += i_mb_pos_tex - i_mb_pos_start;

        bs_align_0( s );

        for( int p = 0; p < plane_count; p++ )
            for( int i = 0; i < 256; i++ )
                bs_write( s, BIT_DEPTH, h->mb.pic.p_fenc[p][i] );
        if( chroma )
            for( int ch = 1; ch < 3; ch++ )
                for( int i = 0; i < 16>>CHROMA_V_SHIFT; i++ )
                    for( int j = 0; j < 8; j++ )
                        bs_write( s, BIT_DEPTH, h->mb.pic.p_fenc[ch][i*FENC_STRIDE+j] );

        bs_init( s, s->p, s->p_end - s->p );
        s->p_start = p_start;

        h->stat.frame.i_tex_bits += bs_pos(s) - i_mb_pos_tex;
        return;
    }*/
#endif
	if (h->param.i_mobiclip) {
		uint8_t mobi_pre_backup[32];
		if (RDO_SKIP_BS)
			memcpy(mobi_pre_backup, h->mobi_pre, sizeof(h->mobi_pre));

		if (h->sh.i_type == SLICE_TYPE_P)
			encode_p_block(h);
		else //if (h->sh.i_type == SLICE_TYPE_I)
			encode_i_block(h);

		if (RDO_SKIP_BS)
			memcpy(h->mobi_pre, mobi_pre_backup, sizeof(h->mobi_pre));
	} else {
		/* Standard H.264 CAVLC macroblock write path */
		if( h->sh.i_type == SLICE_TYPE_P )
			cavlc_mb_header_p( h, i_mb_type, chroma );
		else if( h->sh.i_type == SLICE_TYPE_B )
			cavlc_mb_header_b( h, i_mb_type, chroma );
		else //if( h->sh.i_type == SLICE_TYPE_I )
			cavlc_mb_header_i( h, i_mb_type, 0, chroma );

#if !RDO_SKIP_BS
		i_mb_pos_tex = bs_pos( s );
		h->stat.frame.i_mv_bits += i_mb_pos_tex - i_mb_pos_start;
#endif

		if( i_mb_type != I_16x16 )
			bs_write_ue( s, cbp_to_golomb[chroma][IS_INTRA(i_mb_type)][(h->mb.i_cbp_chroma << 4)|h->mb.i_cbp_luma] );

		if( x264_mb_transform_8x8_allowed( h ) && h->mb.i_cbp_luma )
			bs_write1( s, h->mb.b_transform_8x8 );

		if( i_mb_type == I_16x16 )
		{
			cavlc_qp_delta( h );
			for( int p = 0; p < plane_count; p++ )
			{
				x264_cavlc_block_residual( h, DCT_LUMA_DC, LUMA_DC+p, h->dct.luma16x16_dc[p] );
				if( h->mb.i_cbp_luma )
					for( int i = p*16; i < p*16+16; i++ )
						x264_cavlc_block_residual( h, DCT_LUMA_AC, i, h->dct.luma4x4[i]+1 );
			}
		}
		else if( h->mb.i_cbp_luma | h->mb.i_cbp_chroma )
		{
			cavlc_qp_delta( h );
			cavlc_macroblock_luma_residual( h, plane_count );
		}
		if( h->mb.i_cbp_chroma )
		{
			x264_cavlc_block_residual( h, DCT_CHROMA_DC, CHROMA_DC+0, h->dct.chroma_dc[0] );
			x264_cavlc_block_residual( h, DCT_CHROMA_DC, CHROMA_DC+1, h->dct.chroma_dc[1] );
			if( h->mb.i_cbp_chroma == 2 )
			{
				int step = 8 << CHROMA_V_SHIFT;
				for( int i = 16; i < 3*16; i += step )
					for( int j = i; j < i+4; j++ )
						x264_cavlc_block_residual( h, DCT_CHROMA_AC, j, h->dct.luma4x4[j]+1 );
			}
		}
#if !RDO_SKIP_BS
		h->stat.frame.i_tex_bits += bs_pos(s) - i_mb_pos_tex;
#endif
	}

#if !RDO_SKIP_BS
    /* ACT22.1B rate-model bias trace, Hook B -- see mobi_act22_rate_trace_writer()
     * above. Single end-of-function point (no early returns in this function);
     * h->mb.* is fully finalized by the write path above. Read-only, no-op
     * unless MOBI_ACT22_RATE_TRACE is set. Guarded to !RDO_SKIP_BS for the
     * same reason as the entry capture above -- only the real, final write
     * per MB is recorded, not RD-trial calls. */
    mobi_act22_rate_trace_writer( h, bs_pos( s ) - _act22_bits_before );

    /* ACT22.3 prediction-refinement simulation -- see mobi_act22_3_sim()
     * above. Runs after the real MV/residual bits for this MB have already
     * been written to h->out.bs; only touches a throwaway scratch bs_t and
     * snapshotted/restored MB state. No-op unless MOBI_ACT22_3_SIM is set. */
    mobi_act22_3_sim( h );
#endif
}

#if RDO_SKIP_BS
/*****************************************************************************
 * RD only; doesn't generate a valid bitstream
 * doesn't write cbp or chroma dc (I don't know how much this matters)
 * doesn't write ref (never varies between calls, so no point in doing so)
 * only writes subpartition for p8x8, needed for sub-8x8 mode decision RDO
 * works on all partition sizes except 16x16
 *****************************************************************************/
static int partition_size_cavlc( x264_t *h, int i8, int i_pixel )
{
    bs_t *s = &h->out.bs;
    const int i_mb_type = h->mb.i_type;
    int b_8x16 = h->mb.i_partition == D_8x16;
    int plane_count = CHROMA444 ? 3 : 1;
    int j;

    h->out.bs.i_bits_encoded = 0;

    if( i_mb_type == P_8x8 )
    {
        cavlc_8x8_mvd( h, i8 );
        bs_write_ue( s, subpartition_p_to_golomb[ h->mb.i_sub_partition[i8] ] );
    }
    else if( i_mb_type == P_L0 )
        cavlc_mvd( h, 0, 4*i8, 4>>b_8x16 );

    for( j = (i_pixel < PIXEL_8x8); j >= 0; j-- )
    {
        for( int p = 0; p < plane_count; p++ )
            cavlc_partition_luma_residual( h, i8, p );
        if( h->mb.i_cbp_chroma )
        {
            if( CHROMA_FORMAT == CHROMA_422 )
            {
                int offset = (5*i8) & 0x09;
                x264_cavlc_block_residual( h, DCT_CHROMA_AC, 16+offset, h->dct.luma4x4[16+offset]+1 );
                x264_cavlc_block_residual( h, DCT_CHROMA_AC, 18+offset, h->dct.luma4x4[18+offset]+1 );
                x264_cavlc_block_residual( h, DCT_CHROMA_AC, 32+offset, h->dct.luma4x4[32+offset]+1 );
                x264_cavlc_block_residual( h, DCT_CHROMA_AC, 34+offset, h->dct.luma4x4[34+offset]+1 );
            }
            else
            {
                x264_cavlc_block_residual( h, DCT_CHROMA_AC, 16+i8, h->dct.luma4x4[16+i8]+1 );
                x264_cavlc_block_residual( h, DCT_CHROMA_AC, 32+i8, h->dct.luma4x4[32+i8]+1 );
            }
        }
        i8 += x264_pixel_size[i_pixel].h >> 3;
    }

    return h->out.bs.i_bits_encoded;
}

static int subpartition_size_cavlc( x264_t *h, int i4, int i_pixel )
{
    int plane_count = CHROMA444 ? 3 : 1;
    int b_8x4 = i_pixel == PIXEL_8x4;
    h->out.bs.i_bits_encoded = 0;
    cavlc_mvd( h, 0, i4, 1+b_8x4 );
    for( int p = 0; p < plane_count; p++ )
    {
        x264_cavlc_block_residual( h, DCT_LUMA_4x4, p*16+i4, h->dct.luma4x4[p*16+i4] );
        if( i_pixel != PIXEL_4x4 )
            x264_cavlc_block_residual( h, DCT_LUMA_4x4, p*16+i4+2-b_8x4, h->dct.luma4x4[p*16+i4+2-b_8x4] );
    }

    return h->out.bs.i_bits_encoded;
}

/* V7 opt-in: use the MobiClip VLC mode alphabet when estimating the
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
}

static int partition_i8x8_size_cavlc( x264_t *h, int i8, int i_mode )
{
    int plane_count = CHROMA444 ? 3 : 1;
    h->out.bs.i_bits_encoded = cavlc_intra4x4_pred_size( h, 4*i8, i_mode );
    //bs_write_ue( &h->out.bs, cbp_to_golomb[!CHROMA444][1][(h->mb.i_cbp_chroma << 4)|h->mb.i_cbp_luma] );
	uint8_t mask =
		(!!h->mb.cache.non_zero_count[x264_scan8[0 * 4]]) |
		((!!h->mb.cache.non_zero_count[x264_scan8[1 * 4]]) << 1) |
		((!!h->mb.cache.non_zero_count[x264_scan8[2 * 4]]) << 2) |
		((!!h->mb.cache.non_zero_count[x264_scan8[3 * 4]]) << 3);
	bs_write_ue(&h->out.bs, block_mask_to_golomb_table[(!!h->mb.cache.non_zero_count[x264_scan8[16 + 1 * 16]] << 5) | (!!h->mb.cache.non_zero_count[x264_scan8[16 + 0 * 16]] << 4) | mask]);
	if (h->mb.cache.non_zero_count[x264_scan8[i8 * 4]])
	{
		bs_write1(&h->out.bs, 1);//don't subdivide into 4x4
		h->mb.cache.non_zero_count[x264_scan8[i8 * 4]] = encode_dct(h, h->dct.luma8x8[i8], 64, h->sh.i_type == SLICE_TYPE_I ? 1 : 0);
	}	
	//for( int p = 0; p < plane_count; p++ )
    //    cavlc_partition_luma_residual( h, i8, p );
    return h->out.bs.i_bits_encoded;
}

static int partition_i4x4_size_cavlc( x264_t *h, int i4, int i_mode )
{
    int plane_count = CHROMA444 ? 3 : 1;
    h->out.bs.i_bits_encoded = cavlc_intra4x4_pred_size( h, i4, i_mode );
	if (h->mb.cache.non_zero_count[x264_scan8[i4]])
		h->mb.cache.non_zero_count[x264_scan8[i4]] = encode_dct(h, h->dct.luma4x4[i4], 16, h->sh.i_type == SLICE_TYPE_I ? 1 : 0);
	//for( int p = 0; p < plane_count; p++ )
    //    x264_cavlc_block_residual( h, DCT_LUMA_4x4, p*16+i4, h->dct.luma4x4[p*16+i4] );
    return h->out.bs.i_bits_encoded;
}

static int chroma_size_cavlc( x264_t *h )
{
	h->out.bs.i_bits_encoded = 3;//bs_size_ue( x264_mb_chroma_pred_mode_fix[h->mb.i_chroma_pred_mode] );
    /*if( h->mb.i_cbp_chroma )
    {
        x264_cavlc_block_residual( h, DCT_CHROMA_DC, CHROMA_DC+0, h->dct.chroma_dc[0] );
        x264_cavlc_block_residual( h, DCT_CHROMA_DC, CHROMA_DC+1, h->dct.chroma_dc[1] );

        if( h->mb.i_cbp_chroma == 2 )
        {
            int step = 8 << CHROMA_V_SHIFT;
            for( int i = 16; i < 3*16; i += step )
                for( int j = i; j < i+4; j++ )
                    x264_cavlc_block_residual( h, DCT_CHROMA_AC, j, h->dct.luma4x4[j]+1 );
        }
    }*/
	//todo: write plane params here when implemented and mode == 2
	int cf = h->param.b_moflex ? 0 : 1; /* chroma idx written first  */
	int cs = h->param.b_moflex ? 1 : 0; /* chroma idx written second */
	int planes[2] = {cf, cs};

	for (int i = 0; i < 2; i++)
	{
		int p = planes[i];
		if (h->mb.cache.non_zero_count[x264_scan8[16 + p * 16]])
		{
			bs_write1(&h->out.bs, 1);//don't subdivide into 4x4
			h->mb.cache.non_zero_count[x264_scan8[16 + p * 16]] = encode_dct(h, h->dct.luma8x8[4 + 4 * p], 64, h->sh.i_type == SLICE_TYPE_I ? 1 : 0);
		}
	}
    return h->out.bs.i_bits_encoded;
}
#endif
