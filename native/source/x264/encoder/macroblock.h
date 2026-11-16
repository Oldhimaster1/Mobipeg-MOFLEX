/*****************************************************************************
 * macroblock.h: macroblock encoding
 *****************************************************************************
 * Copyright (C) 2003-2025 x264 project
 *
 * Authors: Loren Merritt <lorenm@u.washington.edu>
 *          Laurent Aimar <fenrir@via.ecp.fr>
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

#ifndef X264_ENCODER_MACROBLOCK_H
#define X264_ENCODER_MACROBLOCK_H

#include "common/macroblock.h"
/* NOTE (R1 release cleanup): the banned/parked luma-8x8 experiment's header
 * ("mobi_luma8x8_q44.h") was included here in the research worktree but
 * nothing in this file or macroblock.c actually references any identifier
 * from it (verified by grep before removing) -- it was vestigial. Luma 8x8
 * remains untouched and unshipped; see AUTHORITATIVE ENCODER STATE / the
 * consolidation doc's banned-topics list. Not re-included in the release tree.
 */

/* Step-B/chroma-deadzone/activation-audit coefficient-block capture
 * (coeff_rd_audit phase). Read-only, gated behind MOBI_COEFF_DUMP (unset
 * by default => zero behavioral change). Dumps FINAL coded coefficients,
 * the prediction pixels the block was reconstructed against, AND the true
 * source (fenc) pixels -- needed as ground truth for the 0->+/-1 activation
 * audit, which must judge whether activating a coefficient moves the
 * reconstruction TOWARD the real source, not merely changes it. */
static ALWAYS_INLINE void mobi_coeff_dump( x264_t *h, int plane, int b_inter, int qp,
                                            int size, const dctcoef *coefs, const pixel *pred,
                                            const pixel *fenc )
{
    static int enabled = -1;
    static FILE *fp = NULL;
    if( enabled < 0 )
    {
        const char *path = getenv( "MOBI_COEFF_DUMP" );
        enabled = path ? 1 : 0;
        if( enabled ) fp = fopen( path, "a" );
        enabled = fp ? 1 : 0;
    }
    if( !enabled ) return;
    int table = h->sh.i_type == SLICE_TYPE_I ? 1 : 0;
    fprintf( fp, "%d %d %d %d %d %d %d", h->mb.i_mb_x, h->mb.i_mb_y, plane, b_inter, qp, table, size );
    for( int i = 0; i < size; i++ ) fprintf( fp, " %d", coefs[i] );
    for( int i = 0; i < size; i++ ) fprintf( fp, " %d", (int)pred[i] );
    for( int i = 0; i < size; i++ ) fprintf( fp, " %d", (int)fenc[i] );
    fprintf( fp, "\n" );
}

/* Mobiclip quantization tables — used by custom quantizer to match decoder.
 * quant4x4_tab/q8 match the decoder's dequant tables exactly. */
static const uint8_t mobi_zigzag4x4[16] =
    { 0, 4, 1, 2, 5, 8, 12, 9, 6, 3, 7, 10, 13, 14, 11, 15 };
static const uint8_t mobi_zigzag8x8[64] =
    { 0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5,
     12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28,
     35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51,
     58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63 };
static const uint8_t mobi_q4[6][16] = {
    {10,13,13,10,16,10,13,13,13,13,16,10,16,13,13,16},
    {11,14,14,11,18,11,14,14,14,14,18,11,18,14,14,18},
    {13,16,16,13,20,13,16,16,16,16,20,13,20,16,16,20},
    {14,18,18,14,23,14,18,18,18,18,23,14,23,18,18,23},
    {16,20,20,16,25,16,20,20,20,20,25,16,25,20,20,25},
    {18,23,23,18,29,18,23,23,23,23,29,18,29,23,23,29},
};
static const uint8_t mobi_q8[6][64] = {
    {0x14,0x13,0x13,0x19,0x12,0x19,0x13,0x18,0x18,0x13,0x14,0x12,0x20,0x12,0x14,0x13,0x13,0x18,0x18,0x13,0x13,0x19,0x12,0x19,0x12,0x19,0x12,0x19,0x13,0x18,0x18,0x13,0x13,0x18,0x18,0x13,0x12,0x20,0x12,0x14,0x12,0x20,0x12,0x18,0x18,0x13,0x13,0x18,0x18,0x12,0x19,0x12,0x19,0x12,0x13,0x18,0x18,0x13,0x12,0x20,0x12,0x18,0x18,0x12},
    {0x16,0x15,0x15,0x1C,0x13,0x1C,0x15,0x1A,0x1A,0x15,0x16,0x13,0x23,0x13,0x16,0x15,0x15,0x1A,0x1A,0x15,0x15,0x1C,0x13,0x1C,0x13,0x1C,0x13,0x1C,0x15,0x1A,0x1A,0x15,0x15,0x1A,0x1A,0x15,0x13,0x23,0x13,0x16,0x13,0x23,0x13,0x1A,0x1A,0x15,0x15,0x1A,0x1A,0x13,0x1C,0x13,0x1C,0x13,0x15,0x1A,0x1A,0x15,0x13,0x23,0x13,0x1A,0x1A,0x13},
    {0x1A,0x18,0x18,0x21,0x17,0x21,0x18,0x1F,0x1F,0x18,0x1A,0x17,0x2A,0x17,0x1A,0x18,0x18,0x1F,0x1F,0x18,0x18,0x21,0x17,0x21,0x17,0x21,0x17,0x21,0x18,0x1F,0x1F,0x18,0x18,0x1F,0x1F,0x18,0x17,0x2A,0x17,0x1A,0x17,0x2A,0x17,0x1F,0x1F,0x18,0x18,0x1F,0x1F,0x17,0x21,0x17,0x21,0x17,0x18,0x1F,0x1F,0x18,0x17,0x2A,0x17,0x1F,0x1F,0x17},
    {0x1C,0x1A,0x1A,0x23,0x19,0x23,0x1A,0x21,0x21,0x1A,0x1C,0x19,0x2D,0x19,0x1C,0x1A,0x1A,0x21,0x21,0x1A,0x1A,0x23,0x19,0x23,0x19,0x23,0x19,0x23,0x1A,0x21,0x21,0x1A,0x1A,0x21,0x21,0x1A,0x19,0x2D,0x19,0x1C,0x19,0x2D,0x19,0x21,0x21,0x1A,0x1A,0x21,0x21,0x19,0x23,0x19,0x23,0x19,0x1A,0x21,0x21,0x1A,0x19,0x2D,0x19,0x21,0x21,0x19},
    {0x20,0x1E,0x1E,0x28,0x1C,0x28,0x1E,0x26,0x26,0x1E,0x20,0x1C,0x33,0x1C,0x20,0x1E,0x1E,0x26,0x26,0x1E,0x1E,0x28,0x1C,0x28,0x1C,0x28,0x1C,0x28,0x1E,0x26,0x26,0x1E,0x1E,0x26,0x26,0x1E,0x1C,0x33,0x1C,0x20,0x1C,0x33,0x1C,0x26,0x26,0x1E,0x1E,0x26,0x26,0x1C,0x28,0x1C,0x28,0x1C,0x1E,0x26,0x26,0x1E,0x1C,0x33,0x1C,0x26,0x26,0x1C},
    {0x24,0x22,0x22,0x2E,0x20,0x2E,0x22,0x2B,0x2B,0x22,0x24,0x20,0x3A,0x20,0x24,0x22,0x22,0x2B,0x2B,0x22,0x22,0x2E,0x20,0x2E,0x20,0x2E,0x20,0x2E,0x22,0x2B,0x2B,0x22,0x22,0x2B,0x2B,0x22,0x20,0x3A,0x20,0x24,0x20,0x3A,0x20,0x2B,0x2B,0x22,0x22,0x2B,0x2B,0x20,0x2E,0x20,0x2E,0x20,0x22,0x2B,0x2B,0x22,0x20,0x3A,0x20,0x2B,0x2B,0x20},
};
static const uint8_t mobi_q8_chroma[6][64] = {
    {0x14,0x13,0x13,0x19,0x12,0x19,0x13,0x18,0x18,0x13,0x14,0x12,0x20,0x12,0x14,0x13,0x13,0x18,0x18,0x13,0x13,0x19,0x12,0x19,0x12,0x19,0x12,0x19,0x13,0x18,0x18,0x13,0x13,0x18,0x18,0x13,0x12,0x20,0x12,0x14,0x12,0x20,0x12,0x18,0x18,0x13,0x13,0x18,0x18,0x12,0x19,0x12,0x19,0x12,0x13,0x18,0x18,0x13,0x12,0x20,0x12,0x18,0x18,0x12},
    {0x16,0x15,0x15,0x1C,0x13,0x1C,0x15,0x1A,0x1A,0x15,0x16,0x13,0x23,0x13,0x16,0x15,0x15,0x1A,0x1A,0x15,0x15,0x1C,0x13,0x1C,0x13,0x1C,0x13,0x1C,0x15,0x1A,0x1A,0x15,0x15,0x1A,0x1A,0x15,0x13,0x23,0x13,0x16,0x13,0x23,0x13,0x1A,0x1A,0x15,0x15,0x1A,0x1A,0x13,0x1C,0x13,0x1C,0x13,0x15,0x1A,0x1A,0x15,0x13,0x23,0x13,0x1A,0x1A,0x13},
    {0x1A,0x18,0x18,0x21,0x17,0x21,0x18,0x1F,0x1F,0x18,0x1A,0x17,0x2A,0x17,0x1A,0x18,0x18,0x1F,0x1F,0x18,0x18,0x21,0x17,0x21,0x17,0x21,0x17,0x21,0x18,0x1F,0x1F,0x18,0x18,0x1F,0x1F,0x18,0x17,0x2A,0x17,0x1A,0x17,0x2A,0x17,0x1F,0x1F,0x18,0x18,0x1F,0x1F,0x17,0x21,0x17,0x21,0x17,0x18,0x1F,0x1F,0x18,0x17,0x2A,0x17,0x1F,0x1F,0x17},
    {0x1C,0x1A,0x1A,0x23,0x19,0x23,0x1A,0x21,0x21,0x1A,0x1C,0x19,0x2D,0x19,0x1C,0x1A,0x1A,0x21,0x21,0x1A,0x1A,0x23,0x19,0x23,0x19,0x23,0x19,0x23,0x1A,0x21,0x21,0x1A,0x1A,0x21,0x21,0x1A,0x19,0x2D,0x19,0x1C,0x19,0x2D,0x19,0x21,0x21,0x1A,0x1A,0x21,0x21,0x19,0x23,0x19,0x23,0x19,0x1A,0x21,0x21,0x1A,0x19,0x2D,0x19,0x21,0x21,0x19},
    {0x20,0x1E,0x1E,0x28,0x1C,0x28,0x1E,0x26,0x26,0x1E,0x20,0x1C,0x33,0x1C,0x20,0x1E,0x1E,0x26,0x26,0x1E,0x1E,0x28,0x1C,0x28,0x1C,0x28,0x1C,0x28,0x1E,0x26,0x26,0x1E,0x1E,0x26,0x26,0x1E,0x1C,0x33,0x1C,0x20,0x1C,0x33,0x1C,0x26,0x26,0x1E,0x1E,0x26,0x26,0x1C,0x28,0x1C,0x28,0x1C,0x1E,0x26,0x26,0x1E,0x1C,0x33,0x1C,0x26,0x26,0x1C},
    {0x24,0x22,0x22,0x2E,0x20,0x2E,0x22,0x2B,0x2B,0x22,0x24,0x20,0x3A,0x20,0x24,0x22,0x22,0x2B,0x2B,0x22,0x22,0x2E,0x20,0x2E,0x20,0x2E,0x20,0x2E,0x22,0x2B,0x2B,0x22,0x22,0x2B,0x2B,0x22,0x20,0x3A,0x20,0x24,0x20,0x3A,0x20,0x2B,0x2B,0x22,0x22,0x2B,0x2B,0x20,0x2E,0x20,0x2E,0x20,0x22,0x2B,0x2B,0x22,0x20,0x3A,0x20,0x2B,0x2B,0x20},
};

/* Mobiclip-aware quantizer: rounds to nearest, matching decoder's dequant.
 * The decoder does: mat[ztab[pos]] = level * (quant_tab[qx][pos] << qy)
 * So quantizer step = quant_tab[qx][pos] << qy. */
/* Extra quantizer coarseness for Mobiclip: total qy = 2 + MOBI_QYX.  qy=2
 * (MOBI_QYX=0) is the finest tier and exactly reproduces the original
 * bit-exact behaviour.  Higher values coarsen the quantization (smaller
 * files, lower quality) and are applied identically to the forward quant,
 * the reconstruction, and the header quantizer so enc/dec stay bit-exact.
 * The DEFAULT is 1: combined with the inter deadzone (see mobi_round_off)
 * this keeps temporal flicker near source level at a size comparable to
 * coarser settings.  Raise MOBI_QYX for smaller files (more flicker) or set
 * MOBI_QYX=0 for visually-lossless/bit-exact. */
static ALWAYS_INLINE int mobi_qyx( x264_t *h )
{
    /* V14 opt-in true picture-level MobiClip quantizer. The existing fixed
     * QY implementation cannot represent x264's changing rate-control QP:
     * it emits only qx=QP%6 while QY never changes. But the MobiClip format
     * already supports per-P-frame signed Q deltas! Under this opt-in mode,
     * use Q=sh.i_qp and derive qy=Q/6. Restrict encoder invocation to
     * picture-uniform QP (--aq-mode 0): the decoder has no per-MB QP field.
     * Without this flag the entire V12/V13 fixed-Q behaviour is unchanged.
     */
    static int frame_adapt = -1;
    if( frame_adapt < 0 )
    {
        const char *e = getenv("MOBI_V14_FRAME_Q");
        frame_adapt = e && atoi(e) ? 1 : 0;
    }
    if( frame_adapt )
        return x264_clip3( h->sh.i_qp/6 - 2, 0, 24 );
    int v = h->param.i_mobi_qyx;
    if( v == -1 ) { const char *e = getenv("MOBI_QYX"); v = e ? atoi(e) : 1; if( v < 0 ) v = 0; }
    return v;
}
/* Rounding offset for quantization.  level = (coef + off)/step, so the
 * threshold to reach level 1 is (step - off).  Round-to-nearest uses off =
 * step/2 (threshold step/2).  For INTER residual we instead use a deadzone
 * (smaller off -> higher threshold) so the small, noisy coefficients of
 * near-static blocks round to zero *consistently* every frame instead of
 * flipping between 0 and +/-1 -> kills temporal flicker/jitter and shrinks
 * files.  This is purely an encoder decision: the decoder reconstructs
 * level*step regardless, so it stays fully bit-compatible.
 *   MOBI_DZ in [1..8] scales the inter offset as step*MOBI_DZ/16
 *   (8 = round-to-nearest/no deadzone, default 5 ~= threshold 0.69*step). */
static ALWAYS_INLINE int mobi_round_off( x264_t *h, int step, int b_intra )
{
    if( b_intra )
        return step >> 1;
    static int dz = -1;
    if( dz < 0 ) { const char *e = getenv("MOBI_DZ"); dz = e ? atoi(e) : 5; if( dz < 1 ) dz = 1; if( dz > 8 ) dz = 8; }
    return step * dz / 16;
}

/* ===================================================================
 * ACT36: forward-transform NORMALISATION correction.
 *
 * Measured defect (evidence: act34_chroma_transform_roundtrip_*,
 * act35_luma4x4_roundtrip_*): the encoder divides by mobi_q4/mobi_q8 on the
 * way in and the decoder multiplies by the SAME table on the way out, so the
 * per-position basis-norm correction those tables encode CANCELS and is never
 * applied. Impulse round-trip gain is therefore not 1.0 but:
 *   luma 4x4   : 1.0 / 1.25 / 1.5625        (spread 1.562x, 0.00% off-position leak)
 *   chroma 8x8 : 0.391 .. 1.278             (spread 3.26x, 4.17% mean leak)
 * Both are quantizer-INDEPENDENT (invariant over impulse amplitude, qx and
 * qyx shift), i.e. structural rather than rounding. Reconstructed detail comes
 * back TOO LARGE at odd frequencies -- 25%/56% for luma, up to 2.56x for chroma.
 *
 * Fix: scale the ENCODER forward step by the measured gain, so the level chosen
 * reconstructs at the correct amplitude. The decoder dequant is NOT touched and
 * cannot be -- it is the format. Any level is legal, so this stays fully
 * format-compatible and needs no decoder change.
 *
 * Numerators below are the measured gains x 1024 (see gen_tables.txt in the
 * ACT36 evidence bundle for the derivation run). Both are exactly separable as
 * f(row)*f(col), which is the expected signature of a per-axis basis norm:
 *   luma   f = {1, 1.25}            for even/odd frequency index
 *   chroma f = {1, 1.1289, 0.625}   for index 0|4, odd, and 2|6
 *
 * HONEST LIMIT: for luma the correction is EXACT (leak is 0.00%, so the error
 * is purely diagonal). For chroma a diagonal scaling CANNOT remove the 4.17%
 * off-position leak, which is genuine basis mismatch in the 8x8 pair -- chroma
 * is improved, NOT fully fixed.
 * Luma 8x8 (mobi_quant_8x8) is deliberately NOT touched: banned topic.
 * =================================================================== */
static const uint16_t mobi_act36_norm4[16] = {
    1024, 1280, 1024, 1280,
    1280, 1600, 1280, 1600,
    1024, 1280, 1024, 1280,
    1280, 1600, 1280, 1600,
};
static const uint16_t mobi_act36_norm8[64] = {
    1024, 1156,  640, 1156, 1024, 1156,  640, 1156,
    1156, 1305,  722, 1305, 1156, 1305,  722, 1305,
     640,  722,  400,  722,  640,  722,  400,  722,
    1156, 1305,  722, 1305, 1156, 1305,  722, 1305,
    1024, 1156,  640, 1156, 1024, 1156,  640, 1156,
    1156, 1305,  722, 1305, 1156, 1305,  722, 1305,
     640,  722,  400,  722,  640,  722,  400,  722,
    1156, 1305,  722, 1305, 1156, 1305,  722, 1305,
};
/* R1 RELEASE DEFAULT CHANGE: ACT36 normalization is now ON by default (the
 * validated, corrected forward-transform quantizer -- see the block comment
 * above the gain tables). MOBI_ACT36_NORM_LUMA / MOBI_ACT36_NORM_CHROMA, when
 * explicitly set (to any value), still override in either direction exactly
 * as before, so every pre-existing evidence bundle's reproduction command
 * (which always sets them explicitly) is unaffected. Only the previously
 * undocumented "nothing set" case changes: it used to mean off
 * (bit-identical to pre-ACT36), now it means on (the corrected default) --
 * UNLESS MOBI_LEGACY_COMPAT is set, which restores the pre-ACT36 default for
 * users who need byte-identical compatibility with old output. Independent
 * per plane class so luma and chroma effects stay separately attributable. */
static ALWAYS_INLINE int mobi_act36_luma_on( void )
{
    static int v = -1;
    if( v < 0 )
    {
        const char *e = getenv("MOBI_ACT36_NORM_LUMA");
        if( e )
            v = atoi(e) ? 1 : 0;
        else
        {
            const char *legacy = getenv("MOBI_LEGACY_COMPAT");
            v = ( legacy && atoi(legacy) ) ? 0 : 1;
        }
    }
    return v;
}
static ALWAYS_INLINE int mobi_act36_chroma_on( void )
{
    static int v = -1;
    if( v < 0 )
    {
        const char *e = getenv("MOBI_ACT36_NORM_CHROMA");
        if( e )
            v = atoi(e) ? 1 : 0;
        else
        {
            const char *legacy = getenv("MOBI_LEGACY_COMPAT");
            v = ( legacy && atoi(legacy) ) ? 0 : 1;
        }
    }
    return v;
}

/* V9 experimental source-flat 4x4 luma AC gate.
 *
 * Unlike a pre-encode spatial blur, this tests the unmodified source pixels
 * of the *same* transform block.  Only AC rounding is changed; DC remains
 * untouched, and all coded levels still use the existing MobiClip dequant.
 * Enabled only by MOBI_V9_FLAT_DZ=0..8 (unset = original V8 byte-for-byte).
 * MOBI_V9_FLAT_RANGE defaults to 12 and is the source 4x4 peak-to-peak gate.
 * An optional MOBI_V9_FLAT_INTRA=0 disables this for intra blocks.
 * These are hypotheses to benchmark, not shipping defaults.
 */
static ALWAYS_INLINE int mobi_v9_flat_luma_off( x264_t *h, int p, int idx,
                                                int b_intra, int *out_dz )
{
    static int configured = -2, range_limit = 12, include_intra = 1;
    if( configured == -2 )
    {
        const char *v = getenv("MOBI_V9_FLAT_DZ");
        const char *r = getenv("MOBI_V9_FLAT_RANGE");
        const char *i = getenv("MOBI_V9_FLAT_INTRA");
        configured = v ? x264_clip3( atoi(v), 0, 8 ) : -1;
        if( r ) range_limit = x264_clip3( atoi(r), 0, 255 );
        if( i ) include_intra = !!atoi(i);
    }
    if( configured < 0 || p != 0 || idx < 0 || idx >= 16 ||
        (b_intra && !include_intra) )
        return 0;
    pixel *src = &h->mb.pic.p_fenc[0][block_idx_xy_fenc[idx]];
    int smallest = (1 << BIT_DEPTH) - 1, largest = 0;
    for( int y = 0; y < 4; y++ )
        for( int x = 0; x < 4; x++ )
        {
            int value = src[y*FENC_STRIDE+x];
            if( value < smallest ) smallest = value;
            if( value > largest ) largest = value;
        }
    *out_dz = configured;
    return largest - smallest <= range_limit;
}

/* V9 opt-in correction: x264_mb_encode_i4x4() is reused for predictive
 * MobiClip residuals with b_predict=0, but historically passed b_intra=1
 * to x264_quant_4x4() unconditionally. That prevents MOBI_DZ's inter
 * deadzone from ever being applied to luma. Keep legacy mode default for
 * reproducible V8 output until independently verified on Old 3DS. */
static ALWAYS_INLINE int mobi_v9_inter_luma_on( void )
{
    static int enabled = -1;
    if( enabled < 0 )
    {
        const char *e = getenv("MOBI_V9_INTER_LUMA_DZ");
        enabled = (e && atoi(e)) ? 1 : 0;
    }
    return enabled;
}

/* Optional edge-preserving refinement. Only apply the alternate inter
 * rounding on a 4x4 region with source pixel range <= configured threshold.
 * Unset MOBI_V9_INTER_FLAT_RANGE means the original all-inter experiment.
 * The original pixels control the gate; no decoder feature is required. */
static ALWAYS_INLINE int mobi_v9_inter_source_flat( x264_t *h, int p, int idx )
{
    static int range = -2;
    if( range == -2 )
    {
        const char *e = getenv("MOBI_V9_INTER_FLAT_RANGE");
        range = e ? x264_clip3( atoi(e), 0, 255 ) : 255;
    }
    if( range == 255 ) return 1;
    if( p != 0 || idx < 0 || idx >= 16 ) return 0;
    pixel *src = &h->mb.pic.p_fenc[0][block_idx_xy_fenc[idx]];
    int smallest = (1 << BIT_DEPTH) - 1, largest = 0;
    for( int y = 0; y < 4; y++ )
        for( int x = 0; x < 4; x++ )
        {
            int v = src[y*FENC_STRIDE+x];
            if( v < smallest ) smallest = v;
            if( v > largest ) largest = v;
        }
    return largest - smallest <= range;
}

/* V10 R-D experiment: distribute *rounding decisions*, not quantizer steps,
 * based on source activity. The decoder's quant tables and bitstream syntax
 * remain unchanged. With the flag unset this path cannot change V9 output.
 * High-activity blocks retain small AC levels; truly flat blocks shed
 * unstable AC coefficients. A two-threshold gate avoids treating every
 * moderately textured block as an edge. */
static ALWAYS_INLINE int mobi_v10_activity_offset( x264_t *h, int p, int idx )
{
    static int enabled = -1;
    static int flat_range = 12, edge_range = 32;
    static int flat_off = 2, edge_off = 9;
    if( enabled < 0 )
    {
        const char *e = getenv("MOBI_V10_ACTIVITY");
        const char *f = getenv("MOBI_V10_FLAT_RANGE");
        const char *r = getenv("MOBI_V10_EDGE_RANGE");
        const char *d = getenv("MOBI_V10_FLAT_OFFSET");
        const char *a = getenv("MOBI_V10_EDGE_OFFSET");
        enabled = e && atoi(e) ? 1 : 0;
        if( f ) flat_range = x264_clip3( atoi(f), 0, 255 );
        if( r ) edge_range = x264_clip3( atoi(r), 0, 255 );
        if( d ) flat_off = x264_clip3( atoi(d), 0, 12 );
        if( a ) edge_off = x264_clip3( atoi(a), 0, 12 );
    }
    if( !enabled || p != 0 || idx < 0 || idx >= 16 ) return -1;
    pixel *src = &h->mb.pic.p_fenc[0][block_idx_xy_fenc[idx]];
    int low = 255, high = 0;
    for( int y = 0; y < 4; y++ )
        for( int x = 0; x < 4; x++ )
        {
            int v = src[y*FENC_STRIDE+x];
            if( v < low ) low = v;
            if( v > high ) high = v;
        }
    if( high - low <= flat_range ) return flat_off;
    if( high - low >= edge_range ) return edge_off;
    return -1;
}

/* V11 experimental neighbor-error-aware DC rounding. A blockwise DC
 * quantization mistake shifts the whole decoded 4x4 cell and creates a
 * visible seam with the already reconstructed block to its left/above.
 * This probe biases only the encoder's decision for the DC level, never
 * decoder tables or bitstream syntax. It is disabled by default.
 *
 * Unlike post-decode blur, the target uses *source-relative reconstruction
 * error* on both sides of an edge, not the true image edge itself. Thus a
 * legitimate high-contrast image boundary is not a request to smooth it.
 * Clamp and blend prevent large errors from cascading across neighboring
 * blocks. Only completed neighbors inside the current macroblock count. */
static ALWAYS_INLINE int mobi_v11_dc_neighbor_bias( x264_t *h, int p, int idx )
{
    static int enabled = -1;
    static int clamp_error = 4, strength = 8;
    if( enabled < 0 )
    {
        const char *e = getenv("MOBI_V11_DC_MATCH");
        const char *c = getenv("MOBI_V11_DC_CLAMP");
        const char *s = getenv("MOBI_V11_DC_STRENGTH");
        enabled = e && atoi(e) ? 1 : 0;
        if( c ) clamp_error = x264_clip3( atoi(c), 0, 16 );
        if( s ) strength = x264_clip3( atoi(s), 0, 16 );
    }
    if( !enabled || !strength || p != 0 || idx < 0 || idx >= 16 ) return 0;
    int off_src = block_idx_xy_fenc[idx];
    int off_dst = block_idx_xy_fdec[idx];
    int bx = off_src % FENC_STRIDE;
    int by = off_src / FENC_STRIDE;
    pixel *src = &h->mb.pic.p_fenc[0][off_src];
    pixel *rec = &h->mb.pic.p_fdec[0][off_dst];
    int sum = 0, count = 0;
    if( bx >= 4 )
        for( int y = 0; y < 4; y++ )
        {
            sum += (int)rec[y*FDEC_STRIDE-1] - (int)src[y*FENC_STRIDE-1];
            count++;
        }
    if( by >= 4 )
        for( int x = 0; x < 4; x++ )
        {
            sum += (int)rec[x-FDEC_STRIDE] - (int)src[x-FENC_STRIDE];
            count++;
        }
    if( !count ) return 0;
    int err = sum/count;
    err = x264_clip3( err, -clamp_error, clamp_error );
    return err * strength;
}

/* V12 opt-in high-frequency quantization regularizer. The default is off.
 * A decoder-reconstructed high-frequency coefficient in a nearly smooth
 * 4x4 source patch can create a visible flickering speckle. Raise the
 * threshold for retaining these coefficients, while leaving DC, low spatial
 * frequencies and real source edges untouched. The MobiClip inverse transform
 * and bitstream remain unchanged. Unlike preprocessing, the source pixels
 * used to judge detail have not been blurred. */
static ALWAYS_INLINE int mobi_v12_hf_gate( x264_t *h, int p, int idx,
                                           int *first_ac )
{
    static int dz = -2, range = 30, start = 8;
    if( dz == -2 )
    {
        const char *v = getenv("MOBI_V12_HF_DZ");
        const char *r = getenv("MOBI_V12_HF_RANGE");
        const char *s = getenv("MOBI_V12_HF_START");
        dz = v ? x264_clip3( atoi(v), 0, 8 ) : -1;
        if( r ) range = x264_clip3( atoi(r), 0, 255 );
        if( s ) start = x264_clip3( atoi(s), 1, 15 );
    }
    if( dz < 0 || p != 0 || idx < 0 || idx >= 16 ) return -1;
    pixel *src = &h->mb.pic.p_fenc[0][block_idx_xy_fenc[idx]];
    int lo = 255, hi = 0;
    for( int y = 0; y < 4; y++ )
        for( int x = 0; x < 4; x++ )
        {
            int v = src[y*FENC_STRIDE+x];
            lo = X264_MIN(lo,v);
            hi = X264_MAX(hi,v);
        }
    if( hi-lo > range ) return -1;
    *first_ac = start;
    return dz;
}

/* V13 experimental DC seam rate-distortion search. Unlike the earlier
 * coefficient bias (V11), this actually compares the neighbouring quantized
 * DC LEVELS. The MobiClip decoder uses the same quantizer in all cases; no
 * new syntax or decoder-side operation is required.
 *
 * The source DC transform represents 16 times the mean prediction residual.
 * A quantized DC level reconstructs (level*step)/16 in image pixel units.
 * Bias the choice toward agreement with *source-relative* errors of already
 * reconstructed, source-smooth left/top neighbours. This does NOT flatten a
 * real source boundary. Restrict to dark, low-activity blocks by default.
 *
 * Opt-in env:
 *   MOBI_V13_SEAM_DC=1
 *   MOBI_V13_SEAM_WEIGHT=0..32  (default 4)
 *   MOBI_V13_SEAM_RANGE=0..64  (default 16)
 *   MOBI_V13_SEAM_DARK_MAX=0..255 (default 140)
 *   MOBI_V13_SEAM_RATE=0..32 (default 0, cost of changing nearest DC)
 */
static ALWAYS_INLINE void mobi_v13_dc_seam_opt( x264_t *h, int p, int idx,
                                                int orig_coef_dc,
                                                int step, dctcoef *dct )
{
    static int enabled = -1, weight = 4, source_range = 16;
    static int dark_max = 140, rate = 0;
    if( enabled < 0 )
    {
        const char *e = getenv("MOBI_V13_SEAM_DC");
        const char *w = getenv("MOBI_V13_SEAM_WEIGHT");
        const char *r = getenv("MOBI_V13_SEAM_RANGE");
        const char *d = getenv("MOBI_V13_SEAM_DARK_MAX");
        const char *b = getenv("MOBI_V13_SEAM_RATE");
        enabled = e && atoi(e) ? 1 : 0;
        if( w ) weight = x264_clip3( atoi(w), 0, 32 );
        if( r ) source_range = x264_clip3( atoi(r), 0, 64 );
        if( d ) dark_max = x264_clip3( atoi(d), 0, 255 );
        if( b ) rate = x264_clip3( atoi(b), 0, 32 );
    }
    if( !enabled || !weight || p != 0 || idx < 0 || idx >= 16 || step <= 0 )
        return;
    int off_src = block_idx_xy_fenc[idx];
    int off_dst = block_idx_xy_fdec[idx];
    int bx = off_src % FENC_STRIDE;
    int by = off_src / FENC_STRIDE;
    pixel *src = &h->mb.pic.p_fenc[0][off_src];
    pixel *dst = &h->mb.pic.p_fdec[0][off_dst];
    int low = 255, high = 0, source_sum = 0;
    for( int yy = 0; yy < 4; yy++ )
        for( int xx = 0; xx < 4; xx++ )
        {
            int v = src[yy*FENC_STRIDE + xx];
            low = X264_MIN( low, v );
            high = X264_MAX( high, v );
            source_sum += v;
        }
    if( high-low > source_range || source_sum > 16*dark_max )
        return;
    int neighbor_errors[8], count = 0;
    if( bx >= 4 )
        for( int yy = 0; yy < 4; yy++ )
        {
            int off = yy*FENC_STRIDE;
            if( abs( (int)src[off]-(int)src[off-1] ) <= 6 )
                neighbor_errors[count++] = (int)dst[yy*FDEC_STRIDE-1] - (int)src[off-1];
        }
    if( by >= 4 )
        for( int xx = 0; xx < 4; xx++ )
        {
            if( abs( (int)src[xx]-(int)src[xx-FENC_STRIDE] ) <= 6 )
                neighbor_errors[count++] = (int)dst[xx-FDEC_STRIDE] - (int)src[xx-FENC_STRIDE];
        }
    if( count < 2 )
        return;
    int old_level = dct[0], best_level = old_level;
    int64_t best_cost = INT64_MAX;
    for( int diff = -1; diff <= 1; diff++ )
    {
        int level = old_level + diff;
        int64_t error16 = (int64_t)level*step - orig_coef_dc;
        int64_t cost = 16*error16*error16;
        for( int j = 0; j < count; j++ )
        {
            int64_t seam = error16 - 16*neighbor_errors[j];
            cost += weight*seam*seam;
        }
        if( diff ) cost += (int64_t)rate*step*step;
        if( cost < best_cost )
        {
            best_cost = cost;
            best_level = level;
        }
    }
    dct[0] = best_level;
}

static ALWAYS_INLINE int mobi_quant_4x4( x264_t *h, dctcoef dct[16], int qp,
                                          int b_intra, int p, int idx )
{
    int qx = qp % 6;
    int shift = mobi_qyx( h );
    int nz = 0;
    int flat_dz = -1;
    int src_flat = mobi_v9_flat_luma_off( h, p, idx, b_intra, &flat_dz );
    int activity_off = mobi_v10_activity_offset( h, p, idx );
    int dc_bias = mobi_v11_dc_neighbor_bias( h, p, idx );
    int hf_start = 8;
    int hf_off = mobi_v12_hf_gate( h, p, idx, &hf_start );
    int orig_coef_dc = dct[0];
    for( int zz = 0; zz < 16; zz++ )
    {
        int raster = mobi_zigzag4x4[zz];
        /* x264's 2D 4x4 DCT DC coefficient = 16*R for constant residual R.
         * The Mobiclip IDCT (>>6 after 2D butterfly) needs DC = 64*R to recover R.
         * Using unshifted mobi_q4[qx] as step compensates: level = 16R/step,
         * reconstruction = level * (step<<2) / 64 = 16R * 4 / 64 = R. */
        int step = (int)mobi_q4[qx][zz] << shift;
        if( mobi_act36_luma_on() )
            step = ( step * (int)mobi_act36_norm4[raster] + 512 ) >> 10;
        int off  = (activity_off >= 0 && zz > 0) ? step * activity_off / 16 :
                   (src_flat && zz > 0) ? step * flat_dz / 16 :
                   mobi_round_off( h, step, b_intra );
        if( hf_off >= 0 && zz >= hf_start )
            off = step * hf_off / 16;
        int coef = dct[raster] + (zz == 0 ? dc_bias : 0);
        int level;
        if( coef >= 0 )
            level = (coef + off) / step;
        else
            level = -((-coef + off) / step);
        dct[raster] = level;
        nz |= level;
    }
    if( h->param.i_mobiclip && p == 0 )
    {
        int step_dc = (int)mobi_q4[qx][0] << shift;
        mobi_v13_dc_seam_opt( h, p, idx, orig_coef_dc,
                              step_dc, dct );
        nz = 0;
        for( int zz = 0; zz < 16; zz++ )
            nz |= dct[zz];
    }
    return !!nz;
}

static ALWAYS_INLINE int mobi_quant_8x8( x264_t *h, dctcoef dct[64], int qp, int b_intra )
{
    int qx = qp % 6;
    int shift = mobi_qyx( h );
    int nz = 0;
    for( int zz = 0; zz < 64; zz++ )
    {
        int raster = mobi_zigzag8x8[zz];
        int step = (int)mobi_q8[qx][zz] << shift;
        int off  = mobi_round_off( h, step, b_intra );
        int coef = dct[raster];
        int level;
        if( coef >= 0 )
            level = (coef + off) / step;
        else
            level = -((-coef + off) / step);
        dct[raster] = level;
        nz |= level;
    }
    return !!nz;
}

/* Chroma-only rounding-offset override, opt-in via MOBI_CHROMA_DZ. Unset
 * (default -1 sentinel) falls back to mobi_round_off()'s existing MOBI_DZ
 * behavior exactly -- zero change to Candidate B. This does NOT touch the
 * quantizer step/shift (mobi_qyx(h), the dequant qtab[], or the header
 * quantizer field written once per slice in encoder.c) -- only which
 * coefficients survive the forward quantizer's round-to-zero threshold.
 * Every retained level is still decoded using the single shared step the
 * header signals, so this stays bitstream-compatible by construction.
 * Intra chroma is untouched (always step>>1, same as mobi_round_off),
 * matching mobi_round_off's own intra/inter split -- MOBI_DZ only ever
 * affected inter blocks, and this preserves that scope for consistency. */
static ALWAYS_INLINE int mobi_round_off_chroma( x264_t *h, int step, int b_intra )
{
    if( b_intra )
        return step >> 1;
    static int dz = -2; /* -2 = not yet read from env */
    if( dz == -2 )
    {
        const char *e = getenv("MOBI_CHROMA_DZ");
        dz = e ? atoi(e) : -1; /* -1 = no override, fall back to MOBI_DZ */
        if( dz >= 0 ) { if( dz < 1 ) dz = 1; if( dz > 8 ) dz = 8; }
    }
    if( dz < 0 )
        return mobi_round_off( h, step, b_intra ); /* fallback: identical to today */
    return step * dz / 16;
}

/* ACT26 PROBE (measurement only, default OFF, byte-identical when disabled):
 * flatness-gated chroma AC deadzone.
 *
 * Mechanism this targets (evidence\act26_chroma_ssim_20260825_180000\
 * MECHANISM_REPORT.txt): in source-flat chroma blocks our decoded output
 * carries MORE within-block variance than the source itself (0.587 vs
 * 0.486) while the reference carries LESS (0.391). That surviving AC is
 * quantization noise relative to a genuinely flat field; SSIM's
 * contrast/structure term divides by local variance, so injected variance
 * where the source has none collapses SSIM while barely moving SSE.
 *
 * The gate keys on the SOURCE block's peak-to-peak range (p_src, the
 * original pixels) -- deliberately NOT on the decoded/reconstructed block,
 * so the decision reflects genuine source flatness rather than our own
 * quantization artifacts. DC (zz==0) is never gated: our flat-block DC
 * accuracy is currently 4x better than the reference's (|err| 0.97 vs
 * 3.84) and is what keeps flat colors correct -- only AC is suppressed.
 *
 * Env:
 *   MOBI_ACT26_CDZ_ENABLE=1   turn the probe on (default off)
 *   MOBI_ACT26_CDZ_DZ=N       AC deadzone strength in flat blocks, 0..8
 *                             (off = step*N/16; 8 = round-to-nearest =
 *                             today's intra behavior; lower = more zeroing;
 *                             0 = maximum deadzone). Default 2.
 *   MOBI_ACT26_CDZ_VAR=N      source peak-to-peak range (0..255) at or
 *                             below which a block counts as flat. Default 4.
 *   MOBI_ACT26_CDZ_MODE=N     0 = gate both intra and inter chroma
 *                             (default), 1 = intra chroma only,
 *                             2 = inter chroma only. Exists because the
 *                             I-vs-P concentration check was inconclusive
 *                             (I-frame U-SSIM 0.9481 vs P-frame 0.9317 --
 *                             the deficit is WORSE in P despite chroma
 *                             intra being the path with no deadzone), so
 *                             which path dominates is settled by sweeping
 *                             this rather than by assumption. */
static ALWAYS_INLINE int mobi_act26_cdz_on( int *out_dz, int *out_var, int *out_mode )
{
    static int on = -1, dz = 2, varth = 4, mode = 0;
    if( on < 0 )
    {
        const char *e = getenv("MOBI_ACT26_CDZ_ENABLE");
        const char *d = getenv("MOBI_ACT26_CDZ_DZ");
        const char *v = getenv("MOBI_ACT26_CDZ_VAR");
        const char *m = getenv("MOBI_ACT26_CDZ_MODE");
        on = ( e && atoi(e) ) ? 1 : 0;
        if( d ) { dz = atoi(d); if( dz < 0 ) dz = 0; if( dz > 8 ) dz = 8; }
        if( v ) { varth = atoi(v); if( varth < 0 ) varth = 0; if( varth > 255 ) varth = 255; }
        if( m ) { mode = atoi(m); if( mode < 0 || mode > 2 ) mode = 0; }
    }
    *out_dz = dz; *out_var = varth; *out_mode = mode;
    return on;
}

/* ACT30 INTERVENTION A: suppress DC-ONLY luma residuals in source-flat blocks.
 * Measured basis (evidencect29_accumulation_20260825_220000): for source-flat
 * INTER method-0 luma blocks, coding a DC-only residual leaves the reconstruction
 * 2.7x WORSE in excess structure than coding nothing (+1.398 vs +0.519), while
 * also costing bits; the reference encoder's equivalent blocks sit at +0.006.
 * Mechanism: a flat 16x16 region is 16 independently-quantized 4x4 blocks, so a
 * per-block DC correction creates a patchwork of slightly different flat levels
 * -- seam structure that no single block's SSE penalises.
 * Encoder-side decision ONLY: not coding a residual is always a legal choice, the
 * bitstream syntax is unchanged, and the decoder needs no knowledge of it, so
 * there is no desync surface. Blocks carrying any AC are deliberately left alone
 * (3.6% at +1.283 -- they may be coding real detail the flatness gate missed).
 *   MOBI_ACT30_LUMADC_ENABLE=1  apply the suppression
 *   MOBI_ACT30_LUMADC_SIM=1     count candidates only, change nothing
 *   MOBI_ACT30_LUMADC_VAR=N     source 16x16 peak-to-peak range at or below which
 *                               the MB counts as flat (default 4) */
static ALWAYS_INLINE int mobi_act30_lumadc_mode( int *out_var )
{
    static int mode = -1, varth = 4;   /* 0=off 1=sim 2=enable */
    if( mode < 0 )
    {
        const char *en = getenv("MOBI_ACT30_LUMADC_ENABLE");
        const char *sm = getenv("MOBI_ACT30_LUMADC_SIM");
        const char *v  = getenv("MOBI_ACT30_LUMADC_VAR");
        mode = ( en && atoi(en) ) ? 2 : ( ( sm && atoi(sm) ) ? 1 : 0 );
        if( v ) { varth = atoi(v); if( varth < 0 ) varth = 0; if( varth > 255 ) varth = 255; }
    }
    *out_var = varth;
    return mode;
}

/* Peak-to-peak range of the 16x16 SOURCE luma MB at p_src (FENC_STRIDE). */
static ALWAYS_INLINE int mobi_act30_src_range16( pixel *p_src )
{
    int mn = (1 << BIT_DEPTH) - 1, mx = 0;
    for( int yy = 0; yy < 16; yy++ )
        for( int xx = 0; xx < 16; xx++ )
        {
            int v = p_src[yy*FENC_STRIDE + xx];
            if( v < mn ) mn = v;
            if( v > mx ) mx = v;
        }
    return mx - mn;
}

/* True when this block's only nonzero coefficient is DC (zigzag index 0). */
static ALWAYS_INLINE int mobi_act30_is_dc_only( dctcoef *c )
{
    if( !c[0] ) return 0;
    for( int zz = 1; zz < 16; zz++ ) if( c[zz] ) return 0;
    return 1;
}

/* Peak-to-peak range of the 8x8 SOURCE chroma block at p_src (FENC_STRIDE). */
static ALWAYS_INLINE int mobi_act26_src_range( pixel *p_src )
{
    int mn = (1 << BIT_DEPTH) - 1, mx = 0;
    for( int yy = 0; yy < 8; yy++ )
        for( int xx = 0; xx < 8; xx++ )
        {
            int v = p_src[yy*FENC_STRIDE + xx];
            if( v < mn ) mn = v;
            if( v > mx ) mx = v;
        }
    return mx - mn;
}

/* Chroma-only forward quant: identical to mobi_quant_8x8 (same shift,
 * same step, same table) except the rounding offset comes from
 * mobi_round_off_chroma(). Kept as a separate function, not a branch
 * inside mobi_quant_8x8, so luma's path (including any future luma 8x8
 * mode) is untouched by construction.
 * b_src_flat: ACT26 probe -- nonzero when the caller determined the SOURCE
 * block is flat AND the probe is enabled for this block's intra/inter
 * class. Zero (the default when the probe is off) reproduces the previous
 * behavior exactly, bit for bit. */
static ALWAYS_INLINE int mobi_quant_8x8_chroma( x264_t *h, dctcoef dct[64], int qp, int b_intra, int b_src_flat )
{
    int qx = qp % 6;
    int shift = mobi_qyx( h );
    int nz = 0;
    int cdz_dz = 0, cdz_var = 0, cdz_mode = 0;
    if( b_src_flat )
        mobi_act26_cdz_on( &cdz_dz, &cdz_var, &cdz_mode );
    for( int zz = 0; zz < 64; zz++ )
    {
        int raster = mobi_zigzag8x8[zz];
        int step = (int)mobi_q8[qx][zz] << shift;
        if( mobi_act36_chroma_on() )
            step = ( step * (int)mobi_act36_norm8[raster] + 512 ) >> 10;
        /* zz==0 is DC -- never gated, see header comment. */
        int off  = ( b_src_flat && zz > 0 ) ? step * cdz_dz / 16
                                            : mobi_round_off_chroma( h, step, b_intra );
        int coef = dct[raster];
        int level;
        if( coef >= 0 )
            level = (coef + off) / step;
        else
            level = -((-coef + off) / step);
        dct[raster] = level;
        nz |= level;
    }
    return !!nz;
}

#define x264_rdo_init x264_template(rdo_init)
void x264_rdo_init( void );

#define x264_macroblock_probe_skip x264_template(macroblock_probe_skip)
int x264_macroblock_probe_skip( x264_t *h, int b_bidir );

#define x264_macroblock_probe_pskip( h )\
    x264_macroblock_probe_skip( h, 0 )
#define x264_macroblock_probe_bskip( h )\
    x264_macroblock_probe_skip( h, 1 )

#define x264_predict_lossless_4x4 x264_template(predict_lossless_4x4)
void x264_predict_lossless_4x4( x264_t *h, pixel *p_dst, int p, int idx, int i_mode );
#define x264_predict_lossless_8x8 x264_template(predict_lossless_8x8)
void x264_predict_lossless_8x8( x264_t *h, pixel *p_dst, int p, int idx, int i_mode, pixel edge[36] );
#define x264_predict_lossless_16x16 x264_template(predict_lossless_16x16)
void x264_predict_lossless_16x16( x264_t *h, int p, int i_mode );
#define x264_predict_lossless_chroma x264_template(predict_lossless_chroma)
void x264_predict_lossless_chroma( x264_t *h, int i_mode );

#define x264_macroblock_encode x264_template(macroblock_encode)
void x264_macroblock_encode      ( x264_t *h );
#define x264_macroblock_write_cabac x264_template(macroblock_write_cabac)
void x264_macroblock_write_cabac ( x264_t *h, x264_cabac_t *cb );
#define x264_macroblock_write_cavlc x264_template(macroblock_write_cavlc)
void x264_macroblock_write_cavlc ( x264_t *h );

#define x264_macroblock_encode_p8x8 x264_template(macroblock_encode_p8x8)
void x264_macroblock_encode_p8x8( x264_t *h, int i8 );
#define x264_macroblock_encode_p4x4 x264_template(macroblock_encode_p4x4)
void x264_macroblock_encode_p4x4( x264_t *h, int i4 );
#define x264_mb_encode_chroma x264_template(mb_encode_chroma)
void x264_mb_encode_chroma( x264_t *h, int b_inter, int i_qp );

#define x264_cabac_mb_skip x264_template(cabac_mb_skip)
void x264_cabac_mb_skip( x264_t *h, int b_skip );
#define x264_cabac_block_residual_c x264_template(cabac_block_residual_c)
void x264_cabac_block_residual_c( x264_t *h, x264_cabac_t *cb, int ctx_block_cat, dctcoef *l );
#define x264_cabac_block_residual_8x8_rd_c x264_template(cabac_block_residual_8x8_rd_c)
void x264_cabac_block_residual_8x8_rd_c( x264_t *h, x264_cabac_t *cb, int ctx_block_cat, dctcoef *l );
#define x264_cabac_block_residual_rd_c x264_template(cabac_block_residual_rd_c)
void x264_cabac_block_residual_rd_c( x264_t *h, x264_cabac_t *cb, int ctx_block_cat, dctcoef *l );

#define x264_quant_luma_dc_trellis x264_template(quant_luma_dc_trellis)
int x264_quant_luma_dc_trellis( x264_t *h, dctcoef *dct, int i_quant_cat, int i_qp,
                                int ctx_block_cat, int b_intra, int idx );
#define x264_quant_chroma_dc_trellis x264_template(quant_chroma_dc_trellis)
int x264_quant_chroma_dc_trellis( x264_t *h, dctcoef *dct, int i_qp, int b_intra, int idx );
#define x264_quant_4x4_trellis x264_template(quant_4x4_trellis)
int x264_quant_4x4_trellis( x264_t *h, dctcoef *dct, int i_quant_cat,
                             int i_qp, int ctx_block_cat, int b_intra, int b_chroma, int idx );
#define x264_quant_8x8_trellis x264_template(quant_8x8_trellis)
int x264_quant_8x8_trellis( x264_t *h, dctcoef *dct, int i_quant_cat,
                             int i_qp, int ctx_block_cat, int b_intra, int b_chroma, int idx );

#define x264_noise_reduction_update x264_template(noise_reduction_update)
void x264_noise_reduction_update( x264_t *h );

static ALWAYS_INLINE int x264_quant_4x4( x264_t *h, dctcoef dct[16], int i_qp, int ctx_block_cat, int b_intra, int p, int idx )
{
    if( h->param.i_mobiclip )
        return mobi_quant_4x4( h, dct, i_qp, b_intra, p, idx );
    int i_quant_cat = b_intra ? (p?CQM_4IC:CQM_4IY) : (p?CQM_4PC:CQM_4PY);
    if( h->mb.b_noise_reduction )
        h->quantf.denoise_dct( dct, h->nr_residual_sum[0+!!p*2], h->nr_offset[0+!!p*2], 16 );
    if( h->mb.b_trellis )
        return x264_quant_4x4_trellis( h, dct, i_quant_cat, i_qp, ctx_block_cat, b_intra, !!p, idx+p*16 );
    else
        return h->quantf.quant_4x4( dct, h->quant4_mf[i_quant_cat][i_qp], h->quant4_bias[i_quant_cat][i_qp] );
}

static ALWAYS_INLINE int x264_quant_8x8( x264_t *h, dctcoef dct[64], int i_qp, int ctx_block_cat, int b_intra, int p, int idx )
{
    if( h->param.i_mobiclip )
        return mobi_quant_8x8( h, dct, i_qp, b_intra );
    int i_quant_cat = b_intra ? (p?CQM_8IC:CQM_8IY) : (p?CQM_8PC:CQM_8PY);
    if( h->mb.b_noise_reduction )
        h->quantf.denoise_dct( dct, h->nr_residual_sum[1+!!p*2], h->nr_offset[1+!!p*2], 64 );
    if( h->mb.b_trellis )
        return x264_quant_8x8_trellis( h, dct, i_quant_cat, i_qp, ctx_block_cat, b_intra, !!p, idx+p*4 );
    else
        return h->quantf.quant_8x8( dct, h->quant8_mf[i_quant_cat][i_qp], h->quant8_bias[i_quant_cat][i_qp] );
}

#define STORE_8x8_NNZ( p, idx, nz )\
do\
{\
    M16( &h->mb.cache.non_zero_count[x264_scan8[p*16+idx*4]+0] ) = (nz) * 0x0101;\
    M16( &h->mb.cache.non_zero_count[x264_scan8[p*16+idx*4]+8] ) = (nz) * 0x0101;\
} while( 0 )

#define CLEAR_16x16_NNZ( p ) \
do\
{\
    M32( &h->mb.cache.non_zero_count[x264_scan8[16*p] + 0*8] ) = 0;\
    M32( &h->mb.cache.non_zero_count[x264_scan8[16*p] + 1*8] ) = 0;\
    M32( &h->mb.cache.non_zero_count[x264_scan8[16*p] + 2*8] ) = 0;\
    M32( &h->mb.cache.non_zero_count[x264_scan8[16*p] + 3*8] ) = 0;\
} while( 0 )

/* A special for loop that iterates branchlessly over each set
 * bit in a 4-bit input. */
#define FOREACH_BIT(idx,start,mask) for( int idx = start, msk = mask, skip; msk && (skip = x264_ctz_4bit(msk), idx += skip, msk >>= skip+1, 1); idx++ )

/* ------------------------------------------------------------------------
 * Mobiclip intra prediction (4x4), bit-exact with the ffmpeg mobiclip
 * decoder's predict_intra()/pick_*()/get_prediction helpers.  Reads
 * reconstructed neighbours straight out of the FDEC tile (p_dst) using the
 * decoder's pget() boundary-clamping rules so the encoder reconstructs the
 * same pixels the decoder will.  Modes: 0=V 1=H 2=plane(unused) 3=DC 4..8=dir.
 * ------------------------------------------------------------------------ */
#if !HIGH_BIT_DEPTH
/* H.264 4x4 intra mode (0..8) -> Mobiclip intra mode.  MUST stay identical to
 * the table in cavlc.c so the reconstruction prediction matches the mode that
 * gets written into the bitstream (and thus the decoder's predict_intra). */
static const int mobi_h264_to_mobiclip_mode[9] = { 0, 1, 3, 3, 7, 6, 5, 8, 4 };
/* read neighbour at block-relative (rx,ry) with decoder pget() semantics */
static ALWAYS_INLINE int mobi_pget( x264_t *h, pixel *p_dst, int idx, int rx, int ry )
{
    const int size = 4;
    if( rx == -1 && ry >= size )      { rx = -1; ry = size - 1; }
    else if( rx >= -1 && ry >= -1 )   { /* keep */ }
    else if( rx == -1 && ry == -2 )   { rx = 0; ry = -1; }
    else if( rx == -2 && ry == -1 )   { rx = -1; ry = 0; }
    int mb_x = h->mb.i_mb_x;
    int mb_y = h->mb.i_mb_y;
    int ax = mb_x * 16 + block_idx_x[idx] * 4;
    int ay = mb_y * 16 + block_idx_y[idx] * 4;

    int orig_x = ax + rx;
    int orig_y = ay + ry;

    // Decoder clips to frame bounds
    int tx = orig_x; if( tx < 0 ) tx = 0; else if( tx > h->param.i_width - 1 ) tx = h->param.i_width - 1;
    int ty = orig_y; if( ty < 0 ) ty = 0; else if( ty > h->param.i_height - 1 ) ty = h->param.i_height - 1;

    int t_mb_x = tx / 16;
    int t_mb_y = ty / 16;

    if( t_mb_y < mb_y || (t_mb_y == mb_y && t_mb_x < mb_x) )
    {
        // Past macroblock. Already reconstructed. Read from frame buffer!
        return h->fdec->plane[0][ ty * h->mb.pic.i_stride[0] + tx ];
    }
    else if( t_mb_y == mb_y && t_mb_x == mb_x )
    {
        // Current macroblock. Read the local fdec tile at the clamped position,
        // EXACTLY as the decoder reads its frame buffer in pget(). This is the
        // critical fix: the decoder fills each 4x4 block in raster order and the
        // directional modes (H, and the diagonal pick_* modes) read pixels that
        // were just written EARLIER IN THE SAME BLOCK (e.g. H mode: pixel x reads
        // pixel x-1, cascading the left edge across the row). Returning 128 for
        // in-block positions made the encoder form residuals against [L,128,128,
        // 128] while the decoder reconstructed [L,L,L,L] -> permanent desync.
        // p_dst holds: reconstructed neighbour blocks (above/left, via the tile
        // border and earlier-idx blocks) AND the progressively-filled pixels of
        // the current block, matching the decoder's frame buffer for every
        // position that a valid prediction mode actually reads.
        return p_dst[ (ty - ay) * FDEC_STRIDE + (tx - ax) ];
    }
    else
    {
        // Future macroblock to the right/below: not yet reconstructed. Valid
        // intra modes never read here (clamping keeps reads to up/left/up-right
        // neighbours), but return a deterministic value just in case.
        return 128;
    }
}
static ALWAYS_INLINE int mobi_half( int a, int b )       { return ((a + b) + 1) / 2; }
static ALWAYS_INLINE int mobi_half3( int a, int b, int c ){ return ((a + b + b + c) * 2 / 4 + 1) / 2; }
#define MPG(rx,ry) mobi_pget(h,p_dst,idx,(rx),(ry))
static ALWAYS_INLINE int mobi_half_horz( x264_t *h, pixel *p_dst, int idx, int x, int y )
{ return mobi_half3( MPG(x-1,y), MPG(x,y), MPG(x+1,y) ); }
static ALWAYS_INLINE int mobi_half_vert( x264_t *h, pixel *p_dst, int idx, int x, int y )
{ return mobi_half3( MPG(x,y-1), MPG(x,y), MPG(x,y+1) ); }

static void mobi_predict_4x4( x264_t *h, pixel *p_dst, int idx, int pmode )
{
    const int size = 4;
    int mb_x = h->mb.i_mb_x;
    int mb_y = h->mb.i_mb_y;
    int ax = mb_x * 16 + block_idx_x[idx] * 4;
    int ay = mb_y * 16 + block_idx_y[idx] * 4;
    if( pmode == 3 ) /* DC */
    {
        int fill;
        if( ax == 0 && ay == 0 )
            fill = 0x80;
        else if( ax >= 1 && ay >= 1 )
        {
            int left = 0, top = 0;
            for( int y = 0; y < size; y++ ) left += p_dst[y*FDEC_STRIDE - 1];
            for( int x = 0; x < size; x++ ) top  += p_dst[-FDEC_STRIDE + x];
            fill = ((left + top) * 2 / (2*size) + 1) / 2;
        }
        else if( ax >= 1 )
        {
            int left = 0;
            for( int y = 0; y < size; y++ ) left += p_dst[y*FDEC_STRIDE - 1];
            fill = (left * 2 / size + 1) / 2;
        }
        else /* ay >= 1 */
        {
            int top = 0;
            for( int x = 0; x < size; x++ ) top += p_dst[-FDEC_STRIDE + x];
            fill = (top * 2 / size + 1) / 2;
        }
        for( int y = 0; y < size; y++ )
            for( int x = 0; x < size; x++ )
                p_dst[y*FDEC_STRIDE + x] = fill;
        return;
    }
    for( int y = 0; y < size; y++ )
    {
        for( int x = 0; x < size; x++ )
        {
            int val = 0;
            switch( pmode )
            {
            case 0: /* V / above */ val = MPG(x, y-1); break;
            case 1: /* H / left  */ val = MPG(x-1, y); break;
            case 4: /* pick_4 */
                if( (x % 2) == 0 )
                    val = mobi_half( MPG(-1, y + x/2), MPG(-1, y + x/2 + 1) );
                else
                    val = mobi_half_vert( h, p_dst, idx, -1, y + x/2 + 1 );
                break;
            case 5: /* pick_5 */
                if( x == 0 )
                    val = mobi_half( MPG(-1, y-1), MPG(-1, y) );
                else if( y == 0 )
                    val = mobi_half_horz( h, p_dst, idx, x-2, y-1 );
                else if( x == 1 )
                    val = mobi_half_vert( h, p_dst, idx, x-2, y-1 );
                else
                    val = MPG(x-2, y-1);
                break;
            case 6: /* pick_6 */
                if( y == 0 )
                    val = mobi_half( MPG(x-1, -1), MPG(x, -1) );
                else if( x == 0 )
                    val = mobi_half_vert( h, p_dst, idx, x-1, y-2 );
                else if( y == 1 )
                    val = mobi_half_horz( h, p_dst, idx, x-1, y-2 );
                else
                    val = MPG(x-1, y-2);
                break;
            case 7: /* pick_7 */
            {
                int clr = MPG(x-1, y-1);
                if( x && y )
                    val = clr;
                else
                {
                    int acc1, acc2;
                    if( x == 0 ) acc1 = MPG(-1, y);
                    else         acc1 = MPG(x-2, -1);
                    if( y == 0 ) acc2 = MPG(x, -1);
                    else         acc2 = MPG(-1, y-2);
                    val = mobi_half3( acc1, clr, acc2 );
                }
                break;
            }
            case 8: /* pick_8 */
                if( y == 0 )
                    val = mobi_half( MPG(x, -1), MPG(x+1, -1) );
                else if( y == 1 )
                    val = mobi_half_horz( h, p_dst, idx, x+1, -1 );
                else if( x < size - 1 )
                    val = MPG(x+1, y-2);
                else if( (y % 2) == 0 )
                    val = mobi_half( MPG(y/2 + size - 1, -1), MPG(y/2 + size, -1) );
                else
                    val = mobi_half_horz( h, p_dst, idx, y/2 + size, -1 );
                break;
            default: val = 0x80; break;
            }
            p_dst[y*FDEC_STRIDE + x] = val;
        }
    }
}
#undef MPG

/* Mobiclip chroma 8x8 prediction, matching the decoder's predict_intra(size=8)
 * for the only modes the chroma-mode fix table can emit: 0=V, 1=H, 3=DC.
 * Reads reconstructed neighbours from the fdec tile borders (populated by x264
 * before chroma encode); DC handles neighbour availability exactly like the
 * decoder. p_dst is the chroma fdec tile origin. */
static void mobi_predict_chroma_8x8( x264_t *h, int ch, int mode )
{
    const int size = 8;
    int ax = h->mb.i_mb_x * 8;
    int ay = h->mb.i_mb_y * 8;
    int stride = FDEC_STRIDE;
    pixel *p_dst = h->mb.pic.p_fdec[1+ch];
    pixel *fp = NULL;
    int fstride = 0;
    if( h->fdec && h->fdec->plane[1+ch] )
    {
        fp = h->fdec->plane[1+ch];
        fstride = h->fdec->i_stride[1];
    }
    if( mode == 0 ) /* V / above */
    {
        int ref_row = X264_MAX(ay - 1, 0);
        if( fp )
        {
            for( int y = 0; y < size; y++ )
                for( int x = 0; x < size; x++ )
                    p_dst[y*stride + x] = fp[ref_row * fstride + ax + x];
        }
        else
        {
            for( int y = 0; y < size; y++ )
                for( int x = 0; x < size; x++ )
                    p_dst[y*stride + x] = p_dst[-stride + x];
        }
    }
    else if( mode == 1 ) /* H / left */
    {
        int ref_col = X264_MAX(ax - 1, 0);
        if( fp )
        {
            for( int y = 0; y < size; y++ )
            {
                pixel val = fp[(ay + y) * fstride + ref_col];
                for( int x = 0; x < size; x++ )
                    p_dst[y*stride + x] = val;
            }
        }
        else
        {
            for( int y = 0; y < size; y++ )
                for( int x = 0; x < size; x++ )
                    p_dst[y*stride + x] = p_dst[y*stride - 1];
        }
    }
    else /* DC (mode 3) - matches decoder's predict_intra case 3 */
    {
        int fill;
        if( fp )
        {
            if( ax == 0 && ay == 0 )
                fill = 0x80;
            else if( ax >= 1 && ay >= 1 )
            {
                int left = 0, top = 0;
                for( int y = 0; y < size; y++ ) left += fp[(ay + y) * fstride + ax - 1];
                for( int x = 0; x < size; x++ ) top  += fp[(ay - 1) * fstride + ax + x];
                fill = ((left + top) * 2 / (2*size) + 1) / 2;
            }
            else if( ax >= 1 )
            {
                int left = 0;
                for( int y = 0; y < size; y++ ) left += fp[(ay + y) * fstride + ax - 1];
                fill = (left * 2 / size + 1) / 2;
            }
            else /* ay >= 1 */
            {
                int top = 0;
                for( int x = 0; x < size; x++ ) top += fp[(ay - 1) * fstride + ax + x];
                fill = (top * 2 / size + 1) / 2;
            }
        }
        else
        {
            if( ax == 0 && ay == 0 )
                fill = 0x80;
            else if( ax >= 1 && ay >= 1 )
            {
                int left = 0, top = 0;
                for( int y = 0; y < size; y++ ) left += p_dst[y*stride - 1];
                for( int x = 0; x < size; x++ ) top  += p_dst[-stride + x];
                fill = ((left + top) * 2 / (2*size) + 1) / 2;
            }
            else if( ax >= 1 )
            {
                int left = 0;
                for( int y = 0; y < size; y++ ) left += p_dst[y*stride - 1];
                fill = (left * 2 / size + 1) / 2;
            }
            else /* ay >= 1 */
            {
                int top = 0;
                for( int x = 0; x < size; x++ ) top += p_dst[-stride + x];
                fill = (top * 2 / size + 1) / 2;
            }
        }
        for( int y = 0; y < size; y++ )
            for( int x = 0; x < size; x++ )
                p_dst[y*stride + x] = fill;
    }
}
#endif

static ALWAYS_INLINE void x264_mb_encode_i4x4( x264_t *h, int p, int idx, int i_qp, int i_mode, int b_predict )
{
    int nz;
    pixel *p_src = &h->mb.pic.p_fenc[p][block_idx_xy_fenc[idx]];
    pixel *p_dst = &h->mb.pic.p_fdec[p][block_idx_xy_fdec[idx]];
    ALIGNED_ARRAY_64( dctcoef, dct4x4,[16] );

    if( b_predict )
    {
#if !HIGH_BIT_DEPTH
        if( h->param.i_mobiclip && p == 0 )
        {
            /* Convert the H.264 prediction mode to the Mobiclip mode exactly as
             * cavlc.c does (fix collapses DC_LEFT/TOP/128->DC and VL->HU), so the
             * pixels we reconstruct here match the mode written to the stream. */
            /* Convert x264 internal I4x4 mode to H.264 standard mode number.
             * The global x264_mb_pred_mode4x4_fix table is BROKEN in this fork
             * because I_PRED_4x4_PLANE=2 was inserted into the enum, shifting
             * values 3-8, but the fix table was not updated for the shift. */
            static const uint8_t x264_intra_to_h264[13] =
                { 2,0,1,2,2,8,6,5,4,3,2,2,2 };
            int i_h264_mode = x264_intra_to_h264[ (unsigned)i_mode + 1 < 13 ? i_mode + 1 : 0 ];
            int mobi_mode = mobi_h264_to_mobiclip_mode[ i_h264_mode < 9 ? i_h264_mode : 8 ];
            mobi_predict_4x4( h, p_dst, idx, mobi_mode );
        }
        else
#endif
        if( h->mb.b_lossless )
            x264_predict_lossless_4x4( h, p_dst, p, idx, i_mode );
        else
            h->predict_4x4[i_mode]( p_dst );
    }

    if( h->mb.b_lossless )
    {
        nz = h->zigzagf.sub_4x4( h->dct.luma4x4[p*16+idx], p_src, p_dst );
        h->mb.cache.non_zero_count[x264_scan8[p*16+idx]] = nz;
        h->mb.i_cbp_luma |= nz<<(idx>>2);
        return;
    }

    h->dctf.sub4x4_dct( dct4x4, p_src, p_dst );

    int mobi_intra = (h->param.i_mobiclip && p == 0 && !b_predict &&
                      mobi_v9_inter_luma_on() &&
                      mobi_v9_inter_source_flat(h,p,idx)) ? 0 : 1;
    nz = x264_quant_4x4( h, dct4x4, i_qp, ctx_cat_plane[DCT_LUMA_4x4][p], mobi_intra, p, idx );
    h->mb.cache.non_zero_count[x264_scan8[p*16+idx]] = nz;
#if !HIGH_BIT_DEPTH
    /* Always write luma4x4 in Mobiclip mode to clear stale analysis data. */
    if( h->param.i_mobiclip && p == 0 )
        for( int zz = 0; zz < 16; zz++ )
            h->dct.luma4x4[p*16+idx][zz] = dct4x4[mobi_zigzag4x4[zz]];
#endif
    if( nz )
    {
#if !HIGH_BIT_DEPTH
        if( !h->param.i_mobiclip || p != 0 )
#endif
        for( int zz = 0; zz < 16; zz++ )
            h->dct.luma4x4[p*16+idx][zz] = dct4x4[mobi_zigzag4x4[zz]];
        if( 1 ) /* mobi dequant always for matching mobiclip decoder */
        {
            int qx = i_qp % 6;
            int qtab64[16];
            /* Reconstruction uses << 2 (qy=2), matching the header QP = qx + 12.
             * Forward quant used unshifted mobi_q4[qx], so level=16R/step.
             * Here: level * (step<<2) >> 6 = 16R * 4 / 64 = R. */
            for( int zz = 0; zz < 16; zz++ )
                qtab64[mobi_zigzag4x4[zz]] = mobi_q4[qx][zz] << (2 + mobi_qyx(h));
            /* Dequantize into a 32-bit matrix: level*qtab (level up to ~hundreds,
             * qtab up to ~29<<2) overflows the int16 dct4x4 buffer, and the
             * inverse4 row/column sums overflow it further.  The decoder uses
             * int mat[]; mirror that exactly (this is the same fix as chroma
             * 8x8) or large-coefficient blocks reconstruct wrong and the error
             * drifts through P-frames as visible shearing. */
            int mat[16];
            /* Re-quantization guard.  The Mobiclip decoder reconstructs each
             * pixel as MinMaxTable[0x40 + prediction + (residual>>6)] with NO
             * bounds check.  The table is 384 entries (a 0..255 ramp with 64
             * zero/255 guard entries each side), so prediction+residual must
             * stay in [-64,319].  DCT ringing on sharp edges (e.g. the first
             * frame's high-contrast logo) can overshoot this; the real Wii then
             * reads memory outside the table and the garbage cascades through
             * intra prediction (green corruption).  Genuine streams never
             * overshoot.  Iteratively attenuate the coefficients (AC first, then
             * DC) and re-run the decoder-exact inverse transform until every
             * reconstructed pixel's index is in range; worst case the block
             * degrades to pure prediction. */
            for( int mobi_pass = 0; ; mobi_pass++ )
            {
                for( int i = 0; i < 16; i++ )
                    mat[i] = (int)dct4x4[i] * qtab64[i];
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
                        int tmp = mat[y*4+x];
                        mat[y*4+x] = mat[x*4+y];
                        mat[x*4+y] = tmp;
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
                {
                    pixel *md = p_dst;
                    for( int y = 0; y < 4 && !oob; y++ )
                    {
                        for( int x = 0; x < 4; x++ )
                        {
                            int s = md[x] + mat[y*4+x];
                            if( s < -64 || s > 319 ) { oob = 1; break; }
                        }
                        md += FDEC_STRIDE;
                    }
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
            /* The attenuation may have changed the levels; re-store the coded
             * coefficients so the bitstream matches the reconstruction. */
            if( h->param.i_mobiclip && p == 0 )
                for( int zz = 0; zz < 16; zz++ )
                    h->dct.luma4x4[p*16+idx][zz] = dct4x4[mobi_zigzag4x4[zz]];
            if( h->param.i_mobiclip && p == 0 )
            {
                pixel pred_flat[16], fenc_flat[16];
                for( int yy = 0; yy < 4; yy++ )
                    for( int xx = 0; xx < 4; xx++ )
                    {
                        pred_flat[yy*4+xx] = p_dst[yy*FDEC_STRIDE+xx];
                        fenc_flat[yy*4+xx] = p_src[yy*FENC_STRIDE+xx];
                    }
                mobi_coeff_dump( h, 0 /*Y*/, 0 /*intra*/, i_qp, 16, h->dct.luma4x4[p*16+idx], pred_flat, fenc_flat );
            }
            pixel *mobi_dst = p_dst;
            for( int y = 0; y < 4; y++ )
            {
                for( int x = 0; x < 4; x++ )
                    mobi_dst[x] = x264_clip_pixel( mobi_dst[x] + mat[y*4+x] );
                mobi_dst += FDEC_STRIDE;
            }
        }
        else
        {
            h->quantf.dequant_4x4( dct4x4, h->dequant4_mf[CQM_4IY], i_qp );
            h->dctf.add4x4_idct( p_dst, dct4x4 );
        }
    }
}

static ALWAYS_INLINE void x264_mb_encode_i8x8( x264_t *h, int p, int idx, int i_qp, int i_mode, pixel *edge, int b_predict )
{
    int x = idx&1;
    int y = idx>>1;
    int nz;
    pixel *p_src = &h->mb.pic.p_fenc[p][8*x + 8*y*FENC_STRIDE];
    pixel *p_dst = &h->mb.pic.p_fdec[p][8*x + 8*y*FDEC_STRIDE];
    ALIGNED_ARRAY_64( dctcoef, dct8x8,[64] );
    ALIGNED_ARRAY_32( pixel, edge_buf,[36] );

    if( b_predict )
    {
        if( !edge )
        {
            h->predict_8x8_filter( p_dst, edge_buf, h->mb.i_neighbour8[idx], x264_pred_i4x4_neighbors[i_mode] );
            edge = edge_buf;
        }

        if( h->mb.b_lossless )
            x264_predict_lossless_8x8( h, p_dst, p, idx, i_mode, edge );
        else
            h->predict_8x8[i_mode]( p_dst, edge );
    }

    if( h->mb.b_lossless )
    {
        nz = h->zigzagf.sub_8x8( h->dct.luma8x8[p*4+idx], p_src, p_dst );
        STORE_8x8_NNZ( p, idx, nz );
        h->mb.i_cbp_luma |= nz<<idx;
        return;
    }

    h->dctf.sub8x8_dct8( dct8x8, p_src, p_dst );

    /* R1 release cleanup: a read-only MOBI_LUMA8X8_EXACT_PROBE comparison
     * hook lived here in the research worktree, depending on
     * mobi_luma8x8_forward_exact() from the banned/parked luma-8x8
     * experiment's header (not carried into this tree). It never altered
     * coded data even when active (its own comment: "does not replace any
     * coded data") -- removed here rather than re-adding the dependency,
     * since luma 8x8 stays untouched/unshipped per the standing ban. */

    nz = x264_quant_8x8( h, dct8x8, i_qp, ctx_cat_plane[DCT_LUMA_8x8][p], 1, p, idx );
    if( nz )
    {
        h->mb.i_cbp_luma |= 1<<idx;
		for (int i = 0; i < 64; i++)
			h->dct.luma8x8[p * 4 + idx][i] = dct8x8[ZigZagTable8x8[i]];
        //h->zigzagf.scan_8x8( h->dct.luma8x8[p*4+idx], dct8x8 );
        if( 1 )
        {
            int qx = i_qp % 6;
            /* Decoder contract: header_qp=(i_qp%6)+12+6*MOBI_QYX, so
             * qx=header_qp%6 and r6=(header_qp/6)-2=MOBI_QYX.  Local
             * reconstruction must use the identical dequant multiplier or
             * encoder references diverge from decoder references after the
             * first coded 8x8 block. */
            int qtab[64];
            int r6 = mobi_qyx( h );
            for( int zz = 0; zz < 64; zz++ )
                qtab[ZigZagTable8x8[zz]] = (int)mobi_q8[qx][zz] << r6;
            for( int i = 0; i < 64; i++ )
                dct8x8[i] = dct8x8[i] * (unsigned)qtab[i];
        }
        else
        {
            h->quantf.dequant_8x8( dct8x8, h->dequant8_mf[CQM_8IY], i_qp );
        }
        h->dctf.add8x8_idct8( p_dst, dct8x8 );
        STORE_8x8_NNZ( p, idx, 1 );
    }
    else
        STORE_8x8_NNZ( p, idx, 0 );
}

#endif
