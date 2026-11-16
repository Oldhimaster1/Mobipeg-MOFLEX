/*****************************************************************************
 * analyse.c: macroblock analysis
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

#include <math.h>
#include <time.h>
#include "common/common.h"
#include "macroblock.h"
#include "me.h"
#include "ratecontrol.h"
#include "analyse.h"
#include "rdo.c"

/* Optional fine-grained motion-analysis profiling. No timers run unless the
 * same MOBI_PROFILE=1 opt-in used by encoder.c is enabled. */
static int mobi_aprof_enabled = -1;
static uint64_t mobi_aprof_ns[11];
static uint64_t mobi_aprof_calls[11];
static const char * const mobi_aprof_names[11] = {
    "motion_p16x16", "motion_p8x8", "motion_sub8", "motion_p16x8",
    "motion_p8x16", "intra_search", "inter_rd", "intra_rd", "rd_refine",
    "intra_rd_refine", "motion_qpel_rd"
};
static uint64_t mobi_aprof_tick( void )
{
    struct timespec ts;
    clock_gettime( CLOCK_MONOTONIC, &ts );
    return (uint64_t)ts.tv_sec * 1000000000ULL + ts.tv_nsec;
}
static void mobi_aprof_dump( void )
{
    for( int i = 0; i < 11; i++ )
        fprintf( stderr, "[MOBI_ANALYSIS] %-18s calls=%llu ms=%.3f\n",
                 mobi_aprof_names[i], (unsigned long long)mobi_aprof_calls[i],
                 mobi_aprof_ns[i] / 1e6 );
}
#define MOBI_APROF( index, body ) do { \
    uint64_t _start = mobi_aprof_enabled == 1 ? mobi_aprof_tick() : 0; \
    body; \
    if( mobi_aprof_enabled == 1 ) { \
        mobi_aprof_ns[index] += mobi_aprof_tick() - _start; \
        mobi_aprof_calls[index]++; \
    } \
} while( 0 )

typedef struct
{
    x264_me_t me16x16;
    x264_me_t bi16x16;      /* for b16x16 BI mode, since MVs can differ from l0/l1 */
    x264_me_t me8x8[4];
    x264_me_t me4x4[4][4];
    x264_me_t me8x4[4][2];
    x264_me_t me4x8[4][2];
    x264_me_t me16x8[2];
    x264_me_t me8x16[2];
    int i_rd16x16;
    int i_cost8x8;
    int i_cost4x4[4]; /* cost per 8x8 partition */
    int i_cost8x4[4]; /* cost per 8x8 partition */
    int i_cost4x8[4]; /* cost per 8x8 partition */
    int i_cost16x8;
    int i_cost8x16;
    /* [ref][0] is 16x16 mv, [ref][1..4] are 8x8 mv from partition [0..3], [ref][5] is for alignment */
    ALIGNED_8( int16_t mvc[32][6][2] );
} x264_mb_analysis_list_t;

typedef struct
{
    /* conduct the analysis using this lamda and QP */
    int i_lambda;
    int i_lambda2;
    int i_qp;
    uint16_t *p_cost_mv;
    uint16_t *p_cost_ref[2];
    int i_mbrd;


    /* I: Intra part */
    /* Take some shortcuts in intra search if intra is deemed unlikely */
    int b_fast_intra;
    int b_force_intra; /* For Periodic Intra Refresh.  Only supported in P-frames. */
    int b_avoid_topright; /* For Periodic Intra Refresh: don't predict from top-right pixels. */
    int b_try_skip;

    /* Luma part */
    int i_satd_i16x16;
    int i_satd_i16x16_dir[7];
    int i_predict16x16;

    int i_satd_i8x8;
    int i_cbp_i8x8_luma;
    ALIGNED_16( uint16_t i_satd_i8x8_dir[4][16] );
    int i_predict8x8[4];

    int i_satd_i4x4;
    int i_predict4x4[16];

    int i_satd_pcm;

    /* Chroma part */
    int i_satd_chroma;
    int i_satd_chroma_dir[7];
    int i_predict8x8chroma;

    /* II: Inter part P/B frame */
    x264_mb_analysis_list_t l0;
    x264_mb_analysis_list_t l1;

    int i_cost16x16bi; /* used the same ref and mv as l0 and l1 (at least for now) */
    int i_cost16x16direct;
    int i_cost8x8bi;
    int i_cost8x8direct[4];
    int i_satd8x8[3][4]; /* [L0,L1,BI][8x8 0..3] SATD only */
    int i_cost_est16x8[2]; /* Per-partition estimated cost */
    int i_cost_est8x16[2];
    int i_cost16x8bi;
    int i_cost8x16bi;
    int i_rd16x16bi;
    int i_rd16x16direct;
    int i_rd16x8bi;
    int i_rd8x16bi;
    int i_rd8x8bi;

    int i_mb_partition16x8[2]; /* mb_partition_e */
    int i_mb_partition8x16[2];
    int i_mb_type16x8; /* mb_class_e */
    int i_mb_type8x16;

    int b_direct_available;
    int b_early_terminate;

} x264_mb_analysis_t;

/* ACT22.1B rate-model bias trace, Hook A: analysis-stage estimated cost.
 * Read-only observability, following the exact pattern of the existing
 * mobi_coeff_dump() in encoder/macroblock.h: lazy-init static FILE* opened
 * from a getenv() path, no-op if MOBI_ACT22_RATE_TRACE is unset (zero
 * behavioral change when disabled). Called once at the single end-of-function
 * point of x264_macroblock_analyse(), after h->mb.i_type is finalized by
 * every code path. Only READS fields already computed by the real decision
 * logic (h->mb.i_type/i_partition/i_qp and the x264_mb_analysis_t a costs) --
 * never writes anything that can influence the encode. */
static ALWAYS_INLINE void mobi_act22_rate_trace_analyse( x264_t *h, x264_mb_analysis_t *a )
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
            snprintf( path, sizeof(path), "%s_analyse.csv", prefix );
            fp = fopen( path, "w" );
            if( fp )
                fprintf( fp, "frame_index,mb_x,mb_y,slice_type,i_type,i_partition,qp,est_cost\n" );
        }
        enabled = fp ? 1 : 0;
    }
    if( !enabled ) return;

    int est_cost;
    switch( h->mb.i_type )
    {
        case I_16x16: est_cost = a->i_satd_i16x16; break;
        case I_4x4:   est_cost = a->i_satd_i4x4;   break;
        case I_8x8:   est_cost = a->i_satd_i8x8;   break;
        case I_PCM:   est_cost = a->i_satd_pcm;    break;
        case P_SKIP:
        case B_SKIP:
        case B_DIRECT:
            est_cost = 0;
            break;
        case P_L0:
            switch( h->mb.i_partition )
            {
                case D_16x16: est_cost = a->l0.me16x16.cost; break;
                case D_16x8:  est_cost = a->i_cost16x8bi;    break;
                case D_8x16:  est_cost = a->i_cost8x16bi;    break;
                default:      est_cost = a->l0.me16x16.cost; break;
            }
            break;
        case P_8x8:
            /* best-effort: this content does not exercise this path per the
             * control's mb-type histogram (0% P8x8) -- low-confidence if it
             * appears at all. */
            est_cost = a->i_cost8x8bi;
            break;
        default:
            /* B_* types: this 24-frame clip is I/P-only (0% B per the
             * control log) so this branch is not expected to fire. Best
             * effort only -- just don't crash. */
            if( IS_INTRA( h->mb.i_type ) )
                est_cost = a->i_satd_i4x4;
            else
                est_cost = a->i_rd16x16bi;
            break;
    }

    fprintf( fp, "%d,%d,%d,%d,%d,%d,%d,%d\n",
             h->fdec->i_frame, h->mb.i_mb_x, h->mb.i_mb_y, h->sh.i_type,
             h->mb.i_type, h->mb.i_partition, h->mb.i_qp, est_cost );
}

/* ACT22.2A: I_4x4-vs-P_L0 pure-simulation hook (env MOBI_ACT22_2A_SIM).
 * Read-only observability, same lazy-init getenv/FILE* pattern as
 * mobi_coeff_dump / Hook A above. NEVER writes to h->mb.*, h->param.*, or
 * any variable read by the real encode -- purely computes and logs what a
 * calibrated-actual-bits comparison WOULD have decided, for macroblocks
 * where stock analysis actually picked I_4x4 in a P-slice.
 *
 * Eligibility (see ACT22_2A_REPORT.md Step 1 for the full source proof):
 * mb_analyse_inter_p16x16() unconditionally runs before mb_analyse_intra()
 * on the normal (non-skip) P-slice path, and always overwrites
 * a->l0.me16x16.cost with a genuine ME result (it starts every call by
 * setting a->l0.me16x16.cost = INT_MAX, then the >=1 reference-frame search
 * loop always overwrites it). The ONE path that reaches mb_analyse_intra()
 * WITHOUT calling mb_analyse_inter_p16x16() first is the b_force_intra ->
 * "goto intra_analysis" shortcut (periodic intra refresh, h->param.b_intra_refresh),
 * which never touches l0.me16x16.cost at all. a->b_force_intra is the exact
 * per-MB flag for that path, so gating on !a->b_force_intra is a proof, not
 * an assumption. (This build's anchor command never passes intra-refresh,
 * so b_force_intra is expected to be 0 for every row in practice; the check
 * is defensive rather than a no-op in principle.)
 *
 * Also from source: a->i_satd_i4x4 is ALWAYS fully computed over all 16
 * 4x4 blocks (no early break) whenever the I4x4 code path runs, because
 * mb_analyse_init() forces a->b_early_terminate=0 for mobiclip (encoder/
 * analyse.c ~line 393-394), which makes the I4x4 loop's i_satd_thresh
 * unconditionally COST_MAX (encoder/analyse.c ~line 978) -- so the
 * `if (i_cost > i_satd_thresh || idx==15) break;` early-exit at line ~1061
 * can only fire via idx==15, i.e. after all 16 blocks. The I8x8 block that
 * could otherwise return early is entirely disabled for mobiclip (its flag
 * bit X264_ANALYSE_I8x8 is cleared in encoder/encoder.c because
 * b_transform_8x8=0 for mobiclip -- see libavcodec/libx264.c ~line 1302).
 *
 * Distortion/rate decomposition (source-derived, not estimated):
 *   I_4x4:  i_cost = lambda*(24+16) [base predmode cost] + sum over the 16
 *           4x4 blocks of (chosen-mode SATD + 3*lambda [mode-signal cost]).
 *           The per-block "-3*lambda" search bias (favoring the predicted
 *           mode) exactly cancels against the unconditional "+3*lambda"
 *           added back at accumulation (encoder/analyse.c ~line 1060), so
 *           the algebra reduces to: i_cost = 88*lambda + sum(raw SATD).
 *           rate_component = 88*lambda ; distortion_component = i_cost - rate_component.
 *   P_L0:   x264_me_t (encoder/me.h) documents cost_mv as "lambda * nbits
 *           for the chosen mv" and cost as "satd + lambda * nbits" --
 *           i.e. the struct itself gives the decomposition directly:
 *           rate_component = me16x16.cost_mv ; distortion_component = me16x16.cost - cost_mv.
 *
 * Calibrated actual-bits model: quantile-bucketed lookup tables built from
 * the ACT22.1B evidence bundle (evidence\act22_1b_rate_trace_bias_20260804_085551\
 * ACT22_1B_JOINED.csv), P-slice rows only, mapping each mode's OWN
 * analysis-stage cost (the only predictor available for both the real,
 * written mode AND the un-taken counterfactual alternative) to the mean
 * REAL bits_actual observed for real MBs of that mode in that cost bucket.
 * P_L0 additionally buckets on MV magnitude (quarter-pel), which
 * ACT22.1B's own grouped stats showed was a structured predictor of bias;
 * I_4x4 has no analogous free predictor available for the untaken
 * alternative so uses a 1D cost-only bucket. Table generation script:
 * evidence\act22_1b_rate_trace_bias_20260804_085551\build_calibration.py
 * (n=2901 I_4x4-in-P rows, n=4974 P_L0 rows; every 2D cell used has n>=13,
 * falls back to the 1D cost-bucket mean if a cell would have n<5). */
static const int    MOBI_ACT22_2A_I4X4_COST_EDGES[4] = {839, 1407, 2259, 3562};
static const double MOBI_ACT22_2A_I4X4_BITS[5] = {102.88, 174.69, 307.33, 457.96, 659.88};
static const int    MOBI_ACT22_2A_PL0_COST_EDGES[4] = {284, 432, 690, 1658};
static const double MOBI_ACT22_2A_PL0_BITS[5][4] = {
    {2.65, 10.46, 13.82, 22.74},
    {4.6, 12.12, 14.86, 23.35},
    {12.32, 19.71, 32.24, 39.79},
    {81.36, 126.82, 104.86, 115.47},
    {384.2, 306.06, 301.57, 324.23}
};

static ALWAYS_INLINE int mobi_act22_2a_bucket( int v, const int *edges, int n_edges )
{
    for( int i = 0; i < n_edges; i++ )
        if( v <= edges[i] ) return i;
    return n_edges;
}

static ALWAYS_INLINE int mobi_act22_2a_mv_bucket( double mag )
{
    if( mag == 0 )  return 0;
    if( mag <= 4 )  return 1;
    if( mag <= 16 ) return 2;
    return 3;
}

static ALWAYS_INLINE void mobi_act22_2a_sim( x264_t *h, x264_mb_analysis_t *a )
{
    static int enabled = -1;
    static FILE *fp = NULL;
    if( enabled < 0 )
    {
        const char *prefix = getenv( "MOBI_ACT22_2A_SIM" );
        enabled = prefix ? 1 : 0;
        if( enabled )
        {
            char path[4096];
            snprintf( path, sizeof(path), "%s_sim.csv", prefix );
            fp = fopen( path, "w" );
            if( fp )
                fprintf( fp, "frame_index,mb_x,mb_y,selected_mode,best_i4x4_analysis_cost,best_pl0_analysis_cost,"
                              "i4x4_distortion_component,pl0_distortion_component,i4x4_stock_rate_component,pl0_stock_rate_component,"
                              "i4x4_calibrated_actual_bits,pl0_calibrated_actual_bits,lambda,stock_decision,corrected_simulated_decision,"
                              "projected_actual_bit_change,projected_distortion_change,corrected_rd_delta,classification,rejection_reason\n" );
        }
        enabled = fp ? 1 : 0;
    }
    if( !enabled ) return;

    /* Only P-slice MBs where stock analysis selected I_4x4 are in scope. */
    if( h->sh.i_type != SLICE_TYPE_P || h->mb.i_type != I_4x4 ) return;

    if( a->b_force_intra )
    {
        /* P_L0 alternative was never evaluated for this MB -- do not
         * fabricate a value. */
        fprintf( fp, "%d,%d,%d,%d,,,,,,,,,,I_4x4,,,,,NO_ALTERNATIVE_COMPUTED,b_force_intra_path_skips_inter_search\n",
                 h->fdec->i_frame, h->mb.i_mb_x, h->mb.i_mb_y, h->mb.i_type );
        return;
    }

    int lambda = a->i_lambda;
    int i4x4_cost = a->i_satd_i4x4;
    int pl0_cost  = a->l0.me16x16.cost;

    int i4x4_rate = 88 * lambda;
    int i4x4_dist = i4x4_cost - i4x4_rate;
    int pl0_rate  = a->l0.me16x16.cost_mv;
    int pl0_dist  = pl0_cost - pl0_rate;

    int mvx = a->l0.me16x16.mv[0];
    int mvy = a->l0.me16x16.mv[1];
    double mv_mag = sqrt( (double)mvx*mvx + (double)mvy*mvy );

    int i4_b  = mobi_act22_2a_bucket( i4x4_cost, MOBI_ACT22_2A_I4X4_COST_EDGES, 4 );
    double i4x4_calib_bits = MOBI_ACT22_2A_I4X4_BITS[i4_b];

    int pl0_cb = mobi_act22_2a_bucket( pl0_cost, MOBI_ACT22_2A_PL0_COST_EDGES, 4 );
    int pl0_mb = mobi_act22_2a_mv_bucket( mv_mag );
    double pl0_calib_bits = MOBI_ACT22_2A_PL0_BITS[pl0_cb][pl0_mb];

    int strict = ( pl0_calib_bits < i4x4_calib_bits ) && ( pl0_dist <= i4x4_dist );
    double rd_i4  = (double)i4x4_dist + lambda * i4x4_calib_bits;
    double rd_pl0 = (double)pl0_dist  + lambda * pl0_calib_bits;
    int positive_rd = !strict && ( rd_pl0 < rd_i4 ) && ( pl0_dist > i4x4_dist );

    const char *classification;
    const char *rejection_reason = "";
    int corrected_is_pl0 = 0;
    if( strict )            { classification = "STRICT_DOMINANCE"; corrected_is_pl0 = 1; }
    else if( positive_rd )  { classification = "POSITIVE_RD";      corrected_is_pl0 = 1; }
    else
    {
        classification = "REJECT";
        if( pl0_calib_bits >= i4x4_calib_bits && pl0_dist >= i4x4_dist )
            rejection_reason = "HIGHER_BITS_AND_DISTORTION";
        else if( rd_pl0 >= rd_i4 )
            rejection_reason = "MARGINAL_RD_NEGATIVE";
        else
            rejection_reason = "OTHER";
    }

    double proj_bit_change  = corrected_is_pl0 ? ( pl0_calib_bits - i4x4_calib_bits ) : 0.0;
    double proj_dist_change = corrected_is_pl0 ? (double)( pl0_dist - i4x4_dist )     : 0.0;
    double corrected_rd_delta = rd_pl0 - rd_i4;

    fprintf( fp, "%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%.2f,%.2f,%d,%s,%s,%.2f,%.2f,%.2f,%s,%s\n",
             h->fdec->i_frame, h->mb.i_mb_x, h->mb.i_mb_y, h->mb.i_type,
             i4x4_cost, pl0_cost, i4x4_dist, pl0_dist, i4x4_rate, pl0_rate,
             i4x4_calib_bits, pl0_calib_bits, lambda,
             "I_4x4", corrected_is_pl0 ? "P_L0" : "I_4x4",
             proj_bit_change, proj_dist_change, corrected_rd_delta,
             classification, rejection_reason );
}

/* ACT22.3B: real activation of the ACT22.3 proven-strict/quality-win MV
 * replacement set (env MOBI_ACT22_3_ACTIVATE=<path to ACT22_3_WINNERS.csv>).
 * Unlike every other ACT22.x hook, this ONE genuinely changes the encode --
 * but ONLY for the exact (frame,mb_x,mb_y) set the ACT22.3 simulation
 * classified STRICT_DOMINANCE/QUALITY_WIN, nothing broader. Default
 * (env unset) is a true no-op: identical to every prior gate's baseline. */
/* Raised from 8192->65536 in ACT22.4 (300f had 31187 winners), and again
 * here in ACT22.6 for the full 1866-frame clip (357713 eligible MBs,
 * 190373 winners at ACT25 settings). A per-frame index (below) keeps
 * lookup cheap even at this size -- a naive O(n) scan per MB would have
 * been ~357713 x 190373 worst case at full-clip scale. */
#define MOBI_ACT22_3_MAX_WINNERS 262144
#define MOBI_ACT22_3_MAX_FRAMES 4096
typedef struct { int frame, mbx, mby, mvx, mvy; } mobi_act22_3_winner_t;
static mobi_act22_3_winner_t mobi_act22_3_winners[MOBI_ACT22_3_MAX_WINNERS];
static int mobi_act22_3_n_winners = -1; /* -1 = not loaded yet */
/* Per-frame [start,count) range into mobi_act22_3_winners, built assuming
 * the input CSV is sorted by frame_index ascending (true for every
 * ACT22_x_WINNERS.csv this pipeline has ever exported -- Python's
 * sorted() call on export). Falls back to a full linear scan if that
 * assumption is ever violated (detected at load time). */
static int mobi_act22_3_frame_start[MOBI_ACT22_3_MAX_FRAMES];
static int mobi_act22_3_frame_count[MOBI_ACT22_3_MAX_FRAMES];
static int mobi_act22_3_sorted_ok = 0;

static void mobi_act22_3_load_winners( void )
{
    mobi_act22_3_n_winners = 0;
    for( int i = 0; i < MOBI_ACT22_3_MAX_FRAMES; i++ )
    {
        mobi_act22_3_frame_start[i] = -1;
        mobi_act22_3_frame_count[i] = 0;
    }
    const char *path = getenv( "MOBI_ACT22_3_ACTIVATE" );
    if( !path ) return;
    FILE *f = fopen( path, "r" );
    if( !f ) return;
    char line[512];
    if( !fgets( line, sizeof(line), f ) ) { fclose(f); return; } /* header */
    int last_frame = -1;
    int sorted = 1;
    while( fgets( line, sizeof(line), f ) && mobi_act22_3_n_winners < MOBI_ACT22_3_MAX_WINNERS )
    {
        int frame, mbx, mby, mvx, mvy;
        if( sscanf( line, "%d,%d,%d,%d,%d,", &frame, &mbx, &mby, &mvx, &mvy ) == 5 )
        {
            int idx = mobi_act22_3_n_winners;
            mobi_act22_3_winner_t *w = &mobi_act22_3_winners[idx];
            w->frame = frame; w->mbx = mbx; w->mby = mby; w->mvx = mvx; w->mvy = mvy;
            mobi_act22_3_n_winners++;
            if( frame < last_frame ) sorted = 0;
            last_frame = frame;
            if( frame >= 0 && frame < MOBI_ACT22_3_MAX_FRAMES )
            {
                if( mobi_act22_3_frame_start[frame] < 0 )
                    mobi_act22_3_frame_start[frame] = idx;
                mobi_act22_3_frame_count[frame]++;
            }
            else
                sorted = 0; /* frame out of the per-frame index range -- force fallback */
        }
    }
    fclose( f );
    mobi_act22_3_sorted_ok = sorted;
}

static ALWAYS_INLINE void mobi_act22_3_activate( x264_t *h )
{
    if( mobi_act22_3_n_winners < 0 )
        mobi_act22_3_load_winners();
    if( mobi_act22_3_n_winners <= 0 ) return;
    if( h->sh.i_type != SLICE_TYPE_P || h->mb.i_type != P_L0 || h->mb.i_partition != D_16x16 ) return;

    int frame = h->fdec->i_frame, mbx = h->mb.i_mb_x, mby = h->mb.i_mb_y;
    int start = 0, count = mobi_act22_3_n_winners;
    if( mobi_act22_3_sorted_ok && frame >= 0 && frame < MOBI_ACT22_3_MAX_FRAMES && mobi_act22_3_frame_start[frame] >= 0 )
    {
        start = mobi_act22_3_frame_start[frame];
        count = mobi_act22_3_frame_count[frame];
    }
    else if( mobi_act22_3_sorted_ok )
        count = 0; /* sorted index says this frame has zero winners */

    for( int i = start; i < start + count; i++ )
    {
        mobi_act22_3_winner_t *w = &mobi_act22_3_winners[i];
        if( w->frame == frame && w->mbx == mbx && w->mby == mby )
        {
            for( int j = 0; j < 16; j++ )
            {
                int i8 = x264_scan8[0] + (j&3) + (j>>2)*8;
                h->mb.cache.mv[0][i8][0] = (int16_t)w->mvx;
                h->mb.cache.mv[0][i8][1] = (int16_t)w->mvy;
            }
            break;
        }
    }
}

/* TODO: calculate CABAC costs */
static const uint8_t i_mb_b_cost_table[X264_MBTYPE_MAX] =
{
    9, 9, 9, 9, 0, 0, 0, 1, 3, 7, 7, 7, 3, 7, 7, 7, 5, 9, 0
};
static const uint8_t i_mb_b16x8_cost_table[17] =
{
    0, 0, 0, 0, 0, 0, 0, 0, 5, 7, 7, 7, 5, 7, 9, 9, 9
};
static const uint8_t i_sub_mb_b_cost_table[13] =
{
    7, 5, 5, 3, 7, 5, 7, 3, 7, 7, 7, 5, 1
};
static const uint8_t i_sub_mb_p_cost_table[4] =
{
    5, 3, 3, 1
};

static void analyse_update_cache( x264_t *h, x264_mb_analysis_t *a );

static int init_costs( x264_t *h, float *logs, int qp )
{
    if( h->cost_mv[qp] )
        return 0;

    int mv_range = h->param.analyse.i_mv_range << PARAM_INTERLACED;
    int lambda = x264_lambda_tab[qp];
    /* factor of 4 from qpel, 2 from sign, and 2 because mv can be opposite from mvp */
    CHECKED_MALLOC( h->cost_mv[qp], (4*4*mv_range + 1) * sizeof(uint16_t) );
    h->cost_mv[qp] += 2*4*mv_range;
    for( int i = 0; i <= 2*4*mv_range; i++ )
    {
        h->cost_mv[qp][-i] =
        h->cost_mv[qp][i]  = X264_MIN( (int)(lambda * logs[i] + .5f), UINT16_MAX );
    }
    for( int i = 0; i < 3; i++ )
        for( int j = 0; j < 33; j++ )
            h->cost_table->ref[qp][i][j] = i ? X264_MIN( lambda * bs_size_te( i, j ), UINT16_MAX ) : 0;
    if( h->param.analyse.i_me_method >= X264_ME_ESA && !h->cost_mv_fpel[qp][0] )
    {
        for( int j = 0; j < 4; j++ )
        {
            CHECKED_MALLOC( h->cost_mv_fpel[qp][j], (4*mv_range + 1) * sizeof(uint16_t) );
            h->cost_mv_fpel[qp][j] += 2*mv_range;
            for( int i = -2*mv_range; i < 2*mv_range; i++ )
                h->cost_mv_fpel[qp][j][i] = h->cost_mv[qp][i*4+j];
        }
    }
    uint16_t *cost_i4x4_mode = h->cost_table->i4x4_mode[qp];
    for( int i = 0; i < 17; i++ )
        cost_i4x4_mode[i] = 3*lambda*(i!=8);
    return 0;
fail:
    return -1;
}

int x264_analyse_init_costs( x264_t *h )
{
    int mv_range = h->param.analyse.i_mv_range << PARAM_INTERLACED;
    float *logs = x264_malloc( (2*4*mv_range+1) * sizeof(float) );
    if( !logs )
        return -1;

    logs[0] = 0.718f;
    for( int i = 1; i <= 2*4*mv_range; i++ )
        logs[i] = log2f( i+1 ) * 2.0f + 1.718f;

    for( int qp = X264_MIN( h->param.rc.i_qp_min, QP_MAX_SPEC ); qp <= h->param.rc.i_qp_max; qp++ )
        if( init_costs( h, logs, qp ) )
            goto fail;

    if( init_costs( h, logs, X264_LOOKAHEAD_QP ) )
        goto fail;

    x264_free( logs );
    return 0;
fail:
    x264_free( logs );
    return -1;
}

void x264_analyse_free_costs( x264_t *h )
{
    int mv_range = h->param.analyse.i_mv_range << PARAM_INTERLACED;
    for( int i = 0; i < QP_MAX+1; i++ )
    {
        if( h->cost_mv[i] )
            x264_free( h->cost_mv[i] - 2*4*mv_range );
        for( int j = 0; j < 4; j++ )
        {
            if( h->cost_mv_fpel[i][j] )
                x264_free( h->cost_mv_fpel[i][j] - 2*mv_range );
        }
    }
}

void x264_analyse_weight_frame( x264_t *h, int end )
{
    for( int j = 0; j < h->i_ref[0]; j++ )
    {
        if( h->sh.weight[j][0].weightfn )
        {
            x264_frame_t *frame = h->fref[0][j];
            int width = frame->i_width[0] + PADH2;
            int i_padv = PADV << PARAM_INTERLACED;
            int offset, height;
            pixel *src = frame->filtered[0][0] - frame->i_stride[0]*i_padv - PADH_ALIGN;
            height = X264_MIN( 16 + end + i_padv, h->fref[0][j]->i_lines[0] + i_padv*2 ) - h->fenc->i_lines_weighted;
            offset = h->fenc->i_lines_weighted*frame->i_stride[0];
            h->fenc->i_lines_weighted += height;
            if( height )
                for( int k = j; k < h->i_ref[0]; k++ )
                    if( h->sh.weight[k][0].weightfn )
                    {
                        pixel *dst = h->fenc->weighted[k] - h->fenc->i_stride[0]*i_padv - PADH_ALIGN;
                        x264_weight_scale_plane( h, dst + offset, frame->i_stride[0],
                                                 src + offset, frame->i_stride[0],
                                                 width, height, &h->sh.weight[k][0] );
                    }
            break;
        }
    }
}

/* initialize an array of lambda*nbits for all possible mvs */
static void mb_analyse_load_costs( x264_t *h, x264_mb_analysis_t *a )
{
    a->p_cost_mv = h->cost_mv[a->i_qp];
    a->p_cost_ref[0] = h->cost_table->ref[a->i_qp][x264_clip3(h->sh.i_num_ref_idx_l0_active-1,0,2)];
    a->p_cost_ref[1] = h->cost_table->ref[a->i_qp][x264_clip3(h->sh.i_num_ref_idx_l1_active-1,0,2)];
}

static void mb_analyse_init_qp( x264_t *h, x264_mb_analysis_t *a, int qp )
{
    /* QRDO1 experiment (off by default): make Mobiclip analysis lambda use
     * the same QP phase and QYX tier as coefficient quantization. */
    int i_mobi_lambda_qp = qp;
    if( h->param.i_mobiclip && getenv("MOBI_QYX_RDO") && atoi(getenv("MOBI_QYX_RDO")) )
    {
        int i_qyx = h->param.i_mobi_qyx;
        const char *psz_qyx = getenv("MOBI_QYX");
        if( psz_qyx ) i_qyx = atoi( psz_qyx );
        i_qyx = x264_clip3( i_qyx, 0, 15 );
        i_mobi_lambda_qp = x264_clip3( (qp % 6) + 12 + 6 * i_qyx, 0, QP_MAX );
    }

    /* V7: test intermediate lambda indexes between x264 raw QP and the
     * emitted MobiClip quantization tier. Do not change reconstruction,
     * bitstream syntax, trellis or the existing V5 default. The original
     * MOBI_QYX_RDO experiment jumps all the way to the emitted QP and lost
     * quality; intermediate offsets must be measured against actual bytes. */
    if( h->param.i_mobiclip && !(getenv("MOBI_QYX_RDO") && atoi(getenv("MOBI_QYX_RDO"))) )
    {
        static int offset = -9999;
        if( offset == -9999 )
        {
            const char *env = getenv("MOBI_RDO_LAMBDA_DELTA");
            offset = env ? atoi(env) : 0;
        }
        i_mobi_lambda_qp = x264_clip3( qp + offset, 0, QP_MAX );
    }

    int effective_chroma_qp = h->chroma_qp_table[SPEC_QP(qp)] + X264_MAX( qp - QP_MAX_SPEC, 0 );
    a->i_lambda = x264_lambda_tab[i_mobi_lambda_qp];
    a->i_lambda2 = x264_lambda2_tab[i_mobi_lambda_qp];

    h->mb.b_trellis = h->param.analyse.i_trellis > 1 && a->i_mbrd;
    if( h->param.analyse.i_trellis )
    {
        h->mb.i_trellis_lambda2[0][0] = x264_trellis_lambda2_tab[0][qp];
        h->mb.i_trellis_lambda2[0][1] = x264_trellis_lambda2_tab[1][qp];
        h->mb.i_trellis_lambda2[1][0] = x264_trellis_lambda2_tab[0][effective_chroma_qp];
        h->mb.i_trellis_lambda2[1][1] = x264_trellis_lambda2_tab[1][effective_chroma_qp];
    }
    h->mb.i_psy_rd_lambda = a->i_lambda;
    /* Adjusting chroma lambda based on QP offset hurts PSNR but improves visual quality. */
    int chroma_offset_idx = X264_MIN( qp-effective_chroma_qp+12, MAX_CHROMA_LAMBDA_OFFSET );
    h->mb.i_chroma_lambda2_offset = h->param.analyse.b_psy ? x264_chroma_lambda2_offset_tab[chroma_offset_idx] : 256;

    if( qp > QP_MAX_SPEC )
    {
        h->nr_offset = h->nr_offset_emergency[qp-QP_MAX_SPEC-1];
        h->nr_residual_sum = h->nr_residual_sum_buf[1];
        h->nr_count = h->nr_count_buf[1];
        h->mb.b_noise_reduction = 1;
        qp = QP_MAX_SPEC; /* Out-of-spec QPs are just used for calculating lambda values. */
    }
    else
    {
        h->nr_offset = h->nr_offset_denoise;
        h->nr_residual_sum = h->nr_residual_sum_buf[0];
        h->nr_count = h->nr_count_buf[0];
        h->mb.b_noise_reduction = 0;
    }

    a->i_qp = h->mb.i_qp = qp;
    h->mb.i_chroma_qp = h->chroma_qp_table[qp];
}

static void mb_analyse_init( x264_t *h, x264_mb_analysis_t *a, int qp )
{
    int subme = h->param.analyse.i_subpel_refine - (h->sh.i_type == SLICE_TYPE_B);

    /* mbrd == 1 -> RD mode decision */
    /* mbrd == 2 -> RD refinement */
    /* mbrd == 3 -> QPRD */
    a->i_mbrd = (subme>=6) + (subme>=8) + (h->param.analyse.i_subpel_refine>=10);
    h->mb.b_deblock_rdo = h->param.analyse.i_subpel_refine >= 9 && h->sh.i_disable_deblocking_filter_idc != 1;
    a->b_early_terminate = h->param.analyse.i_subpel_refine < 11;
    /* Mobiclip forces I_4x4 (see the intra type decision).  Early termination
     * of the intra search can leave the per-4x4 prediction modes unanalysed
     * (garbage), which then get written to the bitstream by the forced-I_4x4
     * encode and desync the decoder.  Disable it so every 4x4 block always has
     * a valid analysed mode.  (Dropped during the upstream-x264 rebase.) */
    if( h->param.i_mobiclip )
        a->b_early_terminate = 0;

    mb_analyse_init_qp( h, a, qp );

    h->mb.b_transform_8x8 = 0;

    /* I: Intra part */
    a->i_satd_i16x16 =
    a->i_satd_i8x8   =
    a->i_satd_i4x4   = COST_MAX;
    a->i_satd_chroma = CHROMA_FORMAT ? COST_MAX : 0;

    /* non-RD PCM decision is inaccurate (as is psy-rd), so don't do it.
     * PCM cost can overflow with high lambda2, so cap it at COST_MAX. */
    uint64_t pcm_cost = ((uint64_t)X264_PCM_COST*a->i_lambda2 + 128) >> 8;
    a->i_satd_pcm = !h->param.i_avcintra_class && !h->mb.i_psy_rd && a->i_mbrd && pcm_cost < COST_MAX ? pcm_cost : COST_MAX;

    a->b_fast_intra = 0;
    a->b_avoid_topright = 0;
    h->mb.i_skip_intra =
        h->mb.b_lossless ? 0 :
        h->param.i_mobiclip ? 0 : /* Mobiclip: never skip intra re-encode (forced I_4x4) */
        a->i_mbrd ? 2 :
        !h->param.analyse.i_trellis && !h->param.analyse.i_noise_reduction;

    /* II: Inter part P/B frame */
    if( h->sh.i_type != SLICE_TYPE_I )
    {
        int i_fmv_range = 4 * h->param.analyse.i_mv_range;
        // limit motion search to a slightly smaller range than the theoretical limit,
        // since the search may go a few iterations past its given range
        int i_fpel_border = 6; // umh: 1 for diamond, 2 for octagon, 2 for hpel

        /* Calculate max allowed MV range.  x264 normally allows the MC to read
         * up to 24 pixels into the padded border.  The Mobiclip decoder reads
         * raw reference-frame data with NO border padding and rejects any MV
         * whose block falls outside [0,width]x[0,height] (predict_motion bounds
         * check), so restrict the range to keep the whole MB inside the frame
         * (a small negative margin leaves room for the half-pel +1 sample). */
        int mobi_border = h->param.i_mobiclip ? -20 : 24;
        h->mb.mv_min[0] = 4*( -16*h->mb.i_mb_x - mobi_border );
        h->mb.mv_max[0] = 4*( 16*( h->mb.i_mb_width - h->mb.i_mb_x - 1 ) + mobi_border );
        h->mb.mv_min_spel[0] = X264_MAX( h->mb.mv_min[0], -i_fmv_range );
        h->mb.mv_max_spel[0] = X264_MIN( h->mb.mv_max[0], i_fmv_range-1 );
        if( h->param.b_intra_refresh && h->sh.i_type == SLICE_TYPE_P )
        {
            int max_x = (h->fref[0][0]->i_pir_end_col * 16 - 3)*4; /* 3 pixels of hpel border */
            int max_mv = max_x - 4*16*h->mb.i_mb_x;
            /* If we're left of the refresh bar, don't reference right of it. */
            if( max_mv > 0 && h->mb.i_mb_x < h->fdec->i_pir_start_col )
                h->mb.mv_max_spel[0] = X264_MIN( h->mb.mv_max_spel[0], max_mv );
        }
        h->mb.mv_limit_fpel[0][0] = (h->mb.mv_min_spel[0]>>2) + i_fpel_border;
        h->mb.mv_limit_fpel[1][0] = (h->mb.mv_max_spel[0]>>2) - i_fpel_border;
        if( h->mb.i_mb_x == 0 && !(h->mb.i_mb_y & PARAM_INTERLACED) )
        {
            int mb_y = h->mb.i_mb_y >> SLICE_MBAFF;
            int thread_mvy_range = i_fmv_range;

            if( h->i_thread_frames > 1 )
            {
                int pix_y = (h->mb.i_mb_y | PARAM_INTERLACED) * 16;
                int thresh = pix_y + h->param.analyse.i_mv_range_thread;
                for( int i = (h->sh.i_type == SLICE_TYPE_B); i >= 0; i-- )
                    for( int j = 0; j < h->i_ref[i]; j++ )
                    {
                        int completed = x264_frame_cond_wait( h->fref[i][j]->orig, thresh );
                        thread_mvy_range = X264_MIN( thread_mvy_range, completed - pix_y );
                    }

                if( h->param.b_deterministic )
                    thread_mvy_range = h->param.analyse.i_mv_range_thread;
                if( PARAM_INTERLACED )
                    thread_mvy_range >>= 1;

                x264_analyse_weight_frame( h, pix_y + thread_mvy_range );
            }

            if( PARAM_INTERLACED )
            {
                /* 0 == top progressive, 1 == bot progressive, 2 == interlaced */
                for( int i = 0; i < 3; i++ )
                {
                    int j = i == 2;
                    mb_y = (h->mb.i_mb_y >> j) + (i == 1);
                    h->mb.mv_miny_row[i] = 4*( -16*mb_y - 24 );
                    h->mb.mv_maxy_row[i] = 4*( 16*( (h->mb.i_mb_height>>j) - mb_y - 1 ) + 24 );
                    h->mb.mv_miny_spel_row[i] = X264_MAX( h->mb.mv_miny_row[i], -i_fmv_range );
                    h->mb.mv_maxy_spel_row[i] = X264_MIN3( h->mb.mv_maxy_row[i], i_fmv_range-1, 4*thread_mvy_range );
                    h->mb.mv_miny_fpel_row[i] = (h->mb.mv_miny_spel_row[i]>>2) + i_fpel_border;
                    h->mb.mv_maxy_fpel_row[i] = (h->mb.mv_maxy_spel_row[i]>>2) - i_fpel_border;
                }
            }
            else
            {
                h->mb.mv_min[1] = 4*( -16*mb_y - (h->param.i_mobiclip ? -20 : 24) );
                h->mb.mv_max[1] = 4*( 16*( h->mb.i_mb_height - mb_y - 1 ) + (h->param.i_mobiclip ? -20 : 24) );
                h->mb.mv_min_spel[1] = X264_MAX( h->mb.mv_min[1], -i_fmv_range );
                h->mb.mv_max_spel[1] = X264_MIN3( h->mb.mv_max[1], i_fmv_range-1, 4*thread_mvy_range );
                h->mb.mv_limit_fpel[0][1] = (h->mb.mv_min_spel[1]>>2) + i_fpel_border;
                h->mb.mv_limit_fpel[1][1] = (h->mb.mv_max_spel[1]>>2) - i_fpel_border;
            }
        }
        if( PARAM_INTERLACED )
        {
            int i = MB_INTERLACED ? 2 : h->mb.i_mb_y&1;
            h->mb.mv_min[1] = h->mb.mv_miny_row[i];
            h->mb.mv_max[1] = h->mb.mv_maxy_row[i];
            h->mb.mv_min_spel[1] = h->mb.mv_miny_spel_row[i];
            h->mb.mv_max_spel[1] = h->mb.mv_maxy_spel_row[i];
            h->mb.mv_limit_fpel[0][1] = h->mb.mv_miny_fpel_row[i];
            h->mb.mv_limit_fpel[1][1] = h->mb.mv_maxy_fpel_row[i];
        }

        a->l0.me16x16.cost =
        a->l0.i_rd16x16    =
        a->l0.i_cost8x8    =
        a->l0.i_cost16x8   =
        a->l0.i_cost8x16   = COST_MAX;
        if( h->sh.i_type == SLICE_TYPE_B )
        {
            a->l1.me16x16.cost =
            a->l1.i_rd16x16    =
            a->l1.i_cost8x8    =
            a->i_cost8x8direct[0] =
            a->i_cost8x8direct[1] =
            a->i_cost8x8direct[2] =
            a->i_cost8x8direct[3] =
            a->l1.i_cost16x8   =
            a->l1.i_cost8x16   =
            a->i_rd16x16bi     =
            a->i_rd16x16direct =
            a->i_rd8x8bi       =
            a->i_rd16x8bi      =
            a->i_rd8x16bi      =
            a->i_cost16x16bi   =
            a->i_cost16x16direct =
            a->i_cost8x8bi     =
            a->i_cost16x8bi    =
            a->i_cost8x16bi    = COST_MAX;
        }
        else if( h->param.analyse.inter & X264_ANALYSE_PSUB8x8 )
            for( int i = 0; i < 4; i++ )
            {
                a->l0.i_cost4x4[i] =
                a->l0.i_cost8x4[i] =
                a->l0.i_cost4x8[i] = COST_MAX;
            }

        /* Fast intra decision */
        if( a->b_early_terminate && h->mb.i_mb_xy - h->sh.i_first_mb > 4 )
        {
            if( IS_INTRA( h->mb.i_mb_type_left[0] ) ||
                IS_INTRA( h->mb.i_mb_type_top ) ||
                IS_INTRA( h->mb.i_mb_type_topleft ) ||
                IS_INTRA( h->mb.i_mb_type_topright ) ||
                (h->sh.i_type == SLICE_TYPE_P && IS_INTRA( h->fref[0][0]->mb_type[h->mb.i_mb_xy] )) ||
                (h->mb.i_mb_xy - h->sh.i_first_mb < 3*(h->stat.frame.i_mb_count[I_4x4] + h->stat.frame.i_mb_count[I_8x8] + h->stat.frame.i_mb_count[I_16x16] + h->stat.frame.i_mb_count[I_PCM])) )
            { /* intra is likely */ }
            else
            {
                a->b_fast_intra = 1;
            }
        }
        h->mb.b_skip_mc = 0;
        if( h->param.b_intra_refresh && h->sh.i_type == SLICE_TYPE_P &&
            h->mb.i_mb_x >= h->fdec->i_pir_start_col && h->mb.i_mb_x <= h->fdec->i_pir_end_col )
        {
            a->b_force_intra = 1;
            a->b_fast_intra = 0;
            a->b_avoid_topright = h->mb.i_mb_x == h->fdec->i_pir_end_col;
        }
        else
            a->b_force_intra = 0;
    }
}

/* Prediction modes allowed for various combinations of neighbors. */
/* Terminated by a -1. */
/* In order, no neighbors, left, top, top/left, top/left/topleft */
static const int8_t i16x16_mode_available[5][5] =
{
    {I_PRED_16x16_DC_128, -1, -1, -1, -1},
    {I_PRED_16x16_DC_LEFT, I_PRED_16x16_H, -1, -1, -1},
    {I_PRED_16x16_DC_TOP, I_PRED_16x16_V, -1, -1, -1},
    {I_PRED_16x16_V, I_PRED_16x16_H, I_PRED_16x16_DC, -1, -1},
    {I_PRED_16x16_V, I_PRED_16x16_H, I_PRED_16x16_DC, I_PRED_16x16_P, -1},
};

static const int8_t chroma_mode_available[5][5] =
{
    {I_PRED_CHROMA_DC_128, -1, -1, -1, -1},
    {I_PRED_CHROMA_DC_LEFT, I_PRED_CHROMA_H, -1, -1, -1},
    {I_PRED_CHROMA_DC_TOP, I_PRED_CHROMA_V, -1, -1, -1},
    {I_PRED_CHROMA_V, I_PRED_CHROMA_H, I_PRED_CHROMA_DC, -1, -1},
    {I_PRED_CHROMA_V, I_PRED_CHROMA_H, I_PRED_CHROMA_DC, I_PRED_CHROMA_P, -1},
};

static const int8_t i8x8_mode_available[2][5][10] =
{
    {
        {I_PRED_4x4_DC_128, -1, -1, -1, -1, -1, -1, -1, -1, -1},
        {I_PRED_4x4_DC_LEFT, I_PRED_4x4_H, I_PRED_4x4_HU, -1, -1, -1, -1, -1, -1, -1},
        {I_PRED_4x4_DC_TOP, I_PRED_4x4_V, I_PRED_4x4_DDL, I_PRED_4x4_VL, -1, -1, -1, -1, -1, -1},
        {I_PRED_4x4_DC, I_PRED_4x4_H, I_PRED_4x4_V, I_PRED_4x4_DDL, I_PRED_4x4_VL, I_PRED_4x4_HU, -1, -1, -1, -1},
        {I_PRED_4x4_DC, I_PRED_4x4_H, I_PRED_4x4_V, I_PRED_4x4_DDL, I_PRED_4x4_DDR, I_PRED_4x4_VR, I_PRED_4x4_HD, I_PRED_4x4_VL, I_PRED_4x4_HU, -1},
    },
    {
        {I_PRED_4x4_DC_128, -1, -1, -1, -1, -1, -1, -1, -1, -1},
        {I_PRED_4x4_DC_LEFT, I_PRED_4x4_H, I_PRED_4x4_HU, -1, -1, -1, -1, -1, -1, -1},
        {-1, -1, -1, -1, -1, -1, -1, -1, -1, -1},
        {I_PRED_4x4_H, I_PRED_4x4_HU, -1, -1, -1, -1, -1, -1, -1, -1},
        {I_PRED_4x4_H, I_PRED_4x4_HD, I_PRED_4x4_HU, -1, -1, -1, -1, -1, -1, -1},
    }
};

static const int8_t i4x4_mode_available[2][5][10] =
{
    {
        {I_PRED_4x4_DC_128, -1, -1, -1, -1, -1, -1, -1, -1, -1},
        {I_PRED_4x4_DC_LEFT, I_PRED_4x4_H, I_PRED_4x4_HU, -1, -1, -1, -1, -1, -1, -1},
        {I_PRED_4x4_DC_TOP, I_PRED_4x4_V, I_PRED_4x4_DDL, I_PRED_4x4_VL, -1, -1, -1, -1, -1, -1},
        {I_PRED_4x4_DC, I_PRED_4x4_H, I_PRED_4x4_V, I_PRED_4x4_DDL, I_PRED_4x4_VL, I_PRED_4x4_HU, -1, -1, -1, -1},
        {I_PRED_4x4_DC, I_PRED_4x4_H, I_PRED_4x4_V, I_PRED_4x4_DDL, I_PRED_4x4_DDR, I_PRED_4x4_VR, I_PRED_4x4_HD, I_PRED_4x4_VL, I_PRED_4x4_HU, -1},
    },
    {
        {I_PRED_4x4_DC_128, -1, -1, -1, -1, -1, -1, -1, -1, -1},
        {I_PRED_4x4_DC_LEFT, I_PRED_4x4_H, I_PRED_4x4_HU, -1, -1, -1, -1, -1, -1, -1},
        {I_PRED_4x4_DC_TOP, I_PRED_4x4_V, -1, -1, -1, -1, -1, -1, -1, -1},
        {I_PRED_4x4_DC, I_PRED_4x4_H, I_PRED_4x4_V, I_PRED_4x4_HU, -1, -1, -1, -1, -1, -1},
        {I_PRED_4x4_DC, I_PRED_4x4_H, I_PRED_4x4_V, I_PRED_4x4_DDR, I_PRED_4x4_VR, I_PRED_4x4_HD, I_PRED_4x4_HU, -1, -1, -1},
    }
};

static ALWAYS_INLINE const int8_t *predict_16x16_mode_available( int i_neighbour )
{
    int idx = i_neighbour & (MB_TOP|MB_LEFT|MB_TOPLEFT);
    idx = (idx == (MB_TOP|MB_LEFT|MB_TOPLEFT)) ? 4 : idx & (MB_TOP|MB_LEFT);
    return i16x16_mode_available[idx];
}

static ALWAYS_INLINE const int8_t *predict_chroma_mode_available( int i_neighbour )
{
    int idx = i_neighbour & (MB_TOP|MB_LEFT|MB_TOPLEFT);
    idx = (idx == (MB_TOP|MB_LEFT|MB_TOPLEFT)) ? 4 : idx & (MB_TOP|MB_LEFT);
    return chroma_mode_available[idx];
}

static ALWAYS_INLINE const int8_t *predict_8x8_mode_available( int force_intra, int i_neighbour, int i )
{
    int avoid_topright = force_intra && (i&1);
    int idx = i_neighbour & (MB_TOP|MB_LEFT|MB_TOPLEFT);
    idx = (idx == (MB_TOP|MB_LEFT|MB_TOPLEFT)) ? 4 : idx & (MB_TOP|MB_LEFT);
    return i8x8_mode_available[avoid_topright][idx];
}

static ALWAYS_INLINE const int8_t *predict_4x4_mode_available( int force_intra, int i_neighbour, int i )
{
    int avoid_topright = force_intra && ((i&5) == 5);
    int idx = i_neighbour & (MB_TOP|MB_LEFT|MB_TOPLEFT);
    idx = (idx == (MB_TOP|MB_LEFT|MB_TOPLEFT)) ? 4 : idx & (MB_TOP|MB_LEFT);
    return i4x4_mode_available[avoid_topright][idx];
}

/* For trellis=2, we need to do this for both sizes of DCT, for trellis=1 we only need to use it on the chosen mode. */
static inline void psy_trellis_init( x264_t *h, int do_both_dct )
{
    if( do_both_dct || h->mb.b_transform_8x8 )
        h->dctf.sub16x16_dct8( h->mb.pic.fenc_dct8, h->mb.pic.p_fenc[0], (pixel*)x264_zero );
    if( do_both_dct || !h->mb.b_transform_8x8 )
        h->dctf.sub16x16_dct( h->mb.pic.fenc_dct4, h->mb.pic.p_fenc[0], (pixel*)x264_zero );
}

/* Reset fenc satd scores cache for psy RD */
static inline void mb_init_fenc_cache( x264_t *h, int b_satd )
{
    if( h->param.analyse.i_trellis == 2 && h->mb.i_psy_trellis )
        psy_trellis_init( h, h->param.analyse.b_transform_8x8 );
    if( !h->mb.i_psy_rd )
        return;

    M128( &h->mb.pic.fenc_hadamard_cache[0] ) = M128_ZERO;
    M128( &h->mb.pic.fenc_hadamard_cache[2] ) = M128_ZERO;
    M128( &h->mb.pic.fenc_hadamard_cache[4] ) = M128_ZERO;
    M128( &h->mb.pic.fenc_hadamard_cache[6] ) = M128_ZERO;
    h->mb.pic.fenc_hadamard_cache[8] = 0;
    if( b_satd )
        h->mc.memzero_aligned( h->mb.pic.fenc_satd_cache, sizeof(h->mb.pic.fenc_satd_cache) );
}

static void mb_analyse_intra_chroma( x264_t *h, x264_mb_analysis_t *a )
{
    if( a->i_satd_chroma < COST_MAX )
        return;

    if( CHROMA444 )
    {
        if( !h->mb.b_chroma_me )
        {
            a->i_satd_chroma = 0;
            return;
        }

        /* Cheap approximation of chroma costs to avoid a full i4x4/i8x8 analysis. */
        if( h->mb.b_lossless )
        {
            x264_predict_lossless_16x16( h, 1, a->i_predict16x16 );
            x264_predict_lossless_16x16( h, 2, a->i_predict16x16 );
        }
        else
        {
            h->predict_16x16[a->i_predict16x16]( h->mb.pic.p_fdec[1] );
            h->predict_16x16[a->i_predict16x16]( h->mb.pic.p_fdec[2] );
        }
        a->i_satd_chroma = h->pixf.mbcmp[PIXEL_16x16]( h->mb.pic.p_fenc[1], FENC_STRIDE, h->mb.pic.p_fdec[1], FDEC_STRIDE )
                         + h->pixf.mbcmp[PIXEL_16x16]( h->mb.pic.p_fenc[2], FENC_STRIDE, h->mb.pic.p_fdec[2], FDEC_STRIDE );
        return;
    }

    const int8_t *predict_mode = predict_chroma_mode_available( h->mb.i_neighbour_intra );
    int chromapix = h->luma2chroma_pixel[PIXEL_16x16];

    /* Prediction selection for chroma */
    if( predict_mode[3] >= 0 && !h->mb.b_lossless )
    {
        int satdu[4], satdv[4];
        h->pixf.intra_mbcmp_x3_chroma( h->mb.pic.p_fenc[1], h->mb.pic.p_fdec[1], satdu );
        h->pixf.intra_mbcmp_x3_chroma( h->mb.pic.p_fenc[2], h->mb.pic.p_fdec[2], satdv );
        h->predict_chroma[I_PRED_CHROMA_P]( h->mb.pic.p_fdec[1] );
        h->predict_chroma[I_PRED_CHROMA_P]( h->mb.pic.p_fdec[2] );
        satdu[I_PRED_CHROMA_P] = h->pixf.mbcmp[chromapix]( h->mb.pic.p_fenc[1], FENC_STRIDE, h->mb.pic.p_fdec[1], FDEC_STRIDE );
        satdv[I_PRED_CHROMA_P] = h->pixf.mbcmp[chromapix]( h->mb.pic.p_fenc[2], FENC_STRIDE, h->mb.pic.p_fdec[2], FDEC_STRIDE );

        for( ; *predict_mode >= 0; predict_mode++ )
        {
            int i_mode = *predict_mode;
            int i_satd = satdu[i_mode] + satdv[i_mode] + a->i_lambda * bs_size_ue( i_mode );

            a->i_satd_chroma_dir[i_mode] = i_satd;
            COPY2_IF_LT( a->i_satd_chroma, i_satd, a->i_predict8x8chroma, i_mode );
        }
    }
    else
    {
        for( ; *predict_mode >= 0; predict_mode++ )
        {
            int i_satd;
            int i_mode = *predict_mode;

            /* we do the prediction */
            if( h->mb.b_lossless )
                x264_predict_lossless_chroma( h, i_mode );
            else
            {
                h->predict_chroma[i_mode]( h->mb.pic.p_fdec[1] );
                h->predict_chroma[i_mode]( h->mb.pic.p_fdec[2] );
            }

            /* we calculate the cost */
            i_satd = h->pixf.mbcmp[chromapix]( h->mb.pic.p_fenc[1], FENC_STRIDE, h->mb.pic.p_fdec[1], FDEC_STRIDE ) +
                     h->pixf.mbcmp[chromapix]( h->mb.pic.p_fenc[2], FENC_STRIDE, h->mb.pic.p_fdec[2], FDEC_STRIDE ) +
                     a->i_lambda * bs_size_ue( x264_mb_chroma_pred_mode_fix[i_mode] );

            a->i_satd_chroma_dir[i_mode] = i_satd;
            COPY2_IF_LT( a->i_satd_chroma, i_satd, a->i_predict8x8chroma, i_mode );
        }
    }

    h->mb.i_chroma_pred_mode = a->i_predict8x8chroma;
}

/* FIXME: should we do any sort of merged chroma analysis with 4:4:4? */
static void mb_analyse_intra( x264_t *h, x264_mb_analysis_t *a, int i_satd_inter )
{
    const unsigned int flags = h->sh.i_type == SLICE_TYPE_I ? h->param.analyse.intra : h->param.analyse.inter;
    pixel *p_src = h->mb.pic.p_fenc[0];
    pixel *p_dst = h->mb.pic.p_fdec[0];
    static const int8_t intra_analysis_shortcut[2][2][2][5] =
    {
        {{{I_PRED_4x4_HU, -1, -1, -1, -1},
          {I_PRED_4x4_DDL, I_PRED_4x4_VL, -1, -1, -1}},
         {{I_PRED_4x4_DDR, I_PRED_4x4_HD, I_PRED_4x4_HU, -1, -1},
          {I_PRED_4x4_DDL, I_PRED_4x4_DDR, I_PRED_4x4_VR, I_PRED_4x4_VL, -1}}},
        {{{I_PRED_4x4_HU, -1, -1, -1, -1},
          {-1, -1, -1, -1, -1}},
         {{I_PRED_4x4_DDR, I_PRED_4x4_HD, I_PRED_4x4_HU, -1, -1},
          {I_PRED_4x4_DDR, I_PRED_4x4_VR, -1, -1, -1}}},
    };

    int idx;
    int lambda = a->i_lambda;

    /*---------------- Try all mode and calculate their score ---------------*/
    /* Disabled i16x16 for AVC-Intra compat */
    /* Mobiclip cannot represent I_16x16 in its bitstream (see the forced
     * I_4x4 type decision below), and always sets b_early_terminate=0, which
     * makes the I_4x4 search's own threshold unconditionally COST_MAX
     * (mb_analyse_init: i_satd_thresh = b_early_terminate ? MIN3(...) :
     * COST_MAX) -- i.e. provably independent of i_satd_i16x16's value.
     * i_satd_i16x16 is also never read by mobiclip's type-selection
     * (COPY2_IF_LT compares i_satd_i4x4 only) and is already initialized to
     * COST_MAX by mb_analyse_init, which is exactly what skipping this block
     * leaves it at. Skipping the I_16x16 SATD search here is therefore
     * provably a no-op for every downstream mobiclip read -- not merely an
     * assumption -- while avoiding real, wasted SATD comparisons that are
     * unconditionally computed but never used for mobiclip's decision. */
    if( !h->param.i_avcintra_class && !h->param.i_mobiclip )
    {
        const int8_t *predict_mode = predict_16x16_mode_available( h->mb.i_neighbour_intra );

        /* Not heavily tuned */
        static const uint8_t i16x16_thresh_lut[11] = { 2, 2, 2, 3, 3, 4, 4, 4, 4, 4, 4 };
        int i16x16_thresh = a->b_fast_intra ? (i16x16_thresh_lut[h->mb.i_subpel_refine]*i_satd_inter)>>1 : COST_MAX;

        if( !h->mb.b_lossless && predict_mode[3] >= 0 )
        {
            h->pixf.intra_mbcmp_x3_16x16( p_src, p_dst, a->i_satd_i16x16_dir );
            a->i_satd_i16x16_dir[0] += lambda * bs_size_ue(0);
            a->i_satd_i16x16_dir[1] += lambda * bs_size_ue(1);
            a->i_satd_i16x16_dir[2] += lambda * bs_size_ue(2);
            COPY2_IF_LT( a->i_satd_i16x16, a->i_satd_i16x16_dir[0], a->i_predict16x16, 0 );
            COPY2_IF_LT( a->i_satd_i16x16, a->i_satd_i16x16_dir[1], a->i_predict16x16, 1 );
            COPY2_IF_LT( a->i_satd_i16x16, a->i_satd_i16x16_dir[2], a->i_predict16x16, 2 );

            /* Plane is expensive, so don't check it unless one of the previous modes was useful. */
            if( a->i_satd_i16x16 <= i16x16_thresh )
            {
                h->predict_16x16[I_PRED_16x16_P]( p_dst );
                a->i_satd_i16x16_dir[I_PRED_16x16_P] = h->pixf.mbcmp[PIXEL_16x16]( p_src, FENC_STRIDE, p_dst, FDEC_STRIDE );
                a->i_satd_i16x16_dir[I_PRED_16x16_P] += lambda * bs_size_ue(3);
                COPY2_IF_LT( a->i_satd_i16x16, a->i_satd_i16x16_dir[I_PRED_16x16_P], a->i_predict16x16, 3 );
            }
        }
        else
        {
            for( ; *predict_mode >= 0; predict_mode++ )
            {
                int i_satd;
                int i_mode = *predict_mode;

                if( h->mb.b_lossless )
                    x264_predict_lossless_16x16( h, 0, i_mode );
                else
                    h->predict_16x16[i_mode]( p_dst );

                i_satd = h->pixf.mbcmp[PIXEL_16x16]( p_src, FENC_STRIDE, p_dst, FDEC_STRIDE ) +
                         lambda * bs_size_ue( x264_mb_pred_mode16x16_fix[i_mode] );
                COPY2_IF_LT( a->i_satd_i16x16, i_satd, a->i_predict16x16, i_mode );
                a->i_satd_i16x16_dir[i_mode] = i_satd;
            }
        }

        if( h->sh.i_type == SLICE_TYPE_B )
            /* cavlc mb type prefix */
            a->i_satd_i16x16 += lambda * i_mb_b_cost_table[I_16x16];

        if( a->i_satd_i16x16 > i16x16_thresh )
            return;
    }

    uint16_t *cost_i4x4_mode = h->cost_table->i4x4_mode[a->i_qp] + 8;
    /* 8x8 prediction selection */
    if( flags & X264_ANALYSE_I8x8 )
    {
        ALIGNED_ARRAY_32( pixel, edge,[36] );
        x264_pixel_cmp_t sa8d = (h->pixf.mbcmp[0] == h->pixf.satd[0]) ? h->pixf.sa8d[PIXEL_8x8] : h->pixf.mbcmp[PIXEL_8x8];
        int i_satd_thresh = a->i_mbrd ? COST_MAX : X264_MIN( i_satd_inter, a->i_satd_i16x16 );

        // FIXME some bias like in i4x4?
        int i_cost = lambda * 4; /* base predmode costs */
        h->mb.i_cbp_luma = 0;

        if( h->sh.i_type == SLICE_TYPE_B )
            i_cost += lambda * i_mb_b_cost_table[I_8x8];

        for( idx = 0;; idx++ )
        {
            int x = idx&1;
            int y = idx>>1;
            pixel *p_src_by = p_src + 8*x + 8*y*FENC_STRIDE;
            pixel *p_dst_by = p_dst + 8*x + 8*y*FDEC_STRIDE;
            int i_best = COST_MAX;
            int i_pred_mode = x264_mb_predict_intra4x4_mode( h, 4*idx );

            const int8_t *predict_mode = predict_8x8_mode_available( a->b_avoid_topright, h->mb.i_neighbour8[idx], idx );
            h->predict_8x8_filter( p_dst_by, edge, h->mb.i_neighbour8[idx], ALL_NEIGHBORS );

            if( h->pixf.intra_mbcmp_x9_8x8 && predict_mode[8] >= 0 )
            {
                /* No shortcuts here. The SSSE3 implementation of intra_mbcmp_x9 is fast enough. */
                i_best = h->pixf.intra_mbcmp_x9_8x8( p_src_by, p_dst_by, edge, cost_i4x4_mode-i_pred_mode, a->i_satd_i8x8_dir[idx] );
                i_cost += i_best & 0xffff;
                i_best >>= 16;
                a->i_predict8x8[idx] = i_best;
                if( idx == 3 || i_cost > i_satd_thresh )
                    break;
                x264_macroblock_cache_intra8x8_pred( h, 2*x, 2*y, i_best );
            }
            else
            {
                if( !h->mb.b_lossless && predict_mode[5] >= 0 )
                {
                    ALIGNED_ARRAY_16( int32_t, satd,[4] );
                    h->pixf.intra_mbcmp_x3_8x8( p_src_by, edge, satd );
                    int favor_vertical = satd[I_PRED_4x4_H] > satd[I_PRED_4x4_V];
                    if( i_pred_mode < 3 )
                        satd[i_pred_mode] -= 3 * lambda;
                    for( int i = 2; i >= 0; i-- )
                    {
                        int cost = satd[i];
                        a->i_satd_i8x8_dir[idx][i] = cost + 4 * lambda;
                        COPY2_IF_LT( i_best, cost, a->i_predict8x8[idx], i );
                    }

                    /* Take analysis shortcuts: don't analyse modes that are too
                     * far away direction-wise from the favored mode. */
                    if( a->i_mbrd < 1 + a->b_fast_intra )
                        predict_mode = intra_analysis_shortcut[a->b_avoid_topright][predict_mode[8] >= 0][favor_vertical];
                    else
                        predict_mode += 3;
                }

                for( ; *predict_mode >= 0 && (i_best >= 0 || a->i_mbrd >= 2); predict_mode++ )
                {
                    int i_satd;
                    int i_mode = *predict_mode;

                    if( h->mb.b_lossless )
                        x264_predict_lossless_8x8( h, p_dst_by, 0, idx, i_mode, edge );
                    else
                        h->predict_8x8[i_mode]( p_dst_by, edge );

                    i_satd = sa8d( p_dst_by, FDEC_STRIDE, p_src_by, FENC_STRIDE );
                    if( i_pred_mode == x264_mb_pred_mode4x4_fix(i_mode) )
                        i_satd -= 3 * lambda;

                    COPY2_IF_LT( i_best, i_satd, a->i_predict8x8[idx], i_mode );
                    a->i_satd_i8x8_dir[idx][i_mode] = i_satd + 4 * lambda;
                }
                i_cost += i_best + 3*lambda;

                if( idx == 3 || i_cost > i_satd_thresh )
                    break;
                if( h->mb.b_lossless )
                    x264_predict_lossless_8x8( h, p_dst_by, 0, idx, a->i_predict8x8[idx], edge );
                else
                    h->predict_8x8[a->i_predict8x8[idx]]( p_dst_by, edge );
                x264_macroblock_cache_intra8x8_pred( h, 2*x, 2*y, a->i_predict8x8[idx] );
            }
            /* we need to encode this block now (for next ones) */
            x264_mb_encode_i8x8( h, 0, idx, a->i_qp, a->i_predict8x8[idx], edge, 0 );
        }

        if( idx == 3 )
        {
            a->i_satd_i8x8 = i_cost;
            if( h->mb.i_skip_intra )
            {
                h->mc.copy[PIXEL_16x16]( h->mb.pic.i8x8_fdec_buf, 16, p_dst, FDEC_STRIDE, 16 );
                h->mb.pic.i8x8_nnz_buf[0] = M32( &h->mb.cache.non_zero_count[x264_scan8[ 0]] );
                h->mb.pic.i8x8_nnz_buf[1] = M32( &h->mb.cache.non_zero_count[x264_scan8[ 2]] );
                h->mb.pic.i8x8_nnz_buf[2] = M32( &h->mb.cache.non_zero_count[x264_scan8[ 8]] );
                h->mb.pic.i8x8_nnz_buf[3] = M32( &h->mb.cache.non_zero_count[x264_scan8[10]] );
                h->mb.pic.i8x8_cbp = h->mb.i_cbp_luma;
                if( h->mb.i_skip_intra == 2 )
                    h->mc.memcpy_aligned( h->mb.pic.i8x8_dct_buf, h->dct.luma8x8, sizeof(h->mb.pic.i8x8_dct_buf) );
            }
        }
        else
        {
            static const uint16_t cost_div_fix8[3] = {1024,512,341};
            a->i_satd_i8x8 = COST_MAX;
            i_cost = (i_cost * cost_div_fix8[idx]) >> 8;
        }
        /* Not heavily tuned */
        static const uint8_t i8x8_thresh[11] = { 4, 4, 4, 5, 5, 5, 6, 6, 6, 6, 6 };
        if( a->b_early_terminate && X264_MIN(i_cost, a->i_satd_i16x16) > (i_satd_inter*i8x8_thresh[h->mb.i_subpel_refine])>>2 )
            return;
    }

    /* 4x4 prediction selection */
    if( flags & X264_ANALYSE_I4x4 )
    {
        int i_cost = lambda * (24+16); /* 24from JVT (SATD0), 16 from base predmode costs */
        int i_satd_thresh = a->b_early_terminate ? X264_MIN3( i_satd_inter, a->i_satd_i16x16, a->i_satd_i8x8 ) : COST_MAX;
        h->mb.i_cbp_luma = 0;

        if( a->b_early_terminate && a->i_mbrd )
            i_satd_thresh = i_satd_thresh * (10-a->b_fast_intra)/8;

        if( h->sh.i_type == SLICE_TYPE_B )
            i_cost += lambda * i_mb_b_cost_table[I_4x4];

        for( idx = 0;; idx++ )
        {
            pixel *p_src_by = p_src + block_idx_xy_fenc[idx];
            pixel *p_dst_by = p_dst + block_idx_xy_fdec[idx];
            int i_best = COST_MAX;
            int i_pred_mode = x264_mb_predict_intra4x4_mode( h, idx );

            const int8_t *predict_mode = predict_4x4_mode_available( a->b_avoid_topright, h->mb.i_neighbour4[idx], idx );

            if( (h->mb.i_neighbour4[idx] & (MB_TOPRIGHT|MB_TOP)) == MB_TOP )
                /* emulate missing topright samples */
                MPIXEL_X4( &p_dst_by[4 - FDEC_STRIDE] ) = PIXEL_SPLAT_X4( p_dst_by[3 - FDEC_STRIDE] );

            if( h->pixf.intra_mbcmp_x9_4x4 && predict_mode[8] >= 0 )
            {
                /* No shortcuts here. The SSSE3 implementation of intra_mbcmp_x9 is fast enough. */
                i_best = h->pixf.intra_mbcmp_x9_4x4( p_src_by, p_dst_by, cost_i4x4_mode-i_pred_mode );
                i_cost += i_best & 0xffff;
                i_best >>= 16;
                a->i_predict4x4[idx] = i_best;
                if( i_cost > i_satd_thresh || idx == 15 )
                    break;
                h->mb.cache.intra4x4_pred_mode[x264_scan8[idx]] = i_best;
            }
            else
            {
                if( !h->mb.b_lossless && predict_mode[5] >= 0 )
                {
                    ALIGNED_ARRAY_16( int32_t, satd,[4] );
                    h->pixf.intra_mbcmp_x3_4x4( p_src_by, p_dst_by, satd );
                    int favor_vertical = satd[I_PRED_4x4_H] > satd[I_PRED_4x4_V];
                    if( i_pred_mode < 3 )
                        satd[i_pred_mode] -= 3 * lambda;
                    i_best = satd[I_PRED_4x4_DC]; a->i_predict4x4[idx] = I_PRED_4x4_DC;
                    COPY2_IF_LT( i_best, satd[I_PRED_4x4_H], a->i_predict4x4[idx], I_PRED_4x4_H );
                    COPY2_IF_LT( i_best, satd[I_PRED_4x4_V], a->i_predict4x4[idx], I_PRED_4x4_V );

                    /* Take analysis shortcuts: don't analyse modes that are too
                     * far away direction-wise from the favored mode. */
                    if( a->i_mbrd < 1 + a->b_fast_intra )
                        predict_mode = intra_analysis_shortcut[a->b_avoid_topright][predict_mode[8] >= 0][favor_vertical];
                    else
                        predict_mode += 3;
                }

                if( i_best > 0 )
                {
                    for( ; *predict_mode >= 0; predict_mode++ )
                    {
                        int i_satd;
                        int i_mode = *predict_mode;

                        if( h->mb.b_lossless )
                            x264_predict_lossless_4x4( h, p_dst_by, 0, idx, i_mode );
                        else
                            h->predict_4x4[i_mode]( p_dst_by );

                        i_satd = h->pixf.mbcmp[PIXEL_4x4]( p_src_by, FENC_STRIDE, p_dst_by, FDEC_STRIDE );
                        if( i_pred_mode == x264_mb_pred_mode4x4_fix(i_mode) )
                        {
                            i_satd -= lambda * 3;
                            if( i_satd <= 0 )
                            {
                                i_best = i_satd;
                                a->i_predict4x4[idx] = i_mode;
                                break;
                            }
                        }

                        COPY2_IF_LT( i_best, i_satd, a->i_predict4x4[idx], i_mode );
                    }
                }

                i_cost += i_best + 3 * lambda;
                if( i_cost > i_satd_thresh || idx == 15 )
                    break;
                if( h->mb.b_lossless )
                    x264_predict_lossless_4x4( h, p_dst_by, 0, idx, a->i_predict4x4[idx] );
                else
                    h->predict_4x4[a->i_predict4x4[idx]]( p_dst_by );
                h->mb.cache.intra4x4_pred_mode[x264_scan8[idx]] = a->i_predict4x4[idx];
            }
            /* we need to encode this block now (for next ones) */
            x264_mb_encode_i4x4( h, 0, idx, a->i_qp, a->i_predict4x4[idx], 0 );
        }
        if( idx == 15 )
        {
            a->i_satd_i4x4 = i_cost;
            if( h->mb.i_skip_intra )
            {
                h->mc.copy[PIXEL_16x16]( h->mb.pic.i4x4_fdec_buf, 16, p_dst, FDEC_STRIDE, 16 );
                h->mb.pic.i4x4_nnz_buf[0] = M32( &h->mb.cache.non_zero_count[x264_scan8[ 0]] );
                h->mb.pic.i4x4_nnz_buf[1] = M32( &h->mb.cache.non_zero_count[x264_scan8[ 2]] );
                h->mb.pic.i4x4_nnz_buf[2] = M32( &h->mb.cache.non_zero_count[x264_scan8[ 8]] );
                h->mb.pic.i4x4_nnz_buf[3] = M32( &h->mb.cache.non_zero_count[x264_scan8[10]] );
                h->mb.pic.i4x4_cbp = h->mb.i_cbp_luma;
                if( h->mb.i_skip_intra == 2 )
                    h->mc.memcpy_aligned( h->mb.pic.i4x4_dct_buf, h->dct.luma4x4, sizeof(h->mb.pic.i4x4_dct_buf) );
            }
        }
        else
            a->i_satd_i4x4 = COST_MAX;
    }
}

static void intra_rd( x264_t *h, x264_mb_analysis_t *a, int i_satd_thresh )
{
    if( !a->b_early_terminate )
        i_satd_thresh = COST_MAX;

    if( a->i_satd_i16x16 < i_satd_thresh )
    {
        h->mb.i_type = I_16x16;
        analyse_update_cache( h, a );
        a->i_satd_i16x16 = rd_cost_mb( h, a->i_lambda2 );
    }
    else
        a->i_satd_i16x16 = COST_MAX;

    if( a->i_satd_i4x4 < i_satd_thresh )
    {
        h->mb.i_type = I_4x4;
        analyse_update_cache( h, a );
        a->i_satd_i4x4 = rd_cost_mb( h, a->i_lambda2 );
    }
    else
        a->i_satd_i4x4 = COST_MAX;

    if( a->i_satd_i8x8 < i_satd_thresh )
    {
        h->mb.i_type = I_8x8;
        analyse_update_cache( h, a );
        a->i_satd_i8x8 = rd_cost_mb( h, a->i_lambda2 );
        a->i_cbp_i8x8_luma = h->mb.i_cbp_luma;
    }
    else
        a->i_satd_i8x8 = COST_MAX;
}

static void intra_rd_refine( x264_t *h, x264_mb_analysis_t *a )
{
    uint64_t i_satd, i_best;
    int plane_count = CHROMA444 ? 3 : 1;
    h->mb.i_skip_intra = 0;

    /* Experimental quality/speed tradeoff. The original subme9 behavior
     * evaluates every available I4x4 direction. A positive cap evaluates the
     * SATD-chosen direction first, then up to cap-1 other legal directions.
     * Default 0 changes no candidate ordering or bitstream. */
    static int mobi_intra_rd_cap = -1;
    static int mobi_intra_rd_policy = -1;
    if( mobi_intra_rd_cap < 0 )
    {
        const char *opt = getenv( "MOBI_INTRA_RD_CAP" );
        mobi_intra_rd_cap = opt ? atoi( opt ) : 0;
        mobi_intra_rd_cap = X264_MAX( 0, X264_MIN( mobi_intra_rd_cap, 9 ) );
    }
    int mobi_rd_cap = h->param.i_mobiclip ? mobi_intra_rd_cap : 0;
    if( mobi_intra_rd_policy < 0 )
    {
        const char *opt = getenv( "MOBI_INTRA_RD_POLICY" );
        mobi_intra_rd_policy = opt ? X264_MAX( 0, X264_MIN( atoi( opt ), 2 ) ) : 0;
    }

    if( h->mb.i_type == I_16x16 )
    {
        int old_pred_mode = a->i_predict16x16;
        const int8_t *predict_mode = predict_16x16_mode_available( h->mb.i_neighbour_intra );
        int i_thresh = a->b_early_terminate ? a->i_satd_i16x16_dir[old_pred_mode] * 9/8 : COST_MAX;
        i_best = a->i_satd_i16x16;
        for( ; *predict_mode >= 0; predict_mode++ )
        {
            int i_mode = *predict_mode;
            if( i_mode == old_pred_mode || a->i_satd_i16x16_dir[i_mode] > i_thresh )
                continue;
            h->mb.i_intra16x16_pred_mode = i_mode;
            i_satd = rd_cost_mb( h, a->i_lambda2 );
            COPY2_IF_LT( i_best, i_satd, a->i_predict16x16, i_mode );
        }
    }

    /* RD selection for chroma prediction */
    if( CHROMA_FORMAT == CHROMA_420 || CHROMA_FORMAT == CHROMA_422 )
    {
        const int8_t *predict_mode = predict_chroma_mode_available( h->mb.i_neighbour_intra );
        if( predict_mode[1] >= 0 )
        {
            int8_t predict_mode_sorted[4];
            int i_max;
            int i_thresh = a->b_early_terminate ? a->i_satd_chroma * 5/4 : COST_MAX;

            for( i_max = 0; *predict_mode >= 0; predict_mode++ )
            {
                int i_mode = *predict_mode;
                if( a->i_satd_chroma_dir[i_mode] < i_thresh && i_mode != a->i_predict8x8chroma )
                    predict_mode_sorted[i_max++] = i_mode;
            }

            if( i_max > 0 )
            {
                int i_cbp_chroma_best = h->mb.i_cbp_chroma;
                int i_chroma_lambda = x264_lambda2_tab[h->mb.i_chroma_qp];
                /* the previous thing encoded was intra_rd(), so the pixels and
                 * coefs for the current chroma mode are still around, so we only
                 * have to recount the bits. */
                i_best = rd_cost_chroma( h, i_chroma_lambda, a->i_predict8x8chroma, 0 );
                for( int i = 0; i < i_max; i++ )
                {
                    int i_mode = predict_mode_sorted[i];
                    if( h->mb.b_lossless )
                        x264_predict_lossless_chroma( h, i_mode );
                    else
                    {
                        h->predict_chroma[i_mode]( h->mb.pic.p_fdec[1] );
                        h->predict_chroma[i_mode]( h->mb.pic.p_fdec[2] );
                    }
                    /* if we've already found a mode that needs no residual, then
                     * probably any mode with a residual will be worse.
                     * so avoid dct on the remaining modes to improve speed. */
                    i_satd = rd_cost_chroma( h, i_chroma_lambda, i_mode, h->mb.i_cbp_chroma != 0x00 );
                    COPY3_IF_LT( i_best, i_satd, a->i_predict8x8chroma, i_mode, i_cbp_chroma_best, h->mb.i_cbp_chroma );
                }
                h->mb.i_chroma_pred_mode = a->i_predict8x8chroma;
                h->mb.i_cbp_chroma = i_cbp_chroma_best;
            }
        }
    }

    if( h->mb.i_type == I_4x4 )
    {
        pixel4 pels[3][4] = {{0}}; // doesn't need initting, just shuts up a gcc warning
        int nnz[3] = {0};
        for( int idx = 0; idx < 16; idx++ )
        {
            pixel *dst[3] = {h->mb.pic.p_fdec[0] + block_idx_xy_fdec[idx],
                             CHROMA_FORMAT ? h->mb.pic.p_fdec[1] + block_idx_xy_fdec[idx] : NULL,
                             CHROMA_FORMAT ? h->mb.pic.p_fdec[2] + block_idx_xy_fdec[idx] : NULL};
            i_best = COST_MAX64;

            const int8_t *predict_mode = predict_4x4_mode_available( a->b_avoid_topright, h->mb.i_neighbour4[idx], idx );
            if( (h->mb.i_neighbour4[idx] & (MB_TOPRIGHT|MB_TOP)) == MB_TOP )
                for( int p = 0; p < plane_count; p++ )
                    /* Emulate missing top-right before any SATD prediction. */
                    MPIXEL_X4( dst[p]+4-FDEC_STRIDE ) = PIXEL_SPLAT_X4( dst[p][3-FDEC_STRIDE] );
            int8_t mobi_limited_modes[10];
            if( mobi_rd_cap )
            {
                int n = 0;
                int satd_mode = a->i_predict4x4[idx];
#if !HIGH_BIT_DEPTH
                if( mobi_intra_rd_policy )
                {
                    /* Experimental Mobiclip-accurate SATD shortlisting.
                     * Unlike generic H264 predictors, this uses our exact
                     * on-device luma predictor for every legal mode. The
                     * shortlist is an explicit fidelity tradeoff. */
                    static const uint8_t h264_modes[13] =
                        { 2, 0, 1, 2, 2, 8, 6, 5, 4, 3, 2, 2, 2 };
                    int scores[10], modes[10], count = 0;
                    pixel *dst = h->mb.pic.p_fdec[0] + block_idx_xy_fdec[idx];
                    pixel *src = h->mb.pic.p_fenc[0] + block_idx_xy_fenc[idx];
                    for( const int8_t *p = predict_mode; *p >= 0; p++ )
                    {
                        int mode = *p;
                        int h264 = h264_modes[(unsigned)mode + 1 < 13 ? mode + 1 : 0];
                        mobi_predict_4x4( h, dst, idx, mobi_h264_to_mobiclip_mode[h264] );
                        scores[count] = mobi_intra_rd_policy == 1
                            ? h->pixf.mbcmp[PIXEL_4x4]( src, FENC_STRIDE, dst, FDEC_STRIDE )
                            : h->pixf.sad[PIXEL_4x4]( src, FENC_STRIDE, dst, FDEC_STRIDE );
                        modes[count++] = mode;
                    }
                    /* Insertion-sort at most nine directions, deterministic
                     * on ties. The RDO encoder is only run for the top cap. */
                    for( int i = 1; i < count; i++ )
                        for( int j = i; j > 0 && scores[j] < scores[j-1]; j-- )
                        {
                            int v = scores[j]; scores[j] = scores[j-1]; scores[j-1] = v;
                            v = modes[j]; modes[j] = modes[j-1]; modes[j-1] = v;
                        }
                    for( int i = 0; i < count && i < mobi_rd_cap; i++ )
                        mobi_limited_modes[n++] = modes[i];
                }
                else
#endif
                {
                    /* Cheap shortlist: SATD's original winner plus legal
                     * candidates in their original enumeration order. */
                    for( const int8_t *p = predict_mode; *p >= 0; p++ )
                        if( *p == satd_mode )
                        {
                            mobi_limited_modes[n++] = satd_mode;
                            break;
                        }
                    for( const int8_t *p = predict_mode; *p >= 0 && n < mobi_rd_cap; p++ )
                        if( *p != satd_mode )
                            mobi_limited_modes[n++] = *p;
                }
                mobi_limited_modes[n] = -1;
                predict_mode = mobi_limited_modes;
            }

            for( ; *predict_mode >= 0; predict_mode++ )
            {
                int i_mode = *predict_mode;
                i_satd = rd_cost_i4x4( h, a->i_lambda2, idx, i_mode );

                if( i_best > i_satd )
                {
                    a->i_predict4x4[idx] = i_mode;
                    i_best = i_satd;
                    for( int p = 0; p < plane_count; p++ )
                    {
                        pels[p][0] = MPIXEL_X4( dst[p]+0*FDEC_STRIDE );
                        pels[p][1] = MPIXEL_X4( dst[p]+1*FDEC_STRIDE );
                        pels[p][2] = MPIXEL_X4( dst[p]+2*FDEC_STRIDE );
                        pels[p][3] = MPIXEL_X4( dst[p]+3*FDEC_STRIDE );
                        nnz[p] = h->mb.cache.non_zero_count[x264_scan8[idx+p*16]];
                    }
                }
            }

            for( int p = 0; p < plane_count; p++ )
            {
                MPIXEL_X4( dst[p]+0*FDEC_STRIDE ) = pels[p][0];
                MPIXEL_X4( dst[p]+1*FDEC_STRIDE ) = pels[p][1];
                MPIXEL_X4( dst[p]+2*FDEC_STRIDE ) = pels[p][2];
                MPIXEL_X4( dst[p]+3*FDEC_STRIDE ) = pels[p][3];
                h->mb.cache.non_zero_count[x264_scan8[idx+p*16]] = nnz[p];
            }

            h->mb.cache.intra4x4_pred_mode[x264_scan8[idx]] = a->i_predict4x4[idx];
        }
    }
    else if( h->mb.i_type == I_8x8 )
    {
        ALIGNED_ARRAY_32( pixel, edge,[4],[32] ); // really [3][36], but they can overlap
        pixel4 pels_h[3][2] = {{0}};
        pixel pels_v[3][7] = {{0}};
        uint16_t nnz[3][2] = {{0}}; //shut up gcc
        for( int idx = 0; idx < 4; idx++ )
        {
            int x = idx&1;
            int y = idx>>1;
            int s8 = X264_SCAN8_0 + 2*x + 16*y;
            pixel *dst[3] = {h->mb.pic.p_fdec[0] + 8*x + 8*y*FDEC_STRIDE,
                             CHROMA_FORMAT ? h->mb.pic.p_fdec[1] + 8*x + 8*y*FDEC_STRIDE : NULL,
                             CHROMA_FORMAT ? h->mb.pic.p_fdec[2] + 8*x + 8*y*FDEC_STRIDE : NULL};
            int cbp_luma_new = 0;
            int i_thresh = a->b_early_terminate ? a->i_satd_i8x8_dir[idx][a->i_predict8x8[idx]] * 11/8 : COST_MAX;

            i_best = COST_MAX64;

            const int8_t *predict_mode = predict_8x8_mode_available( a->b_avoid_topright, h->mb.i_neighbour8[idx], idx );
            for( int p = 0; p < plane_count; p++ )
                h->predict_8x8_filter( dst[p], edge[p], h->mb.i_neighbour8[idx], ALL_NEIGHBORS );

            for( ; *predict_mode >= 0; predict_mode++ )
            {
                int i_mode = *predict_mode;
                if( a->i_satd_i8x8_dir[idx][i_mode] > i_thresh )
                    continue;

                h->mb.i_cbp_luma = a->i_cbp_i8x8_luma;
                i_satd = rd_cost_i8x8( h, a->i_lambda2, idx, i_mode, edge );

                if( i_best > i_satd )
                {
                    a->i_predict8x8[idx] = i_mode;
                    cbp_luma_new = h->mb.i_cbp_luma;
                    i_best = i_satd;

                    for( int p = 0; p < plane_count; p++ )
                    {
                        pels_h[p][0] = MPIXEL_X4( dst[p]+7*FDEC_STRIDE+0 );
                        pels_h[p][1] = MPIXEL_X4( dst[p]+7*FDEC_STRIDE+4 );
                        if( !(idx&1) )
                            for( int j = 0; j < 7; j++ )
                                pels_v[p][j] = dst[p][7+j*FDEC_STRIDE];
                        nnz[p][0] = M16( &h->mb.cache.non_zero_count[s8 + 0*8 + p*16] );
                        nnz[p][1] = M16( &h->mb.cache.non_zero_count[s8 + 1*8 + p*16] );
                    }
                }
            }
            a->i_cbp_i8x8_luma = cbp_luma_new;
            for( int p = 0; p < plane_count; p++ )
            {
                MPIXEL_X4( dst[p]+7*FDEC_STRIDE+0 ) = pels_h[p][0];
                MPIXEL_X4( dst[p]+7*FDEC_STRIDE+4 ) = pels_h[p][1];
                if( !(idx&1) )
                    for( int j = 0; j < 7; j++ )
                        dst[p][7+j*FDEC_STRIDE] = pels_v[p][j];
                M16( &h->mb.cache.non_zero_count[s8 + 0*8 + p*16] ) = nnz[p][0];
                M16( &h->mb.cache.non_zero_count[s8 + 1*8 + p*16] ) = nnz[p][1];
            }

            x264_macroblock_cache_intra8x8_pred( h, 2*x, 2*y, a->i_predict8x8[idx] );
        }
    }
}

#define LOAD_FENC(m, src, xoff, yoff) \
{ \
    (m)->p_cost_mv = a->p_cost_mv; \
    (m)->i_stride[0] = h->mb.pic.i_stride[0]; \
    (m)->i_stride[1] = h->mb.pic.i_stride[1]; \
    (m)->i_stride[2] = h->mb.pic.i_stride[2]; \
    (m)->p_fenc[0] = &(src)[0][(xoff)+(yoff)*FENC_STRIDE]; \
    if( CHROMA_FORMAT ) \
    { \
        (m)->p_fenc[1] = &(src)[1][((xoff)>>CHROMA_H_SHIFT)+((yoff)>>CHROMA_V_SHIFT)*FENC_STRIDE]; \
        (m)->p_fenc[2] = &(src)[2][((xoff)>>CHROMA_H_SHIFT)+((yoff)>>CHROMA_V_SHIFT)*FENC_STRIDE]; \
    } \
}

#define LOAD_HPELS(m, src, list, ref, xoff, yoff) \
{ \
    (m)->p_fref_w = (m)->p_fref[0] = &(src)[0][(xoff)+(yoff)*(m)->i_stride[0]]; \
    if( h->param.analyse.i_subpel_refine ) \
    { \
        (m)->p_fref[1] = &(src)[1][(xoff)+(yoff)*(m)->i_stride[0]]; \
        (m)->p_fref[2] = &(src)[2][(xoff)+(yoff)*(m)->i_stride[0]]; \
        (m)->p_fref[3] = &(src)[3][(xoff)+(yoff)*(m)->i_stride[0]]; \
    } \
    if( CHROMA444 ) \
    { \
        (m)->p_fref[ 4] = &(src)[ 4][(xoff)+(yoff)*(m)->i_stride[1]]; \
        (m)->p_fref[ 8] = &(src)[ 8][(xoff)+(yoff)*(m)->i_stride[2]]; \
        if( h->param.analyse.i_subpel_refine ) \
        { \
            (m)->p_fref[ 5] = &(src)[ 5][(xoff)+(yoff)*(m)->i_stride[1]]; \
            (m)->p_fref[ 6] = &(src)[ 6][(xoff)+(yoff)*(m)->i_stride[1]]; \
            (m)->p_fref[ 7] = &(src)[ 7][(xoff)+(yoff)*(m)->i_stride[1]]; \
            (m)->p_fref[ 9] = &(src)[ 9][(xoff)+(yoff)*(m)->i_stride[2]]; \
            (m)->p_fref[10] = &(src)[10][(xoff)+(yoff)*(m)->i_stride[2]]; \
            (m)->p_fref[11] = &(src)[11][(xoff)+(yoff)*(m)->i_stride[2]]; \
        } \
    } \
    else if( CHROMA_FORMAT ) \
        (m)->p_fref[4] = &(src)[4][(xoff)+((yoff)>>CHROMA_V_SHIFT)*(m)->i_stride[1]]; \
    if( h->param.analyse.i_me_method >= X264_ME_ESA ) \
        (m)->integral = &h->mb.pic.p_integral[list][ref][(xoff)+(yoff)*(m)->i_stride[0]]; \
    (m)->weight = x264_weight_none; \
    (m)->i_ref = ref; \
}

#define LOAD_WPELS(m, src, list, ref, xoff, yoff) \
    (m)->p_fref_w = &(src)[(xoff)+(yoff)*(m)->i_stride[0]]; \
    (m)->weight = h->sh.weight[i_ref];

#define REF_COST(list, ref) \
    (a->p_cost_ref[list][ref])

static void mb_analyse_inter_p16x16( x264_t *h, x264_mb_analysis_t *a )
{
    x264_me_t m;
    int i_mvc;
    ALIGNED_ARRAY_8( int16_t, mvc,[8],[2] );
    int i_halfpel_thresh = INT_MAX;
    int *p_halfpel_thresh = (a->b_early_terminate && h->mb.pic.i_fref[0]>1) ? &i_halfpel_thresh : NULL;

    /* 16x16 Search on all ref frame */
    m.i_pixel = PIXEL_16x16;
    LOAD_FENC( &m, h->mb.pic.p_fenc, 0, 0 );

    a->l0.me16x16.cost = INT_MAX;
    for( int i_ref = 0; i_ref < h->mb.pic.i_fref[0]; i_ref++ )
    {
        m.i_ref_cost = REF_COST( 0, i_ref );
        i_halfpel_thresh -= m.i_ref_cost;

        /* search with ref */
        LOAD_HPELS( &m, h->mb.pic.p_fref[0][i_ref], 0, i_ref, 0, 0 );
        LOAD_WPELS( &m, h->mb.pic.p_fref_w[i_ref], 0, i_ref, 0, 0 );

        x264_mb_predict_mv_16x16( h, 0, i_ref, m.mvp );

        if( h->mb.ref_blind_dupe == i_ref )
        {
            CP32( m.mv, a->l0.mvc[0][0] );
            x264_me_refine_qpel_refdupe( h, &m, p_halfpel_thresh );
        }
        else
        {
            x264_mb_predict_mv_ref16x16( h, 0, i_ref, mvc, &i_mvc );
            x264_me_search_ref( h, &m, mvc, i_mvc, p_halfpel_thresh );
        }

        /* save mv for predicting neighbors */
        CP32( h->mb.mvr[0][i_ref][h->mb.i_mb_xy], m.mv );
        CP32( a->l0.mvc[i_ref][0], m.mv );

        /* early termination
         * SSD threshold would probably be better than SATD */
        if( i_ref == 0
            && a->b_try_skip
            && m.cost-m.cost_mv < 300*a->i_lambda
            &&  abs(m.mv[0]-h->mb.cache.pskip_mv[0])
              + abs(m.mv[1]-h->mb.cache.pskip_mv[1]) <= 1
            && x264_macroblock_probe_pskip( h ) )
        {
            h->mb.i_type = P_SKIP;
            analyse_update_cache( h, a );
            assert( h->mb.cache.pskip_mv[1] <= h->mb.mv_max_spel[1] || h->i_thread_frames == 1 );
            return;
        }

        m.cost += m.i_ref_cost;
        i_halfpel_thresh += m.i_ref_cost;

        if( m.cost < a->l0.me16x16.cost )
            h->mc.memcpy_aligned( &a->l0.me16x16, &m, sizeof(x264_me_t) );
    }

    x264_macroblock_cache_ref( h, 0, 0, 4, 4, 0, a->l0.me16x16.i_ref );
    assert( a->l0.me16x16.mv[1] <= h->mb.mv_max_spel[1] || h->i_thread_frames == 1 );

    h->mb.i_type = P_L0;
    if( a->i_mbrd )
    {
        mb_init_fenc_cache( h, a->i_mbrd >= 2 || h->param.analyse.inter & X264_ANALYSE_PSUB8x8 );
        if( a->l0.me16x16.i_ref == 0 && M32( a->l0.me16x16.mv ) == M32( h->mb.cache.pskip_mv ) && !a->b_force_intra )
        {
            h->mb.i_partition = D_16x16;
            x264_macroblock_cache_mv_ptr( h, 0, 0, 4, 4, 0, a->l0.me16x16.mv );
            a->l0.i_rd16x16 = rd_cost_mb( h, a->i_lambda2 );
            if( !(h->mb.i_cbp_luma|h->mb.i_cbp_chroma) )
                h->mb.i_type = P_SKIP;
        }
    }
}

static void mb_analyse_inter_p8x8_mixed_ref( x264_t *h, x264_mb_analysis_t *a )
{
    x264_me_t m;
    pixel **p_fenc = h->mb.pic.p_fenc;
    int i_maxref = h->mb.pic.i_fref[0]-1;

    h->mb.i_partition = D_8x8;

    #define CHECK_NEIGHBOUR(i)\
    {\
        int ref = h->mb.cache.ref[0][X264_SCAN8_0+i];\
        if( ref > i_maxref && ref != h->mb.ref_blind_dupe )\
            i_maxref = ref;\
    }

    /* early termination: if 16x16 chose ref 0, then evaluate no refs older
     * than those used by the neighbors */
    if( a->b_early_terminate && (i_maxref > 0 && (a->l0.me16x16.i_ref == 0 || a->l0.me16x16.i_ref == h->mb.ref_blind_dupe) &&
        h->mb.i_mb_type_top > 0 && h->mb.i_mb_type_left[0] > 0) )
    {
        i_maxref = 0;
        CHECK_NEIGHBOUR(  -8 - 1 );
        CHECK_NEIGHBOUR(  -8 + 0 );
        CHECK_NEIGHBOUR(  -8 + 2 );
        CHECK_NEIGHBOUR(  -8 + 4 );
        CHECK_NEIGHBOUR(   0 - 1 );
        CHECK_NEIGHBOUR( 2*8 - 1 );
    }
    #undef CHECK_NEIGHBOUR

    for( int i_ref = 0; i_ref <= i_maxref; i_ref++ )
        CP32( a->l0.mvc[i_ref][0], h->mb.mvr[0][i_ref][h->mb.i_mb_xy] );

    for( int i = 0; i < 4; i++ )
    {
        x264_me_t *l0m = &a->l0.me8x8[i];
        int x8 = i&1;
        int y8 = i>>1;

        m.i_pixel = PIXEL_8x8;

        LOAD_FENC( &m, p_fenc, 8*x8, 8*y8 );
        l0m->cost = INT_MAX;
        for( int i_ref = 0; i_ref <= i_maxref || i_ref == h->mb.ref_blind_dupe; )
        {
            m.i_ref_cost = REF_COST( 0, i_ref );

            LOAD_HPELS( &m, h->mb.pic.p_fref[0][i_ref], 0, i_ref, 8*x8, 8*y8 );
            LOAD_WPELS( &m, h->mb.pic.p_fref_w[i_ref], 0, i_ref, 8*x8, 8*y8 );

            x264_macroblock_cache_ref( h, 2*x8, 2*y8, 2, 2, 0, i_ref );
            x264_mb_predict_mv( h, 0, 4*i, 2, m.mvp );
            if( h->mb.ref_blind_dupe == i_ref )
            {
                CP32( m.mv, a->l0.mvc[0][i+1] );
                x264_me_refine_qpel_refdupe( h, &m, NULL );
            }
            else
                x264_me_search( h, &m, a->l0.mvc[i_ref], i+1 );

            m.cost += m.i_ref_cost;

            CP32( a->l0.mvc[i_ref][i+1], m.mv );

            if( m.cost < l0m->cost )
                h->mc.memcpy_aligned( l0m, &m, sizeof(x264_me_t) );
            if( i_ref == i_maxref && i_maxref < h->mb.ref_blind_dupe )
                i_ref = h->mb.ref_blind_dupe;
            else
                i_ref++;
        }
        x264_macroblock_cache_mv_ptr( h, 2*x8, 2*y8, 2, 2, 0, l0m->mv );
        x264_macroblock_cache_ref( h, 2*x8, 2*y8, 2, 2, 0, l0m->i_ref );

        a->i_satd8x8[0][i] = l0m->cost - ( l0m->cost_mv + l0m->i_ref_cost );

        /* If CABAC is on and we're not doing sub-8x8 analysis, the costs
           are effectively zero. */
        if( !h->param.b_cabac || (h->param.analyse.inter & X264_ANALYSE_PSUB8x8) )
            l0m->cost += a->i_lambda * i_sub_mb_p_cost_table[D_L0_8x8];
    }

    a->l0.i_cost8x8 = a->l0.me8x8[0].cost + a->l0.me8x8[1].cost +
                      a->l0.me8x8[2].cost + a->l0.me8x8[3].cost;
    /* P_8x8 ref0 has no ref cost */
    if( !h->param.b_cabac && !(a->l0.me8x8[0].i_ref | a->l0.me8x8[1].i_ref |
                               a->l0.me8x8[2].i_ref | a->l0.me8x8[3].i_ref) )
        a->l0.i_cost8x8 -= REF_COST( 0, 0 ) * 4;
    M32( h->mb.i_sub_partition ) = D_L0_8x8 * 0x01010101;
}

static void mb_analyse_inter_p8x8( x264_t *h, x264_mb_analysis_t *a )
{
    /* Duplicate refs are rarely useful in p8x8 due to the high cost of the
     * reference frame flags.  Thus, if we're not doing mixedrefs, just
     * don't bother analysing the dupes. */
    const int i_ref = h->mb.ref_blind_dupe == a->l0.me16x16.i_ref ? 0 : a->l0.me16x16.i_ref;
    const int i_ref_cost = h->param.b_cabac || i_ref ? REF_COST( 0, i_ref ) : 0;
    pixel **p_fenc = h->mb.pic.p_fenc;
    int i_mvc;
    int16_t (*mvc)[2] = a->l0.mvc[i_ref];

    /* XXX Needed for x264_mb_predict_mv */
    h->mb.i_partition = D_8x8;

    i_mvc = 1;
    CP32( mvc[0], a->l0.me16x16.mv );

    for( int i = 0; i < 4; i++ )
    {
        x264_me_t *m = &a->l0.me8x8[i];
        int x8 = i&1;
        int y8 = i>>1;

        m->i_pixel = PIXEL_8x8;
        m->i_ref_cost = i_ref_cost;

        LOAD_FENC( m, p_fenc, 8*x8, 8*y8 );
        LOAD_HPELS( m, h->mb.pic.p_fref[0][i_ref], 0, i_ref, 8*x8, 8*y8 );
        LOAD_WPELS( m, h->mb.pic.p_fref_w[i_ref], 0, i_ref, 8*x8, 8*y8 );

        x264_mb_predict_mv( h, 0, 4*i, 2, m->mvp );
        x264_me_search( h, m, mvc, i_mvc );

        x264_macroblock_cache_mv_ptr( h, 2*x8, 2*y8, 2, 2, 0, m->mv );

        CP32( mvc[i_mvc], m->mv );
        i_mvc++;

        a->i_satd8x8[0][i] = m->cost - m->cost_mv;

        /* mb type cost */
        m->cost += i_ref_cost;
        if( !h->param.b_cabac || (h->param.analyse.inter & X264_ANALYSE_PSUB8x8) )
            m->cost += a->i_lambda * i_sub_mb_p_cost_table[D_L0_8x8];
    }

    a->l0.i_cost8x8 = a->l0.me8x8[0].cost + a->l0.me8x8[1].cost +
                      a->l0.me8x8[2].cost + a->l0.me8x8[3].cost;
    /* theoretically this should include 4*ref_cost,
     * but 3 seems a better approximation of cabac. */
    if( h->param.b_cabac )
        a->l0.i_cost8x8 -= i_ref_cost;
    M32( h->mb.i_sub_partition ) = D_L0_8x8 * 0x01010101;
}

static void mb_analyse_inter_p16x8( x264_t *h, x264_mb_analysis_t *a, int i_best_satd )
{
    x264_me_t m;
    pixel **p_fenc = h->mb.pic.p_fenc;
    ALIGNED_ARRAY_8( int16_t, mvc,[3],[2] );

    /* XXX Needed for x264_mb_predict_mv */
    h->mb.i_partition = D_16x8;

    for( int i = 0; i < 2; i++ )
    {
        x264_me_t *l0m = &a->l0.me16x8[i];
        const int minref = X264_MIN( a->l0.me8x8[2*i].i_ref, a->l0.me8x8[2*i+1].i_ref );
        const int maxref = X264_MAX( a->l0.me8x8[2*i].i_ref, a->l0.me8x8[2*i+1].i_ref );
        const int ref8[2] = { minref, maxref };
        const int i_ref8s = ( ref8[0] == ref8[1] ) ? 1 : 2;

        m.i_pixel = PIXEL_16x8;

        LOAD_FENC( &m, p_fenc, 0, 8*i );
        l0m->cost = INT_MAX;
        for( int j = 0; j < i_ref8s; j++ )
        {
            const int i_ref = ref8[j];
            m.i_ref_cost = REF_COST( 0, i_ref );

            /* if we skipped the 16x16 predictor, we wouldn't have to copy anything... */
            CP32( mvc[0], a->l0.mvc[i_ref][0] );
            CP32( mvc[1], a->l0.mvc[i_ref][2*i+1] );
            CP32( mvc[2], a->l0.mvc[i_ref][2*i+2] );

            LOAD_HPELS( &m, h->mb.pic.p_fref[0][i_ref], 0, i_ref, 0, 8*i );
            LOAD_WPELS( &m, h->mb.pic.p_fref_w[i_ref], 0, i_ref, 0, 8*i );

            x264_macroblock_cache_ref( h, 0, 2*i, 4, 2, 0, i_ref );
            x264_mb_predict_mv( h, 0, 8*i, 4, m.mvp );
            /* We can only take this shortcut if the first search was performed on ref0. */
            if( h->mb.ref_blind_dupe == i_ref && !ref8[0] )
            {
                /* We can just leave the MV from the previous ref search. */
                x264_me_refine_qpel_refdupe( h, &m, NULL );
            }
            else
                x264_me_search( h, &m, mvc, 3 );

            m.cost += m.i_ref_cost;

            if( m.cost < l0m->cost )
                h->mc.memcpy_aligned( l0m, &m, sizeof(x264_me_t) );
        }

        /* Early termination based on the current SATD score of partition[0]
           plus the estimated SATD score of partition[1] */
        if( a->b_early_terminate && (!i && l0m->cost + a->i_cost_est16x8[1] > i_best_satd * (4 + !!a->i_mbrd) / 4) )
        {
            a->l0.i_cost16x8 = COST_MAX;
            return;
        }

        x264_macroblock_cache_mv_ptr( h, 0, 2*i, 4, 2, 0, l0m->mv );
        x264_macroblock_cache_ref( h, 0, 2*i, 4, 2, 0, l0m->i_ref );
    }

    a->l0.i_cost16x8 = a->l0.me16x8[0].cost + a->l0.me16x8[1].cost;
}

static void mb_analyse_inter_p8x16( x264_t *h, x264_mb_analysis_t *a, int i_best_satd )
{
    x264_me_t m;
    pixel **p_fenc = h->mb.pic.p_fenc;
    ALIGNED_ARRAY_8( int16_t, mvc,[3],[2] );

    /* XXX Needed for x264_mb_predict_mv */
    h->mb.i_partition = D_8x16;

    for( int i = 0; i < 2; i++ )
    {
        x264_me_t *l0m = &a->l0.me8x16[i];
        const int minref = X264_MIN( a->l0.me8x8[i].i_ref, a->l0.me8x8[i+2].i_ref );
        const int maxref = X264_MAX( a->l0.me8x8[i].i_ref, a->l0.me8x8[i+2].i_ref );
        const int ref8[2] = { minref, maxref };
        const int i_ref8s = ( ref8[0] == ref8[1] ) ? 1 : 2;

        m.i_pixel = PIXEL_8x16;

        LOAD_FENC( &m, p_fenc, 8*i, 0 );
        l0m->cost = INT_MAX;
        for( int j = 0; j < i_ref8s; j++ )
        {
            const int i_ref = ref8[j];
            m.i_ref_cost = REF_COST( 0, i_ref );

            CP32( mvc[0], a->l0.mvc[i_ref][0] );
            CP32( mvc[1], a->l0.mvc[i_ref][i+1] );
            CP32( mvc[2], a->l0.mvc[i_ref][i+3] );

            LOAD_HPELS( &m, h->mb.pic.p_fref[0][i_ref], 0, i_ref, 8*i, 0 );
            LOAD_WPELS( &m, h->mb.pic.p_fref_w[i_ref], 0, i_ref, 8*i, 0 );

            x264_macroblock_cache_ref( h, 2*i, 0, 2, 4, 0, i_ref );
            x264_mb_predict_mv( h, 0, 4*i, 2, m.mvp );
            /* We can only take this shortcut if the first search was performed on ref0. */
            if( h->mb.ref_blind_dupe == i_ref && !ref8[0] )
            {
                /* We can just leave the MV from the previous ref search. */
                x264_me_refine_qpel_refdupe( h, &m, NULL );
            }
            else
                x264_me_search( h, &m, mvc, 3 );

            m.cost += m.i_ref_cost;

            if( m.cost < l0m->cost )
                h->mc.memcpy_aligned( l0m, &m, sizeof(x264_me_t) );
        }

        /* Early termination based on the current SATD score of partition[0]
           plus the estimated SATD score of partition[1] */
        if( a->b_early_terminate && (!i && l0m->cost + a->i_cost_est8x16[1] > i_best_satd * (4 + !!a->i_mbrd) / 4) )
        {
            a->l0.i_cost8x16 = COST_MAX;
            return;
        }

        x264_macroblock_cache_mv_ptr( h, 2*i, 0, 2, 4, 0, l0m->mv );
        x264_macroblock_cache_ref( h, 2*i, 0, 2, 4, 0, l0m->i_ref );
    }

    a->l0.i_cost8x16 = a->l0.me8x16[0].cost + a->l0.me8x16[1].cost;
}

static ALWAYS_INLINE int mb_analyse_inter_p4x4_chroma_internal( x264_t *h, x264_mb_analysis_t *a,
                                                                pixel **p_fref, int i8x8, int size, int chroma )
{
    ALIGNED_ARRAY_32( pixel, pix1,[16*16] );
    pixel *pix2 = pix1+8;
    int i_stride = h->mb.pic.i_stride[1];
    int chroma_h_shift = chroma <= CHROMA_422;
    int chroma_v_shift = chroma == CHROMA_420;
    int or = 8*(i8x8&1) + (4>>chroma_v_shift)*(i8x8&2)*i_stride;
    int i_ref = a->l0.me8x8[i8x8].i_ref;
    int mvy_offset = chroma_v_shift && MB_INTERLACED & i_ref ? (h->mb.i_mb_y & 1)*4 - 2 : 0;
    x264_weight_t *weight = h->sh.weight[i_ref];

    // FIXME weight can be done on 4x4 blocks even if mc is smaller
#define CHROMA4x4MC( width, height, me, x, y ) \
    if( chroma == CHROMA_444 ) \
    { \
        int mvx = (me).mv[0] + 4*2*x; \
        int mvy = (me).mv[1] + 4*2*y; \
        h->mc.mc_luma( &pix1[2*x+2*y*16], 16, &h->mb.pic.p_fref[0][i_ref][4], i_stride, \
                       mvx, mvy, 2*width, 2*height, &h->sh.weight[i_ref][1] ); \
        h->mc.mc_luma( &pix2[2*x+2*y*16], 16, &h->mb.pic.p_fref[0][i_ref][8], i_stride, \
                       mvx, mvy, 2*width, 2*height, &h->sh.weight[i_ref][2] ); \
    } \
    else \
    { \
        int offset = x + (2>>chroma_v_shift)*16*y; \
        int chroma_height = (2>>chroma_v_shift)*height; \
        h->mc.mc_chroma( &pix1[offset], &pix2[offset], 16, &p_fref[4][or+2*x+(2>>chroma_v_shift)*y*i_stride], i_stride, \
                         (me).mv[0], (2>>chroma_v_shift)*((me).mv[1]+mvy_offset), width, chroma_height ); \
        if( weight[1].weightfn ) \
            weight[1].weightfn[width>>2]( &pix1[offset], 16, &pix1[offset], 16, &weight[1], chroma_height ); \
        if( weight[2].weightfn ) \
            weight[2].weightfn[width>>2]( &pix2[offset], 16, &pix2[offset], 16, &weight[2], chroma_height ); \
    }

    if( size == PIXEL_4x4 )
    {
        x264_me_t *m = a->l0.me4x4[i8x8];
        CHROMA4x4MC( 2,2, m[0], 0,0 );
        CHROMA4x4MC( 2,2, m[1], 2,0 );
        CHROMA4x4MC( 2,2, m[2], 0,2 );
        CHROMA4x4MC( 2,2, m[3], 2,2 );
    }
    else if( size == PIXEL_8x4 )
    {
        x264_me_t *m = a->l0.me8x4[i8x8];
        CHROMA4x4MC( 4,2, m[0], 0,0 );
        CHROMA4x4MC( 4,2, m[1], 0,2 );
    }
    else
    {
        x264_me_t *m = a->l0.me4x8[i8x8];
        CHROMA4x4MC( 2,4, m[0], 0,0 );
        CHROMA4x4MC( 2,4, m[1], 2,0 );
    }
#undef CHROMA4x4MC

    int oe = (8>>chroma_h_shift)*(i8x8&1) + (4>>chroma_v_shift)*(i8x8&2)*FENC_STRIDE;
    int chromapix = chroma == CHROMA_444 ? PIXEL_8x8 : chroma == CHROMA_422 ? PIXEL_4x8 : PIXEL_4x4;
    return h->pixf.mbcmp[chromapix]( &h->mb.pic.p_fenc[1][oe], FENC_STRIDE, pix1, 16 )
         + h->pixf.mbcmp[chromapix]( &h->mb.pic.p_fenc[2][oe], FENC_STRIDE, pix2, 16 );
}

static int mb_analyse_inter_p4x4_chroma( x264_t *h, x264_mb_analysis_t *a, pixel **p_fref, int i8x8, int size )
{
    if( CHROMA_FORMAT == CHROMA_444 )
        return mb_analyse_inter_p4x4_chroma_internal( h, a, p_fref, i8x8, size, CHROMA_444 );
    else if( CHROMA_FORMAT == CHROMA_422 )
        return mb_analyse_inter_p4x4_chroma_internal( h, a, p_fref, i8x8, size, CHROMA_422 );
    else
        return mb_analyse_inter_p4x4_chroma_internal( h, a, p_fref, i8x8, size, CHROMA_420 );
}

static void mb_analyse_inter_p4x4( x264_t *h, x264_mb_analysis_t *a, int i8x8 )
{
    pixel **p_fref = h->mb.pic.p_fref[0][a->l0.me8x8[i8x8].i_ref];
    pixel **p_fenc = h->mb.pic.p_fenc;
    const int i_ref = a->l0.me8x8[i8x8].i_ref;

    /* XXX Needed for x264_mb_predict_mv */
    h->mb.i_partition = D_8x8;

    for( int i4x4 = 0; i4x4 < 4; i4x4++ )
    {
        const int idx = 4*i8x8 + i4x4;
        const int x4 = block_idx_x[idx];
        const int y4 = block_idx_y[idx];
        const int i_mvc = (i4x4 == 0);

        x264_me_t *m = &a->l0.me4x4[i8x8][i4x4];

        m->i_pixel = PIXEL_4x4;

        LOAD_FENC( m, p_fenc, 4*x4, 4*y4 );
        LOAD_HPELS( m, p_fref, 0, i_ref, 4*x4, 4*y4 );
        LOAD_WPELS( m, h->mb.pic.p_fref_w[i_ref], 0, i_ref, 4*x4, 4*y4 );

        x264_mb_predict_mv( h, 0, idx, 1, m->mvp );
        x264_me_search( h, m, &a->l0.me8x8[i8x8].mv, i_mvc );

        x264_macroblock_cache_mv_ptr( h, x4, y4, 1, 1, 0, m->mv );
    }
    a->l0.i_cost4x4[i8x8] = a->l0.me4x4[i8x8][0].cost +
                            a->l0.me4x4[i8x8][1].cost +
                            a->l0.me4x4[i8x8][2].cost +
                            a->l0.me4x4[i8x8][3].cost +
                            REF_COST( 0, i_ref ) +
                            a->i_lambda * i_sub_mb_p_cost_table[D_L0_4x4];
    if( h->mb.b_chroma_me && !CHROMA444 )
        a->l0.i_cost4x4[i8x8] += mb_analyse_inter_p4x4_chroma( h, a, p_fref, i8x8, PIXEL_4x4 );
}

static void mb_analyse_inter_p8x4( x264_t *h, x264_mb_analysis_t *a, int i8x8 )
{
    pixel **p_fref = h->mb.pic.p_fref[0][a->l0.me8x8[i8x8].i_ref];
    pixel **p_fenc = h->mb.pic.p_fenc;
    const int i_ref = a->l0.me8x8[i8x8].i_ref;

    /* XXX Needed for x264_mb_predict_mv */
    h->mb.i_partition = D_8x8;

    for( int i8x4 = 0; i8x4 < 2; i8x4++ )
    {
        const int idx = 4*i8x8 + 2*i8x4;
        const int x4 = block_idx_x[idx];
        const int y4 = block_idx_y[idx];
        const int i_mvc = (i8x4 == 0);

        x264_me_t *m = &a->l0.me8x4[i8x8][i8x4];

        m->i_pixel = PIXEL_8x4;

        LOAD_FENC( m, p_fenc, 4*x4, 4*y4 );
        LOAD_HPELS( m, p_fref, 0, i_ref, 4*x4, 4*y4 );
        LOAD_WPELS( m, h->mb.pic.p_fref_w[i_ref], 0, i_ref, 4*x4, 4*y4 );

        x264_mb_predict_mv( h, 0, idx, 2, m->mvp );
        x264_me_search( h, m, &a->l0.me4x4[i8x8][0].mv, i_mvc );

        x264_macroblock_cache_mv_ptr( h, x4, y4, 2, 1, 0, m->mv );
    }
    a->l0.i_cost8x4[i8x8] = a->l0.me8x4[i8x8][0].cost + a->l0.me8x4[i8x8][1].cost +
                            REF_COST( 0, i_ref ) +
                            a->i_lambda * i_sub_mb_p_cost_table[D_L0_8x4];
    if( h->mb.b_chroma_me && !CHROMA444 )
        a->l0.i_cost8x4[i8x8] += mb_analyse_inter_p4x4_chroma( h, a, p_fref, i8x8, PIXEL_8x4 );
}

static void mb_analyse_inter_p4x8( x264_t *h, x264_mb_analysis_t *a, int i8x8 )
{
    pixel **p_fref = h->mb.pic.p_fref[0][a->l0.me8x8[i8x8].i_ref];
    pixel **p_fenc = h->mb.pic.p_fenc;
    const int i_ref = a->l0.me8x8[i8x8].i_ref;

    /* XXX Needed for x264_mb_predict_mv */
    h->mb.i_partition = D_8x8;

    for( int i4x8 = 0; i4x8 < 2; i4x8++ )
    {
        const int idx = 4*i8x8 + i4x8;
        const int x4 = block_idx_x[idx];
        const int y4 = block_idx_y[idx];
        const int i_mvc = (i4x8 == 0);

        x264_me_t *m = &a->l0.me4x8[i8x8][i4x8];

        m->i_pixel = PIXEL_4x8;

        LOAD_FENC( m, p_fenc, 4*x4, 4*y4 );
        LOAD_HPELS( m, p_fref, 0, i_ref, 4*x4, 4*y4 );
        LOAD_WPELS( m, h->mb.pic.p_fref_w[i_ref], 0, i_ref, 4*x4, 4*y4 );

        x264_mb_predict_mv( h, 0, idx, 1, m->mvp );
        x264_me_search( h, m, &a->l0.me4x4[i8x8][0].mv, i_mvc );

        x264_macroblock_cache_mv_ptr( h, x4, y4, 1, 2, 0, m->mv );
    }
    a->l0.i_cost4x8[i8x8] = a->l0.me4x8[i8x8][0].cost + a->l0.me4x8[i8x8][1].cost +
                            REF_COST( 0, i_ref ) +
                            a->i_lambda * i_sub_mb_p_cost_table[D_L0_4x8];
    if( h->mb.b_chroma_me && !CHROMA444 )
        a->l0.i_cost4x8[i8x8] += mb_analyse_inter_p4x4_chroma( h, a, p_fref, i8x8, PIXEL_4x8 );
}

static ALWAYS_INLINE int analyse_bi_chroma( x264_t *h, x264_mb_analysis_t *a, int idx, int i_pixel )
{
    ALIGNED_ARRAY_32( pixel, pix, [4],[16*16] );
    ALIGNED_ARRAY_32( pixel,  bi, [2],[16*16] );
    int i_chroma_cost = 0;
    int chromapix = h->luma2chroma_pixel[i_pixel];

#define COST_BI_CHROMA( m0, m1, width, height ) \
{ \
    if( CHROMA444 ) \
    { \
        h->mc.mc_luma( pix[0], 16, &m0.p_fref[4], m0.i_stride[1], \
                       m0.mv[0], m0.mv[1], width, height, x264_weight_none ); \
        h->mc.mc_luma( pix[1], 16, &m0.p_fref[8], m0.i_stride[2], \
                       m0.mv[0], m0.mv[1], width, height, x264_weight_none ); \
        h->mc.mc_luma( pix[2], 16, &m1.p_fref[4], m1.i_stride[1], \
                       m1.mv[0], m1.mv[1], width, height, x264_weight_none ); \
        h->mc.mc_luma( pix[3], 16, &m1.p_fref[8], m1.i_stride[2], \
                       m1.mv[0], m1.mv[1], width, height, x264_weight_none ); \
    } \
    else \
    { \
        int v_shift = CHROMA_V_SHIFT; \
        int l0_mvy_offset = v_shift & MB_INTERLACED & m0.i_ref ? (h->mb.i_mb_y & 1)*4 - 2 : 0; \
        int l1_mvy_offset = v_shift & MB_INTERLACED & m1.i_ref ? (h->mb.i_mb_y & 1)*4 - 2 : 0; \
        h->mc.mc_chroma( pix[0], pix[1], 16, m0.p_fref[4], m0.i_stride[1], \
                         m0.mv[0], 2*(m0.mv[1]+l0_mvy_offset)>>v_shift, width>>1, height>>v_shift ); \
        h->mc.mc_chroma( pix[2], pix[3], 16, m1.p_fref[4], m1.i_stride[1], \
                         m1.mv[0], 2*(m1.mv[1]+l1_mvy_offset)>>v_shift, width>>1, height>>v_shift ); \
    } \
    h->mc.avg[chromapix]( bi[0], 16, pix[0], 16, pix[2], 16, h->mb.bipred_weight[m0.i_ref][m1.i_ref] ); \
    h->mc.avg[chromapix]( bi[1], 16, pix[1], 16, pix[3], 16, h->mb.bipred_weight[m0.i_ref][m1.i_ref] ); \
    i_chroma_cost = h->pixf.mbcmp[chromapix]( m0.p_fenc[1], FENC_STRIDE, bi[0], 16 ) \
                  + h->pixf.mbcmp[chromapix]( m0.p_fenc[2], FENC_STRIDE, bi[1], 16 ); \
}

    if( i_pixel == PIXEL_16x16 )
        COST_BI_CHROMA( a->l0.bi16x16, a->l1.bi16x16, 16, 16 )
    else if( i_pixel == PIXEL_16x8 )
        COST_BI_CHROMA( a->l0.me16x8[idx], a->l1.me16x8[idx], 16, 8 )
    else if( i_pixel == PIXEL_8x16 )
        COST_BI_CHROMA( a->l0.me8x16[idx], a->l1.me8x16[idx], 8, 16 )
    else
        COST_BI_CHROMA( a->l0.me8x8[idx], a->l1.me8x8[idx], 8, 8 )

    return i_chroma_cost;
}

static void mb_analyse_inter_direct( x264_t *h, x264_mb_analysis_t *a )
{
    /* Assumes that fdec still contains the results of
     * x264_mb_predict_mv_direct16x16 and x264_mb_mc */

    pixel *p_fenc = h->mb.pic.p_fenc[0];
    pixel *p_fdec = h->mb.pic.p_fdec[0];

    a->i_cost16x16direct = a->i_lambda * i_mb_b_cost_table[B_DIRECT];
    if( h->param.analyse.inter & X264_ANALYSE_BSUB16x16 )
    {
        int chromapix = h->luma2chroma_pixel[PIXEL_8x8];

        for( int i = 0; i < 4; i++ )
        {
            const int x = (i&1)*8;
            const int y = (i>>1)*8;
            a->i_cost8x8direct[i] = h->pixf.mbcmp[PIXEL_8x8]( &p_fenc[x+y*FENC_STRIDE], FENC_STRIDE,
                                                              &p_fdec[x+y*FDEC_STRIDE], FDEC_STRIDE );
            if( h->mb.b_chroma_me )
            {
                int fenc_offset = (x>>CHROMA_H_SHIFT) + (y>>CHROMA_V_SHIFT)*FENC_STRIDE;
                int fdec_offset = (x>>CHROMA_H_SHIFT) + (y>>CHROMA_V_SHIFT)*FDEC_STRIDE;
                a->i_cost8x8direct[i] += h->pixf.mbcmp[chromapix]( &h->mb.pic.p_fenc[1][fenc_offset], FENC_STRIDE,
                                                                   &h->mb.pic.p_fdec[1][fdec_offset], FDEC_STRIDE )
                                       + h->pixf.mbcmp[chromapix]( &h->mb.pic.p_fenc[2][fenc_offset], FENC_STRIDE,
                                                                   &h->mb.pic.p_fdec[2][fdec_offset], FDEC_STRIDE );
            }
            a->i_cost16x16direct += a->i_cost8x8direct[i];

            /* mb type cost */
            a->i_cost8x8direct[i] += a->i_lambda * i_sub_mb_b_cost_table[D_DIRECT_8x8];
        }
    }
    else
    {
        a->i_cost16x16direct += h->pixf.mbcmp[PIXEL_16x16]( p_fenc, FENC_STRIDE, p_fdec, FDEC_STRIDE );
        if( h->mb.b_chroma_me )
        {
            int chromapix = h->luma2chroma_pixel[PIXEL_16x16];
            a->i_cost16x16direct += h->pixf.mbcmp[chromapix]( h->mb.pic.p_fenc[1], FENC_STRIDE, h->mb.pic.p_fdec[1], FDEC_STRIDE )
                                 +  h->pixf.mbcmp[chromapix]( h->mb.pic.p_fenc[2], FENC_STRIDE, h->mb.pic.p_fdec[2], FDEC_STRIDE );
        }
    }
}

static void mb_analyse_inter_b16x16( x264_t *h, x264_mb_analysis_t *a )
{
    ALIGNED_ARRAY_32( pixel, pix0,[16*16] );
    ALIGNED_ARRAY_32( pixel, pix1,[16*16] );
    pixel *src0, *src1;
    intptr_t stride0 = 16, stride1 = 16;
    int i_ref, i_mvc;
    ALIGNED_ARRAY_8( int16_t, mvc,[9],[2] );
    int try_skip = a->b_try_skip;
    int list1_skipped = 0;
    int i_halfpel_thresh[2] = {INT_MAX, INT_MAX};
    int *p_halfpel_thresh[2] = {(a->b_early_terminate && h->mb.pic.i_fref[0]>1) ? &i_halfpel_thresh[0] : NULL,
                                (a->b_early_terminate && h->mb.pic.i_fref[1]>1) ? &i_halfpel_thresh[1] : NULL};

    x264_me_t m;
    m.i_pixel = PIXEL_16x16;

    LOAD_FENC( &m, h->mb.pic.p_fenc, 0, 0 );

    /* 16x16 Search on list 0 and list 1 */
    a->l0.me16x16.cost = INT_MAX;
    a->l1.me16x16.cost = INT_MAX;
    for( int l = 1; l >= 0; )
    {
        x264_mb_analysis_list_t *lX = l ? &a->l1 : &a->l0;

        /* This loop is extremely munged in order to facilitate the following order of operations,
         * necessary for an efficient fast skip.
         * 1.  Search list1 ref0.
         * 2.  Search list0 ref0.
         * 3.  Try skip.
         * 4.  Search the rest of list0.
         * 5.  Go back and finish list1.
         */
        for( i_ref = (list1_skipped && l == 1) ? 1 : 0; i_ref < h->mb.pic.i_fref[l]; i_ref++ )
        {
            if( try_skip && l == 1 && i_ref > 0 )
            {
                list1_skipped = 1;
                break;
            }

            m.i_ref_cost = REF_COST( l, i_ref );

            /* search with ref */
            LOAD_HPELS( &m, h->mb.pic.p_fref[l][i_ref], l, i_ref, 0, 0 );
            x264_mb_predict_mv_16x16( h, l, i_ref, m.mvp );
            x264_mb_predict_mv_ref16x16( h, l, i_ref, mvc, &i_mvc );
            x264_me_search_ref( h, &m, mvc, i_mvc, p_halfpel_thresh[l] );

            /* add ref cost */
            m.cost += m.i_ref_cost;

            if( m.cost < lX->me16x16.cost )
                h->mc.memcpy_aligned( &lX->me16x16, &m, sizeof(x264_me_t) );

            /* save mv for predicting neighbors */
            CP32( lX->mvc[i_ref][0], m.mv );
            CP32( h->mb.mvr[l][i_ref][h->mb.i_mb_xy], m.mv );

            /* Fast skip detection. */
            if( i_ref == 0 && try_skip )
            {
                if( abs(lX->me16x16.mv[0]-h->mb.cache.direct_mv[l][0][0]) +
                    abs(lX->me16x16.mv[1]-h->mb.cache.direct_mv[l][0][1]) > 1 )
                {
                    try_skip = 0;
                }
                else if( !l )
                {
                    /* We already tested skip */
                    h->mb.i_type = B_SKIP;
                    analyse_update_cache( h, a );
                    return;
                }
            }
        }
        if( list1_skipped && l == 1 && i_ref == h->mb.pic.i_fref[1] )
            break;
        if( list1_skipped && l == 0 )
            l = 1;
        else
            l--;
    }

    /* get cost of BI mode */
    h->mc.memcpy_aligned( &a->l0.bi16x16, &a->l0.me16x16, sizeof(x264_me_t) );
    h->mc.memcpy_aligned( &a->l1.bi16x16, &a->l1.me16x16, sizeof(x264_me_t) );
    int ref_costs = REF_COST( 0, a->l0.bi16x16.i_ref ) + REF_COST( 1, a->l1.bi16x16.i_ref );
    src0 = h->mc.get_ref( pix0, &stride0,
                          h->mb.pic.p_fref[0][a->l0.bi16x16.i_ref], h->mb.pic.i_stride[0],
                          a->l0.bi16x16.mv[0], a->l0.bi16x16.mv[1], 16, 16, x264_weight_none );
    src1 = h->mc.get_ref( pix1, &stride1,
                          h->mb.pic.p_fref[1][a->l1.bi16x16.i_ref], h->mb.pic.i_stride[0],
                          a->l1.bi16x16.mv[0], a->l1.bi16x16.mv[1], 16, 16, x264_weight_none );

    h->mc.avg[PIXEL_16x16]( pix0, 16, src0, stride0, src1, stride1, h->mb.bipred_weight[a->l0.bi16x16.i_ref][a->l1.bi16x16.i_ref] );

    a->i_cost16x16bi = h->pixf.mbcmp[PIXEL_16x16]( h->mb.pic.p_fenc[0], FENC_STRIDE, pix0, 16 )
                     + ref_costs
                     + a->l0.bi16x16.cost_mv
                     + a->l1.bi16x16.cost_mv;

    if( h->mb.b_chroma_me )
        a->i_cost16x16bi += analyse_bi_chroma( h, a, 0, PIXEL_16x16 );

    /* Always try the 0,0,0,0 vector; helps avoid errant motion vectors in fades */
    if( M32( a->l0.bi16x16.mv ) | M32( a->l1.bi16x16.mv ) )
    {
        int l0_mv_cost = a->l0.bi16x16.p_cost_mv[-a->l0.bi16x16.mvp[0]]
                       + a->l0.bi16x16.p_cost_mv[-a->l0.bi16x16.mvp[1]];
        int l1_mv_cost = a->l1.bi16x16.p_cost_mv[-a->l1.bi16x16.mvp[0]]
                       + a->l1.bi16x16.p_cost_mv[-a->l1.bi16x16.mvp[1]];
        h->mc.avg[PIXEL_16x16]( pix0, 16, h->mb.pic.p_fref[0][a->l0.bi16x16.i_ref][0], h->mb.pic.i_stride[0],
                                h->mb.pic.p_fref[1][a->l1.bi16x16.i_ref][0], h->mb.pic.i_stride[0],
                                h->mb.bipred_weight[a->l0.bi16x16.i_ref][a->l1.bi16x16.i_ref] );
        int cost00 = h->pixf.mbcmp[PIXEL_16x16]( h->mb.pic.p_fenc[0], FENC_STRIDE, pix0, 16 )
                   + ref_costs + l0_mv_cost + l1_mv_cost;

        if( h->mb.b_chroma_me && cost00 < a->i_cost16x16bi )
        {
            ALIGNED_ARRAY_16( pixel, bi, [16*FENC_STRIDE] );

            if( CHROMA444 )
            {
                h->mc.avg[PIXEL_16x16]( bi, FENC_STRIDE, h->mb.pic.p_fref[0][a->l0.bi16x16.i_ref][4], h->mb.pic.i_stride[1],
                                        h->mb.pic.p_fref[1][a->l1.bi16x16.i_ref][4], h->mb.pic.i_stride[1],
                                        h->mb.bipred_weight[a->l0.bi16x16.i_ref][a->l1.bi16x16.i_ref] );
                cost00 += h->pixf.mbcmp[PIXEL_16x16]( h->mb.pic.p_fenc[1], FENC_STRIDE, bi, FENC_STRIDE );
                h->mc.avg[PIXEL_16x16]( bi, FENC_STRIDE, h->mb.pic.p_fref[0][a->l0.bi16x16.i_ref][8], h->mb.pic.i_stride[2],
                                        h->mb.pic.p_fref[1][a->l1.bi16x16.i_ref][8], h->mb.pic.i_stride[2],
                                        h->mb.bipred_weight[a->l0.bi16x16.i_ref][a->l1.bi16x16.i_ref] );
                cost00 += h->pixf.mbcmp[PIXEL_16x16]( h->mb.pic.p_fenc[2], FENC_STRIDE, bi, FENC_STRIDE );
            }
            else
            {
                ALIGNED_ARRAY_64( pixel, pixuv, [2],[16*FENC_STRIDE] );
                int chromapix = h->luma2chroma_pixel[PIXEL_16x16];
                int v_shift = CHROMA_V_SHIFT;

                if( v_shift & MB_INTERLACED & a->l0.bi16x16.i_ref )
                {
                    int l0_mvy_offset = (h->mb.i_mb_y & 1)*4 - 2;
                    h->mc.mc_chroma( pixuv[0], pixuv[0]+8, FENC_STRIDE, h->mb.pic.p_fref[0][a->l0.bi16x16.i_ref][4],
                                     h->mb.pic.i_stride[1], 0, 0 + l0_mvy_offset, 8, 8 );
                }
                else
                    h->mc.load_deinterleave_chroma_fenc( pixuv[0], h->mb.pic.p_fref[0][a->l0.bi16x16.i_ref][4],
                                                         h->mb.pic.i_stride[1], 16>>v_shift );

                if( v_shift & MB_INTERLACED & a->l1.bi16x16.i_ref )
                {
                    int l1_mvy_offset = (h->mb.i_mb_y & 1)*4 - 2;
                    h->mc.mc_chroma( pixuv[1], pixuv[1]+8, FENC_STRIDE, h->mb.pic.p_fref[1][a->l1.bi16x16.i_ref][4],
                                     h->mb.pic.i_stride[1], 0, 0 + l1_mvy_offset, 8, 8 );
                }
                else
                    h->mc.load_deinterleave_chroma_fenc( pixuv[1], h->mb.pic.p_fref[1][a->l1.bi16x16.i_ref][4],
                                                         h->mb.pic.i_stride[1], 16>>v_shift );

                h->mc.avg[chromapix]( bi,   FENC_STRIDE, pixuv[0],   FENC_STRIDE, pixuv[1],   FENC_STRIDE,
                                      h->mb.bipred_weight[a->l0.bi16x16.i_ref][a->l1.bi16x16.i_ref] );
                h->mc.avg[chromapix]( bi+8, FENC_STRIDE, pixuv[0]+8, FENC_STRIDE, pixuv[1]+8, FENC_STRIDE,
                                      h->mb.bipred_weight[a->l0.bi16x16.i_ref][a->l1.bi16x16.i_ref] );

                cost00 += h->pixf.mbcmp[chromapix]( h->mb.pic.p_fenc[1], FENC_STRIDE, bi,   FENC_STRIDE )
                       +  h->pixf.mbcmp[chromapix]( h->mb.pic.p_fenc[2], FENC_STRIDE, bi+8, FENC_STRIDE );
            }
        }

        if( cost00 < a->i_cost16x16bi )
        {
            M32( a->l0.bi16x16.mv ) = 0;
            M32( a->l1.bi16x16.mv ) = 0;
            a->l0.bi16x16.cost_mv = l0_mv_cost;
            a->l1.bi16x16.cost_mv = l1_mv_cost;
            a->i_cost16x16bi = cost00;
        }
    }

    /* mb type cost */
    a->i_cost16x16bi   += a->i_lambda * i_mb_b_cost_table[B_BI_BI];
    a->l0.me16x16.cost += a->i_lambda * i_mb_b_cost_table[B_L0_L0];
    a->l1.me16x16.cost += a->i_lambda * i_mb_b_cost_table[B_L1_L1];
}

static inline void mb_cache_mv_p8x8( x264_t *h, x264_mb_analysis_t *a, int i )
{
    int x = 2*(i&1);
    int y = i&2;

    switch( h->mb.i_sub_partition[i] )
    {
        case D_L0_8x8:
            x264_macroblock_cache_mv_ptr( h, x, y, 2, 2, 0, a->l0.me8x8[i].mv );
            break;
        case D_L0_8x4:
            x264_macroblock_cache_mv_ptr( h, x, y+0, 2, 1, 0, a->l0.me8x4[i][0].mv );
            x264_macroblock_cache_mv_ptr( h, x, y+1, 2, 1, 0, a->l0.me8x4[i][1].mv );
            break;
        case D_L0_4x8:
            x264_macroblock_cache_mv_ptr( h, x+0, y, 1, 2, 0, a->l0.me4x8[i][0].mv );
            x264_macroblock_cache_mv_ptr( h, x+1, y, 1, 2, 0, a->l0.me4x8[i][1].mv );
            break;
        case D_L0_4x4:
            x264_macroblock_cache_mv_ptr( h, x+0, y+0, 1, 1, 0, a->l0.me4x4[i][0].mv );
            x264_macroblock_cache_mv_ptr( h, x+1, y+0, 1, 1, 0, a->l0.me4x4[i][1].mv );
            x264_macroblock_cache_mv_ptr( h, x+0, y+1, 1, 1, 0, a->l0.me4x4[i][2].mv );
            x264_macroblock_cache_mv_ptr( h, x+1, y+1, 1, 1, 0, a->l0.me4x4[i][3].mv );
            break;
        default:
            x264_log( h, X264_LOG_ERROR, "internal error\n" );
            break;
    }
}

static void mb_load_mv_direct8x8( x264_t *h, int idx )
{
    int x = 2*(idx&1);
    int y = idx&2;
    x264_macroblock_cache_ref( h, x, y, 2, 2, 0, h->mb.cache.direct_ref[0][idx] );
    x264_macroblock_cache_ref( h, x, y, 2, 2, 1, h->mb.cache.direct_ref[1][idx] );
    x264_macroblock_cache_mv_ptr( h, x, y, 2, 2, 0, h->mb.cache.direct_mv[0][idx] );
    x264_macroblock_cache_mv_ptr( h, x, y, 2, 2, 1, h->mb.cache.direct_mv[1][idx] );
}

#define CACHE_MV_BI(x,y,dx,dy,me0,me1,part) \
    if( x264_mb_partition_listX_table[0][part] ) \
    { \
        x264_macroblock_cache_ref( h, x,y,dx,dy, 0, me0.i_ref ); \
        x264_macroblock_cache_mv_ptr( h, x,y,dx,dy, 0, me0.mv ); \
    } \
    else \
    { \
        x264_macroblock_cache_ref( h, x,y,dx,dy, 0, -1 ); \
        x264_macroblock_cache_mv(  h, x,y,dx,dy, 0, 0 ); \
        if( b_mvd ) \
            x264_macroblock_cache_mvd( h, x,y,dx,dy, 0, 0 ); \
    } \
    if( x264_mb_partition_listX_table[1][part] ) \
    { \
        x264_macroblock_cache_ref( h, x,y,dx,dy, 1, me1.i_ref ); \
        x264_macroblock_cache_mv_ptr( h, x,y,dx,dy, 1, me1.mv ); \
    } \
    else \
    { \
        x264_macroblock_cache_ref( h, x,y,dx,dy, 1, -1 ); \
        x264_macroblock_cache_mv(  h, x,y,dx,dy, 1, 0 ); \
        if( b_mvd ) \
            x264_macroblock_cache_mvd( h, x,y,dx,dy, 1, 0 ); \
    }

static inline void mb_cache_mv_b8x8( x264_t *h, x264_mb_analysis_t *a, int i, int b_mvd )
{
    int x = 2*(i&1);
    int y = i&2;
    if( h->mb.i_sub_partition[i] == D_DIRECT_8x8 )
    {
        mb_load_mv_direct8x8( h, i );
        if( b_mvd )
        {
            x264_macroblock_cache_mvd(  h, x, y, 2, 2, 0, 0 );
            x264_macroblock_cache_mvd(  h, x, y, 2, 2, 1, 0 );
            x264_macroblock_cache_skip( h, x, y, 2, 2, 1 );
        }
    }
    else
    {
        CACHE_MV_BI( x, y, 2, 2, a->l0.me8x8[i], a->l1.me8x8[i], h->mb.i_sub_partition[i] );
    }
}
static inline void mb_cache_mv_b16x8( x264_t *h, x264_mb_analysis_t *a, int i, int b_mvd )
{
    CACHE_MV_BI( 0, 2*i, 4, 2, a->l0.me16x8[i], a->l1.me16x8[i], a->i_mb_partition16x8[i] );
}
static inline void mb_cache_mv_b8x16( x264_t *h, x264_mb_analysis_t *a, int i, int b_mvd )
{
    CACHE_MV_BI( 2*i, 0, 2, 4, a->l0.me8x16[i], a->l1.me8x16[i], a->i_mb_partition8x16[i] );
}
#undef CACHE_MV_BI

static void mb_analyse_inter_b8x8_mixed_ref( x264_t *h, x264_mb_analysis_t *a )
{
    ALIGNED_ARRAY_16( pixel, pix,[2],[8*8] );
    int i_maxref[2] = {h->mb.pic.i_fref[0]-1, h->mb.pic.i_fref[1]-1};

    /* early termination: if 16x16 chose ref 0, then evaluate no refs older
     * than those used by the neighbors */
    #define CHECK_NEIGHBOUR(i)\
    {\
        int ref = h->mb.cache.ref[l][X264_SCAN8_0+i];\
        if( ref > i_maxref[l] )\
            i_maxref[l] = ref;\
    }

    for( int l = 0; l < 2; l++ )
    {
        x264_mb_analysis_list_t *lX = l ? &a->l1 : &a->l0;
        if( i_maxref[l] > 0 && lX->me16x16.i_ref == 0 &&
            h->mb.i_mb_type_top > 0 && h->mb.i_mb_type_left[0] > 0 )
        {
            i_maxref[l] = 0;
            CHECK_NEIGHBOUR(  -8 - 1 );
            CHECK_NEIGHBOUR(  -8 + 0 );
            CHECK_NEIGHBOUR(  -8 + 2 );
            CHECK_NEIGHBOUR(  -8 + 4 );
            CHECK_NEIGHBOUR(   0 - 1 );
            CHECK_NEIGHBOUR( 2*8 - 1 );
        }
    }

    /* XXX Needed for x264_mb_predict_mv */
    h->mb.i_partition = D_8x8;

    a->i_cost8x8bi = 0;

    for( int i = 0; i < 4; i++ )
    {
        int x8 = i&1;
        int y8 = i>>1;
        int i_part_cost;
        int i_part_cost_bi;
        intptr_t stride[2] = {8,8};
        pixel *src[2];
        x264_me_t m;
        m.i_pixel = PIXEL_8x8;
        LOAD_FENC( &m, h->mb.pic.p_fenc, 8*x8, 8*y8 );

        for( int l = 0; l < 2; l++ )
        {
            x264_mb_analysis_list_t *lX = l ? &a->l1 : &a->l0;

            lX->me8x8[i].cost = INT_MAX;
            for( int i_ref = 0; i_ref <= i_maxref[l]; i_ref++ )
            {
                m.i_ref_cost = REF_COST( l, i_ref );

                LOAD_HPELS( &m, h->mb.pic.p_fref[l][i_ref], l, i_ref, 8*x8, 8*y8 );

                x264_macroblock_cache_ref( h, x8*2, y8*2, 2, 2, l, i_ref );
                x264_mb_predict_mv( h, l, 4*i, 2, m.mvp );
                x264_me_search( h, &m, lX->mvc[i_ref], i+1 );
                m.cost += m.i_ref_cost;

                if( m.cost < lX->me8x8[i].cost )
                {
                    h->mc.memcpy_aligned( &lX->me8x8[i], &m, sizeof(x264_me_t) );
                    a->i_satd8x8[l][i] = m.cost - ( m.cost_mv + m.i_ref_cost );
                }

                /* save mv for predicting other partitions within this MB */
                CP32( lX->mvc[i_ref][i+1], m.mv );
            }
        }

        /* BI mode */
        src[0] = h->mc.get_ref( pix[0], &stride[0], a->l0.me8x8[i].p_fref, a->l0.me8x8[i].i_stride[0],
                                a->l0.me8x8[i].mv[0], a->l0.me8x8[i].mv[1], 8, 8, x264_weight_none );
        src[1] = h->mc.get_ref( pix[1], &stride[1], a->l1.me8x8[i].p_fref, a->l1.me8x8[i].i_stride[0],
                                a->l1.me8x8[i].mv[0], a->l1.me8x8[i].mv[1], 8, 8, x264_weight_none );
        h->mc.avg[PIXEL_8x8]( pix[0], 8, src[0], stride[0], src[1], stride[1],
                                h->mb.bipred_weight[a->l0.me8x8[i].i_ref][a->l1.me8x8[i].i_ref] );

        a->i_satd8x8[2][i] = h->pixf.mbcmp[PIXEL_8x8]( a->l0.me8x8[i].p_fenc[0], FENC_STRIDE, pix[0], 8 );
        i_part_cost_bi = a->i_satd8x8[2][i] + a->l0.me8x8[i].cost_mv + a->l1.me8x8[i].cost_mv
                         + a->l0.me8x8[i].i_ref_cost + a->l1.me8x8[i].i_ref_cost
                         + a->i_lambda * i_sub_mb_b_cost_table[D_BI_8x8];

        if( h->mb.b_chroma_me )
        {
            int i_chroma_cost = analyse_bi_chroma( h, a, i, PIXEL_8x8 );
            i_part_cost_bi += i_chroma_cost;
            a->i_satd8x8[2][i] += i_chroma_cost;
        }

        a->l0.me8x8[i].cost += a->i_lambda * i_sub_mb_b_cost_table[D_L0_8x8];
        a->l1.me8x8[i].cost += a->i_lambda * i_sub_mb_b_cost_table[D_L1_8x8];

        i_part_cost = a->l0.me8x8[i].cost;
        h->mb.i_sub_partition[i] = D_L0_8x8;
        COPY2_IF_LT( i_part_cost, a->l1.me8x8[i].cost, h->mb.i_sub_partition[i], D_L1_8x8 );
        COPY2_IF_LT( i_part_cost, i_part_cost_bi, h->mb.i_sub_partition[i], D_BI_8x8 );
        COPY2_IF_LT( i_part_cost, a->i_cost8x8direct[i], h->mb.i_sub_partition[i], D_DIRECT_8x8 );
        a->i_cost8x8bi += i_part_cost;

        /* XXX Needed for x264_mb_predict_mv */
        mb_cache_mv_b8x8( h, a, i, 0 );
    }

    /* mb type cost */
    a->i_cost8x8bi += a->i_lambda * i_mb_b_cost_table[B_8x8];
}

static void mb_analyse_inter_b8x8( x264_t *h, x264_mb_analysis_t *a )
{
    pixel **p_fref[2] =
        { h->mb.pic.p_fref[0][a->l0.me16x16.i_ref],
          h->mb.pic.p_fref[1][a->l1.me16x16.i_ref] };
    ALIGNED_ARRAY_16( pixel, pix,[2],[8*8] );

    /* XXX Needed for x264_mb_predict_mv */
    h->mb.i_partition = D_8x8;

    a->i_cost8x8bi = 0;

    for( int i = 0; i < 4; i++ )
    {
        int x8 = i&1;
        int y8 = i>>1;
        int i_part_cost;
        int i_part_cost_bi = 0;
        intptr_t stride[2] = {8,8};
        pixel *src[2];

        for( int l = 0; l < 2; l++ )
        {
            x264_mb_analysis_list_t *lX = l ? &a->l1 : &a->l0;
            x264_me_t *m = &lX->me8x8[i];
            m->i_pixel = PIXEL_8x8;
            LOAD_FENC( m, h->mb.pic.p_fenc, 8*x8, 8*y8 );

            m->i_ref_cost = REF_COST( l, lX->me16x16.i_ref );
            m->i_ref = lX->me16x16.i_ref;

            LOAD_HPELS( m, p_fref[l], l, lX->me16x16.i_ref, 8*x8, 8*y8 );

            x264_macroblock_cache_ref( h, x8*2, y8*2, 2, 2, l, lX->me16x16.i_ref );
            x264_mb_predict_mv( h, l, 4*i, 2, m->mvp );
            x264_me_search( h, m, &lX->me16x16.mv, 1 );
            a->i_satd8x8[l][i] = m->cost - m->cost_mv;
            m->cost += m->i_ref_cost;

            x264_macroblock_cache_mv_ptr( h, 2*x8, 2*y8, 2, 2, l, m->mv );

            /* save mv for predicting other partitions within this MB */
            CP32( lX->mvc[lX->me16x16.i_ref][i+1], m->mv );

            /* BI mode */
            src[l] = h->mc.get_ref( pix[l], &stride[l], m->p_fref, m->i_stride[0],
                                    m->mv[0], m->mv[1], 8, 8, x264_weight_none );
            i_part_cost_bi += m->cost_mv + m->i_ref_cost;
        }
        h->mc.avg[PIXEL_8x8]( pix[0], 8, src[0], stride[0], src[1], stride[1], h->mb.bipred_weight[a->l0.me16x16.i_ref][a->l1.me16x16.i_ref] );
        a->i_satd8x8[2][i] = h->pixf.mbcmp[PIXEL_8x8]( a->l0.me8x8[i].p_fenc[0], FENC_STRIDE, pix[0], 8 );
        i_part_cost_bi += a->i_satd8x8[2][i] + a->i_lambda * i_sub_mb_b_cost_table[D_BI_8x8];
        a->l0.me8x8[i].cost += a->i_lambda * i_sub_mb_b_cost_table[D_L0_8x8];
        a->l1.me8x8[i].cost += a->i_lambda * i_sub_mb_b_cost_table[D_L1_8x8];

        if( h->mb.b_chroma_me )
        {
            int i_chroma_cost = analyse_bi_chroma( h, a, i, PIXEL_8x8 );
            i_part_cost_bi += i_chroma_cost;
            a->i_satd8x8[2][i] += i_chroma_cost;
        }

        i_part_cost = a->l0.me8x8[i].cost;
        h->mb.i_sub_partition[i] = D_L0_8x8;
        COPY2_IF_LT( i_part_cost, a->l1.me8x8[i].cost, h->mb.i_sub_partition[i], D_L1_8x8 );
        COPY2_IF_LT( i_part_cost, i_part_cost_bi, h->mb.i_sub_partition[i], D_BI_8x8 );
        COPY2_IF_LT( i_part_cost, a->i_cost8x8direct[i], h->mb.i_sub_partition[i], D_DIRECT_8x8 );
        a->i_cost8x8bi += i_part_cost;

        /* XXX Needed for x264_mb_predict_mv */
        mb_cache_mv_b8x8( h, a, i, 0 );
    }

    /* mb type cost */
    a->i_cost8x8bi += a->i_lambda * i_mb_b_cost_table[B_8x8];
}

static void mb_analyse_inter_b16x8( x264_t *h, x264_mb_analysis_t *a, int i_best_satd )
{
    ALIGNED_ARRAY_32( pixel, pix,[2],[16*8] );
    ALIGNED_ARRAY_8( int16_t, mvc,[3],[2] );

    h->mb.i_partition = D_16x8;
    a->i_cost16x8bi = 0;

    for( int i = 0; i < 2; i++ )
    {
        int i_part_cost;
        int i_part_cost_bi = 0;
        intptr_t stride[2] = {16,16};
        pixel *src[2];
        x264_me_t m;
        m.i_pixel = PIXEL_16x8;
        LOAD_FENC( &m, h->mb.pic.p_fenc, 0, 8*i );

        for( int l = 0; l < 2; l++ )
        {
            x264_mb_analysis_list_t *lX = l ? &a->l1 : &a->l0;
            int ref8[2] = { lX->me8x8[2*i].i_ref, lX->me8x8[2*i+1].i_ref };
            int i_ref8s = ( ref8[0] == ref8[1] ) ? 1 : 2;
            lX->me16x8[i].cost = INT_MAX;
            for( int j = 0; j < i_ref8s; j++ )
            {
                int i_ref = ref8[j];
                m.i_ref_cost = REF_COST( l, i_ref );

                LOAD_HPELS( &m, h->mb.pic.p_fref[l][i_ref], l, i_ref, 0, 8*i );

                CP32( mvc[0], lX->mvc[i_ref][0] );
                CP32( mvc[1], lX->mvc[i_ref][2*i+1] );
                CP32( mvc[2], lX->mvc[i_ref][2*i+2] );

                x264_macroblock_cache_ref( h, 0, 2*i, 4, 2, l, i_ref );
                x264_mb_predict_mv( h, l, 8*i, 4, m.mvp );
                x264_me_search( h, &m, mvc, 3 );
                m.cost += m.i_ref_cost;

                if( m.cost < lX->me16x8[i].cost )
                    h->mc.memcpy_aligned( &lX->me16x8[i], &m, sizeof(x264_me_t) );
            }
        }

        /* BI mode */
        src[0] = h->mc.get_ref( pix[0], &stride[0], a->l0.me16x8[i].p_fref, a->l0.me16x8[i].i_stride[0],
                                a->l0.me16x8[i].mv[0], a->l0.me16x8[i].mv[1], 16, 8, x264_weight_none );
        src[1] = h->mc.get_ref( pix[1], &stride[1], a->l1.me16x8[i].p_fref, a->l1.me16x8[i].i_stride[0],
                                a->l1.me16x8[i].mv[0], a->l1.me16x8[i].mv[1], 16, 8, x264_weight_none );
        h->mc.avg[PIXEL_16x8]( pix[0], 16, src[0], stride[0], src[1], stride[1],
                                h->mb.bipred_weight[a->l0.me16x8[i].i_ref][a->l1.me16x8[i].i_ref] );

        i_part_cost_bi = h->pixf.mbcmp[PIXEL_16x8]( a->l0.me16x8[i].p_fenc[0], FENC_STRIDE, pix[0], 16 )
                        + a->l0.me16x8[i].cost_mv + a->l1.me16x8[i].cost_mv + a->l0.me16x8[i].i_ref_cost
                        + a->l1.me16x8[i].i_ref_cost;

        if( h->mb.b_chroma_me )
            i_part_cost_bi += analyse_bi_chroma( h, a, i, PIXEL_16x8 );

        i_part_cost = a->l0.me16x8[i].cost;
        a->i_mb_partition16x8[i] = D_L0_8x8; /* not actually 8x8, only the L0 matters */

        if( a->l1.me16x8[i].cost < i_part_cost )
        {
            i_part_cost = a->l1.me16x8[i].cost;
            a->i_mb_partition16x8[i] = D_L1_8x8;
        }
        if( i_part_cost_bi + a->i_lambda * 1 < i_part_cost )
        {
            i_part_cost = i_part_cost_bi;
            a->i_mb_partition16x8[i] = D_BI_8x8;
        }
        a->i_cost16x8bi += i_part_cost;

        /* Early termination based on the current SATD score of partition[0]
           plus the estimated SATD score of partition[1] */
        if( a->b_early_terminate && (!i && i_part_cost + a->i_cost_est16x8[1] > i_best_satd
            * (16 + (!!a->i_mbrd + !!h->mb.i_psy_rd))/16) )
        {
            a->i_cost16x8bi = COST_MAX;
            return;
        }

        mb_cache_mv_b16x8( h, a, i, 0 );
    }

    /* mb type cost */
    a->i_mb_type16x8 = B_L0_L0
        + (a->i_mb_partition16x8[0]>>2) * 3
        + (a->i_mb_partition16x8[1]>>2);
    a->i_cost16x8bi += a->i_lambda * i_mb_b16x8_cost_table[a->i_mb_type16x8];
}

static void mb_analyse_inter_b8x16( x264_t *h, x264_mb_analysis_t *a, int i_best_satd )
{
    ALIGNED_ARRAY_16( pixel, pix,[2],[8*16] );
    ALIGNED_ARRAY_8( int16_t, mvc,[3],[2] );

    h->mb.i_partition = D_8x16;
    a->i_cost8x16bi = 0;

    for( int i = 0; i < 2; i++ )
    {
        int i_part_cost;
        int i_part_cost_bi = 0;
        intptr_t stride[2] = {8,8};
        pixel *src[2];
        x264_me_t m;
        m.i_pixel = PIXEL_8x16;
        LOAD_FENC( &m, h->mb.pic.p_fenc, 8*i, 0 );

        for( int l = 0; l < 2; l++ )
        {
            x264_mb_analysis_list_t *lX = l ? &a->l1 : &a->l0;
            int ref8[2] = { lX->me8x8[i].i_ref, lX->me8x8[i+2].i_ref };
            int i_ref8s = ( ref8[0] == ref8[1] ) ? 1 : 2;
            lX->me8x16[i].cost = INT_MAX;
            for( int j = 0; j < i_ref8s; j++ )
            {
                int i_ref = ref8[j];
                m.i_ref_cost = REF_COST( l, i_ref );

                LOAD_HPELS( &m, h->mb.pic.p_fref[l][i_ref], l, i_ref, 8*i, 0 );

                CP32( mvc[0], lX->mvc[i_ref][0] );
                CP32( mvc[1], lX->mvc[i_ref][i+1] );
                CP32( mvc[2], lX->mvc[i_ref][i+3] );

                x264_macroblock_cache_ref( h, 2*i, 0, 2, 4, l, i_ref );
                x264_mb_predict_mv( h, l, 4*i, 2, m.mvp );
                x264_me_search( h, &m, mvc, 3 );
                m.cost += m.i_ref_cost;

                if( m.cost < lX->me8x16[i].cost )
                    h->mc.memcpy_aligned( &lX->me8x16[i], &m, sizeof(x264_me_t) );
            }
        }

        /* BI mode */
        src[0] = h->mc.get_ref( pix[0], &stride[0], a->l0.me8x16[i].p_fref, a->l0.me8x16[i].i_stride[0],
                                a->l0.me8x16[i].mv[0], a->l0.me8x16[i].mv[1], 8, 16, x264_weight_none );
        src[1] = h->mc.get_ref( pix[1], &stride[1], a->l1.me8x16[i].p_fref, a->l1.me8x16[i].i_stride[0],
                                a->l1.me8x16[i].mv[0], a->l1.me8x16[i].mv[1], 8, 16, x264_weight_none );
        h->mc.avg[PIXEL_8x16]( pix[0], 8, src[0], stride[0], src[1], stride[1], h->mb.bipred_weight[a->l0.me8x16[i].i_ref][a->l1.me8x16[i].i_ref] );

        i_part_cost_bi = h->pixf.mbcmp[PIXEL_8x16]( a->l0.me8x16[i].p_fenc[0], FENC_STRIDE, pix[0], 8 )
                        + a->l0.me8x16[i].cost_mv + a->l1.me8x16[i].cost_mv + a->l0.me8x16[i].i_ref_cost
                        + a->l1.me8x16[i].i_ref_cost;

        if( h->mb.b_chroma_me )
            i_part_cost_bi += analyse_bi_chroma( h, a, i, PIXEL_8x16 );

        i_part_cost = a->l0.me8x16[i].cost;
        a->i_mb_partition8x16[i] = D_L0_8x8;

        if( a->l1.me8x16[i].cost < i_part_cost )
        {
            i_part_cost = a->l1.me8x16[i].cost;
            a->i_mb_partition8x16[i] = D_L1_8x8;
        }
        if( i_part_cost_bi + a->i_lambda * 1 < i_part_cost )
        {
            i_part_cost = i_part_cost_bi;
            a->i_mb_partition8x16[i] = D_BI_8x8;
        }
        a->i_cost8x16bi += i_part_cost;

        /* Early termination based on the current SATD score of partition[0]
           plus the estimated SATD score of partition[1] */
        if( a->b_early_terminate && (!i && i_part_cost + a->i_cost_est8x16[1] > i_best_satd
            * (16 + (!!a->i_mbrd + !!h->mb.i_psy_rd))/16) )
        {
            a->i_cost8x16bi = COST_MAX;
            return;
        }

        mb_cache_mv_b8x16( h, a, i, 0 );
    }

    /* mb type cost */
    a->i_mb_type8x16 = B_L0_L0
        + (a->i_mb_partition8x16[0]>>2) * 3
        + (a->i_mb_partition8x16[1]>>2);
    a->i_cost8x16bi += a->i_lambda * i_mb_b16x8_cost_table[a->i_mb_type8x16];
}

static void mb_analyse_p_rd( x264_t *h, x264_mb_analysis_t *a, int i_satd )
{
    int thresh = a->b_early_terminate ? i_satd * 5/4 + 1 : COST_MAX;

    h->mb.i_type = P_L0;
    if( a->l0.i_rd16x16 == COST_MAX && (!a->b_early_terminate || a->l0.me16x16.cost <= i_satd * 3/2) )
    {
        h->mb.i_partition = D_16x16;
        analyse_update_cache( h, a );
        a->l0.i_rd16x16 = rd_cost_mb( h, a->i_lambda2 );
    }

    if( a->l0.i_cost16x8 < thresh )
    {
        h->mb.i_partition = D_16x8;
        analyse_update_cache( h, a );
        a->l0.i_cost16x8 = rd_cost_mb( h, a->i_lambda2 );
    }
    else
        a->l0.i_cost16x8 = COST_MAX;

    if( a->l0.i_cost8x16 < thresh )
    {
        h->mb.i_partition = D_8x16;
        analyse_update_cache( h, a );
        a->l0.i_cost8x16 = rd_cost_mb( h, a->i_lambda2 );
    }
    else
        a->l0.i_cost8x16 = COST_MAX;

    if( a->l0.i_cost8x8 < thresh )
    {
        h->mb.i_type = P_8x8;
        h->mb.i_partition = D_8x8;
        if( h->param.analyse.inter & X264_ANALYSE_PSUB8x8 )
        {
            x264_macroblock_cache_ref( h, 0, 0, 2, 2, 0, a->l0.me8x8[0].i_ref );
            x264_macroblock_cache_ref( h, 2, 0, 2, 2, 0, a->l0.me8x8[1].i_ref );
            x264_macroblock_cache_ref( h, 0, 2, 2, 2, 0, a->l0.me8x8[2].i_ref );
            x264_macroblock_cache_ref( h, 2, 2, 2, 2, 0, a->l0.me8x8[3].i_ref );
            /* FIXME: In the 8x8 blocks where RDO isn't run, the NNZ values used for context selection
             * for future blocks are those left over from previous RDO calls. */
            for( int i = 0; i < 4; i++ )
            {
                int costs[4] = {a->l0.i_cost4x4[i], a->l0.i_cost8x4[i], a->l0.i_cost4x8[i], a->l0.me8x8[i].cost};
                int sub8x8_thresh = a->b_early_terminate ? X264_MIN4( costs[0], costs[1], costs[2], costs[3] ) * 5 / 4 : COST_MAX;
                int subtype, btype = D_L0_8x8;
                uint64_t bcost = COST_MAX64;
                for( subtype = D_L0_4x4; subtype <= D_L0_8x8; subtype++ )
                {
                    uint64_t cost;
                    if( costs[subtype] > sub8x8_thresh )
                        continue;
                    h->mb.i_sub_partition[i] = subtype;
                    mb_cache_mv_p8x8( h, a, i );
                    if( subtype == btype )
                        continue;
                    cost = x264_rd_cost_part( h, a->i_lambda2, i<<2, PIXEL_8x8 );
                    COPY2_IF_LT( bcost, cost, btype, subtype );
                }
                if( h->mb.i_sub_partition[i] != btype )
                {
                    h->mb.i_sub_partition[i] = btype;
                    mb_cache_mv_p8x8( h, a, i );
                }
            }
        }
        else
            analyse_update_cache( h, a );
        a->l0.i_cost8x8 = rd_cost_mb( h, a->i_lambda2 );
    }
    else
        a->l0.i_cost8x8 = COST_MAX;
}

static void mb_analyse_b_rd( x264_t *h, x264_mb_analysis_t *a, int i_satd_inter )
{
    int thresh = a->b_early_terminate ? i_satd_inter * (17 + (!!h->mb.i_psy_rd))/16 + 1 : COST_MAX;

    if( a->b_direct_available && a->i_rd16x16direct == COST_MAX )
    {
        h->mb.i_type = B_DIRECT;
        /* Assumes direct/skip MC is still in fdec */
        /* Requires b-rdo to be done before intra analysis */
        h->mb.b_skip_mc = 1;
        analyse_update_cache( h, a );
        a->i_rd16x16direct = rd_cost_mb( h, a->i_lambda2 );
        h->mb.b_skip_mc = 0;
    }

    //FIXME not all the update_cache calls are needed
    h->mb.i_partition = D_16x16;
    /* L0 */
    if( a->l0.me16x16.cost < thresh && a->l0.i_rd16x16 == COST_MAX )
    {
        h->mb.i_type = B_L0_L0;
        analyse_update_cache( h, a );
        a->l0.i_rd16x16 = rd_cost_mb( h, a->i_lambda2 );
    }

    /* L1 */
    if( a->l1.me16x16.cost < thresh && a->l1.i_rd16x16 == COST_MAX )
    {
        h->mb.i_type = B_L1_L1;
        analyse_update_cache( h, a );
        a->l1.i_rd16x16 = rd_cost_mb( h, a->i_lambda2 );
    }

    /* BI */
    if( a->i_cost16x16bi < thresh && a->i_rd16x16bi == COST_MAX )
    {
        h->mb.i_type = B_BI_BI;
        analyse_update_cache( h, a );
        a->i_rd16x16bi = rd_cost_mb( h, a->i_lambda2 );
    }

    /* 8x8 */
    if( a->i_cost8x8bi < thresh && a->i_rd8x8bi == COST_MAX )
    {
        h->mb.i_type = B_8x8;
        h->mb.i_partition = D_8x8;
        analyse_update_cache( h, a );
        a->i_rd8x8bi = rd_cost_mb( h, a->i_lambda2 );
        x264_macroblock_cache_skip( h, 0, 0, 4, 4, 0 );
    }

    /* 16x8 */
    if( a->i_cost16x8bi < thresh && a->i_rd16x8bi == COST_MAX )
    {
        h->mb.i_type = a->i_mb_type16x8;
        h->mb.i_partition = D_16x8;
        analyse_update_cache( h, a );
        a->i_rd16x8bi = rd_cost_mb( h, a->i_lambda2 );
    }

    /* 8x16 */
    if( a->i_cost8x16bi < thresh && a->i_rd8x16bi == COST_MAX )
    {
        h->mb.i_type = a->i_mb_type8x16;
        h->mb.i_partition = D_8x16;
        analyse_update_cache( h, a );
        a->i_rd8x16bi = rd_cost_mb( h, a->i_lambda2 );
    }
}

static void refine_bidir( x264_t *h, x264_mb_analysis_t *a )
{
    int i_biweight;

    if( IS_INTRA(h->mb.i_type) )
        return;

    switch( h->mb.i_partition )
    {
        case D_16x16:
            if( h->mb.i_type == B_BI_BI )
            {
                i_biweight = h->mb.bipred_weight[a->l0.bi16x16.i_ref][a->l1.bi16x16.i_ref];
                x264_me_refine_bidir_satd( h, &a->l0.bi16x16, &a->l1.bi16x16, i_biweight );
            }
            break;
        case D_16x8:
            for( int i = 0; i < 2; i++ )
                if( a->i_mb_partition16x8[i] == D_BI_8x8 )
                {
                    i_biweight = h->mb.bipred_weight[a->l0.me16x8[i].i_ref][a->l1.me16x8[i].i_ref];
                    x264_me_refine_bidir_satd( h, &a->l0.me16x8[i], &a->l1.me16x8[i], i_biweight );
                }
            break;
        case D_8x16:
            for( int i = 0; i < 2; i++ )
                if( a->i_mb_partition8x16[i] == D_BI_8x8 )
                {
                    i_biweight = h->mb.bipred_weight[a->l0.me8x16[i].i_ref][a->l1.me8x16[i].i_ref];
                    x264_me_refine_bidir_satd( h, &a->l0.me8x16[i], &a->l1.me8x16[i], i_biweight );
                }
            break;
        case D_8x8:
            for( int i = 0; i < 4; i++ )
                if( h->mb.i_sub_partition[i] == D_BI_8x8 )
                {
                    i_biweight = h->mb.bipred_weight[a->l0.me8x8[i].i_ref][a->l1.me8x8[i].i_ref];
                    x264_me_refine_bidir_satd( h, &a->l0.me8x8[i], &a->l1.me8x8[i], i_biweight );
                }
            break;
    }
}

static inline void mb_analyse_transform( x264_t *h )
{
    if( x264_mb_transform_8x8_allowed( h ) && h->param.analyse.b_transform_8x8 && !h->mb.b_lossless )
    {
        /* Only luma MC is really needed for 4:2:0, but the full MC is re-used in macroblock_encode. */
        x264_mb_mc( h );

        int plane_count = CHROMA444 && h->mb.b_chroma_me ? 3 : 1;
        int i_cost8 = 0, i_cost4 = 0;
        /* Not all platforms have a merged SATD function */
        if( h->pixf.sa8d_satd[PIXEL_16x16] )
        {
            uint64_t cost = 0;
            for( int p = 0; p < plane_count; p++ )
            {
                cost += h->pixf.sa8d_satd[PIXEL_16x16]( h->mb.pic.p_fenc[p], FENC_STRIDE,
                                                        h->mb.pic.p_fdec[p], FDEC_STRIDE );

            }
            i_cost8 = (uint32_t)cost;
            i_cost4 = (uint32_t)(cost >> 32);
        }
        else
        {
            for( int p = 0; p < plane_count; p++ )
            {
                i_cost8 += h->pixf.sa8d[PIXEL_16x16]( h->mb.pic.p_fenc[p], FENC_STRIDE,
                                                      h->mb.pic.p_fdec[p], FDEC_STRIDE );
                i_cost4 += h->pixf.satd[PIXEL_16x16]( h->mb.pic.p_fenc[p], FENC_STRIDE,
                                                      h->mb.pic.p_fdec[p], FDEC_STRIDE );
            }
        }

        h->mb.b_transform_8x8 = i_cost8 < i_cost4;
        if( h->param.i_mobiclip && getenv("MOBI_LUMA8X8_SELECTION_TRACE") )
            fprintf(stderr,"[MOBI8_COST] type=%d cost4=%d cost8=%d natural=%d\n",h->mb.i_type,i_cost4,i_cost8,h->mb.b_transform_8x8);
        if( h->param.i_mobiclip && !IS_INTRA(h->mb.i_type) && getenv("MOBI_LUMA8X8_DIAGNOSTIC_FORCE") && atoi(getenv("MOBI_LUMA8X8_DIAGNOSTIC_FORCE")) )
        { h->mb.b_transform_8x8=1; if(getenv("MOBI_LUMA8X8_SELECTION_TRACE")) fprintf(stderr,"[MOBI8_FORCE] type=%d cost4=%d cost8=%d\n",h->mb.i_type,i_cost4,i_cost8); }
        h->mb.b_skip_mc = 1;
    }
}

static inline void mb_analyse_transform_rd( x264_t *h, x264_mb_analysis_t *a, int *i_satd, int *i_rd )
{
    if( h->param.analyse.b_transform_8x8 && h->pps->b_transform_8x8_mode )
    {
        uint32_t subpart_bak = M32( h->mb.i_sub_partition );
        /* Try switching the subpartitions to 8x8 so that we can use 8x8 transform mode */
        if( h->mb.i_type == P_8x8 )
            M32( h->mb.i_sub_partition ) = D_L0_8x8*0x01010101;
        else if( !x264_transform_allowed[h->mb.i_type] )
            return;

        analyse_update_cache( h, a );
        h->mb.b_transform_8x8 ^= 1;
        /* FIXME only luma is needed for 4:2:0, but the score for comparison already includes chroma */
        int i_rd8 = rd_cost_mb( h, a->i_lambda2 );

        if( *i_rd >= i_rd8 )
        {
            if( *i_rd > 0 )
                *i_satd = (int64_t)(*i_satd) * i_rd8 / *i_rd;
            *i_rd = i_rd8;
        }
        else
        {
            h->mb.b_transform_8x8 ^= 1;
            M32( h->mb.i_sub_partition ) = subpart_bak;
        }
    }
}

/* Rate-distortion optimal QP selection.
 * FIXME: More than half of the benefit of this function seems to be
 * in the way it improves the coding of chroma DC (by decimating or
 * finding a better way to code a single DC coefficient.)
 * There must be a more efficient way to get that portion of the benefit
 * without doing full QP-RD, but RD-decimation doesn't seem to do the
 * trick. */
static inline void mb_analyse_qp_rd( x264_t *h, x264_mb_analysis_t *a )
{
    int bcost, cost, failures, prevcost, origcost;
    int orig_qp = h->mb.i_qp, bqp = h->mb.i_qp;
    int last_qp_tried = 0;
    origcost = bcost = rd_cost_mb( h, a->i_lambda2 );
    int origcbp = h->mb.cbp[h->mb.i_mb_xy];

    /* If CBP is already zero, don't raise the quantizer any higher. */
    for( int direction = origcbp ? 1 : -1; direction >= -1; direction-=2 )
    {
        /* Without psy-RD, require monotonicity when moving quant away from previous
         * macroblock's quant; allow 1 failure when moving quant towards previous quant.
         * With psy-RD, allow 1 failure when moving quant away from previous quant,
         * allow 2 failures when moving quant towards previous quant.
         * Psy-RD generally seems to result in more chaotic RD score-vs-quantizer curves. */
        int threshold = (!!h->mb.i_psy_rd);
        /* Raise the threshold for failures if we're moving towards the last QP. */
        if( ( h->mb.i_last_qp < orig_qp && direction == -1 ) ||
            ( h->mb.i_last_qp > orig_qp && direction ==  1 ) )
            threshold++;
        h->mb.i_qp = orig_qp;
        failures = 0;
        prevcost = origcost;

        /* If the current QP results in an empty CBP, it's highly likely that lower QPs
         * (up to a point) will too.  So, jump down to where the threshold will kick in
         * and check the QP there.  If the CBP is still empty, skip the main loop.
         * If it isn't empty, we would have ended up having to check this QP anyways,
         * so as long as we store it for later lookup, we lose nothing. */
        int already_checked_qp = -1;
        int already_checked_cost = COST_MAX;
        if( direction == -1 )
        {
            if( !origcbp )
            {
                h->mb.i_qp = X264_MAX( h->mb.i_qp - threshold - 1, SPEC_QP( h->param.rc.i_qp_min ) );
                h->mb.i_chroma_qp = h->chroma_qp_table[h->mb.i_qp];
                already_checked_cost = rd_cost_mb( h, a->i_lambda2 );
                if( !h->mb.cbp[h->mb.i_mb_xy] )
                {
                    /* If our empty-CBP block is lower QP than the last QP,
                     * the last QP almost surely doesn't have a CBP either. */
                    if( h->mb.i_last_qp > h->mb.i_qp )
                        last_qp_tried = 1;
                    break;
                }
                already_checked_qp = h->mb.i_qp;
                h->mb.i_qp = orig_qp;
            }
        }

        h->mb.i_qp += direction;
        while( h->mb.i_qp >= h->param.rc.i_qp_min && h->mb.i_qp <= SPEC_QP( h->param.rc.i_qp_max ) )
        {
            if( h->mb.i_last_qp == h->mb.i_qp )
                last_qp_tried = 1;
            if( h->mb.i_qp == already_checked_qp )
                cost = already_checked_cost;
            else
            {
                h->mb.i_chroma_qp = h->chroma_qp_table[h->mb.i_qp];
                cost = rd_cost_mb( h, a->i_lambda2 );
                COPY2_IF_LT( bcost, cost, bqp, h->mb.i_qp );
            }

            /* We can't assume that the costs are monotonic over QPs.
             * Tie case-as-failure seems to give better results. */
            if( cost < prevcost )
                failures = 0;
            else
                failures++;
            prevcost = cost;

            if( failures > threshold )
                break;
            if( direction == 1 && !h->mb.cbp[h->mb.i_mb_xy] )
                break;
            h->mb.i_qp += direction;
        }
    }

    /* Always try the last block's QP. */
    if( !last_qp_tried )
    {
        h->mb.i_qp = h->mb.i_last_qp;
        h->mb.i_chroma_qp = h->chroma_qp_table[h->mb.i_qp];
        cost = rd_cost_mb( h, a->i_lambda2 );
        COPY2_IF_LT( bcost, cost, bqp, h->mb.i_qp );
    }

    h->mb.i_qp = bqp;
    h->mb.i_chroma_qp = h->chroma_qp_table[h->mb.i_qp];

    /* Check transform again; decision from before may no longer be optimal. */
    if( h->mb.i_qp != orig_qp && h->param.analyse.b_transform_8x8 &&
        x264_mb_transform_8x8_allowed( h ) )
    {
        h->mb.b_transform_8x8 ^= 1;
        cost = rd_cost_mb( h, a->i_lambda2 );
        if( cost > bcost )
            h->mb.b_transform_8x8 ^= 1;
    }
}

/*****************************************************************************
 * x264_macroblock_analyse:
 *****************************************************************************/
void x264_macroblock_analyse( x264_t *h )
{
    x264_mb_analysis_t analysis;
    int i_cost = COST_MAX;

    if( mobi_aprof_enabled < 0 && h->param.i_mobiclip )
    {
        const char *opt = getenv( "MOBI_PROFILE" );
        mobi_aprof_enabled = opt && atoi( opt ) != 0;
        if( mobi_aprof_enabled )
            atexit( mobi_aprof_dump );
    }

    h->mb.i_qp = x264_ratecontrol_mb_qp( h );
    /* If the QP of this MB is within 1 of the previous MB, code the same QP as the previous MB,
     * to lower the bit cost of the qp_delta.  Don't do this if QPRD is enabled. */
    if( h->param.rc.i_aq_mode && h->param.analyse.i_subpel_refine < 10 )
        h->mb.i_qp = abs(h->mb.i_qp - h->mb.i_last_qp) == 1 ? h->mb.i_last_qp : h->mb.i_qp;

    if( h->param.analyse.b_mb_info )
        h->fdec->effective_qp[h->mb.i_mb_xy] = h->mb.i_qp; /* Store the real analysis QP. */
    mb_analyse_init( h, &analysis, h->mb.i_qp );

    /*--------------------------- Do the analysis ---------------------------*/
    if( h->sh.i_type == SLICE_TYPE_I )
    {
intra_analysis:
        if( analysis.i_mbrd )
            mb_init_fenc_cache( h, analysis.i_mbrd >= 2 );
        mb_analyse_intra( h, &analysis, COST_MAX );
        if( analysis.i_mbrd )
            intra_rd( h, &analysis, COST_MAX );

        i_cost = analysis.i_satd_i16x16;
        if( h->param.i_mobiclip )
        {
            /* The Mobiclip decoder only supports per-4x4 intra prediction
             * (I_4x4).  I_16x16 / I_8x8 macroblocks are encoded by encode_i_block
             * in a form the decoder cannot parse and desync the whole frame.
             * Always force I_4x4.  (The rebase to upstream x264 dropped this
             * mobiclip constraint, which re-introduced I_16x16 MBs.) */
            h->mb.i_type = I_4x4;
            i_cost = analysis.i_satd_i4x4;
        }
        else
        {
            h->mb.i_type = I_16x16;
            COPY2_IF_LT( i_cost, analysis.i_satd_i4x4, h->mb.i_type, I_4x4 );
            COPY2_IF_LT( i_cost, analysis.i_satd_i8x8, h->mb.i_type, I_8x8 );
            if( analysis.i_satd_pcm < i_cost )
                h->mb.i_type = I_PCM;
        }

        if( analysis.i_mbrd >= 2 )
            intra_rd_refine( h, &analysis );
    }
    else if( h->sh.i_type == SLICE_TYPE_P )
    {
        int b_skip = 0;

        h->mc.prefetch_ref( h->mb.pic.p_fref[0][0][h->mb.i_mb_x&3], h->mb.pic.i_stride[0], 0 );

        analysis.b_try_skip = 0;
        if( analysis.b_force_intra )
        {
            if( !h->param.analyse.b_psy )
            {
                mb_analyse_init_qp( h, &analysis, X264_MAX( h->mb.i_qp - h->mb.ip_offset, h->param.rc.i_qp_min ) );
                goto intra_analysis;
            }
        }
        else
        {
            /* Special fast-skip logic using information from mb_info. */
            if( h->fdec->mb_info && (h->fdec->mb_info[h->mb.i_mb_xy]&X264_MBINFO_CONSTANT) )
            {
                if( !SLICE_MBAFF && (h->fdec->i_frame - h->fref[0][0]->i_frame) == 1 && !h->sh.b_weighted_pred &&
                    h->fref[0][0]->effective_qp[h->mb.i_mb_xy] <= h->mb.i_qp )
                {
                    h->mb.i_partition = D_16x16;
                    /* Use the P-SKIP MV if we can... */
                    if( !M32(h->mb.cache.pskip_mv) )
                    {
                        b_skip = 1;
                        h->mb.i_type = P_SKIP;
                    }
                    /* Otherwise, just force a 16x16 block. */
                    else
                    {
                        h->mb.i_type = P_L0;
                        analysis.l0.me16x16.i_ref = 0;
                        M32( analysis.l0.me16x16.mv ) = 0;
                    }
                    goto skip_analysis;
                }
                /* Reset the information accordingly */
                else if( h->param.analyse.b_mb_info_update )
                    h->fdec->mb_info[h->mb.i_mb_xy] &= ~X264_MBINFO_CONSTANT;
            }

            int skip_invalid = h->i_thread_frames > 1 && h->mb.cache.pskip_mv[1] > h->mb.mv_max_spel[1];
            /* If the current macroblock is off the frame, just skip it. */
            if( HAVE_INTERLACED && !MB_INTERLACED && h->mb.i_mb_y * 16 >= h->param.i_height && !skip_invalid )
                b_skip = 1;
            /* Fast P_SKIP detection */
            else if( h->param.analyse.b_fast_pskip )
            {
                if( skip_invalid )
                    // FIXME don't need to check this if the reference frame is done
                    {}
                else if( h->param.analyse.i_subpel_refine >= 3 )
                    analysis.b_try_skip = 1;
                else if( h->mb.i_mb_type_left[0] == P_SKIP ||
                         h->mb.i_mb_type_top == P_SKIP ||
                         h->mb.i_mb_type_topleft == P_SKIP ||
                         h->mb.i_mb_type_topright == P_SKIP )
                    b_skip = x264_macroblock_probe_pskip( h );
            }
        }

        h->mc.prefetch_ref( h->mb.pic.p_fref[0][0][h->mb.i_mb_x&3], h->mb.pic.i_stride[0], 1 );

        if( b_skip )
        {
            h->mb.i_type = P_SKIP;
            h->mb.i_partition = D_16x16;
            assert( h->mb.cache.pskip_mv[1] <= h->mb.mv_max_spel[1] || h->i_thread_frames == 1 );
skip_analysis:
            /* Set up MVs for future predictors */
            for( int i = 0; i < h->mb.pic.i_fref[0]; i++ )
                M32( h->mb.mvr[0][i][h->mb.i_mb_xy] ) = 0;
        }
        else
        {
            const unsigned int flags = h->param.analyse.inter;
            int i_type;
            int i_partition;
            int i_satd_inter, i_satd_intra;

            mb_analyse_load_costs( h, &analysis );

            MOBI_APROF( 0, mb_analyse_inter_p16x16( h, &analysis ) );

            if( h->mb.i_type == P_SKIP )
            {
                for( int i = 1; i < h->mb.pic.i_fref[0]; i++ )
                    M32( h->mb.mvr[0][i][h->mb.i_mb_xy] ) = 0;
                return;
            }

            if( flags & X264_ANALYSE_PSUB16x16 )
            {
                if( h->param.analyse.b_mixed_references )
                    MOBI_APROF( 1, mb_analyse_inter_p8x8_mixed_ref( h, &analysis ) );
                else
                    MOBI_APROF( 1, mb_analyse_inter_p8x8( h, &analysis ) );
            }

            /* Select best inter mode */
            i_type = P_L0;
            i_partition = D_16x16;
            i_cost = analysis.l0.me16x16.cost;

            if( ( flags & X264_ANALYSE_PSUB16x16 ) && (!analysis.b_early_terminate ||
                analysis.l0.i_cost8x8 < analysis.l0.me16x16.cost) )
            {
                i_type = P_8x8;
                i_partition = D_8x8;
                i_cost = analysis.l0.i_cost8x8;

                /* Do sub 8x8 */
                if( flags & X264_ANALYSE_PSUB8x8 )
                {
                    uint64_t mobi_sub_start = mobi_aprof_enabled == 1 ? mobi_aprof_tick() : 0;
                    for( int i = 0; i < 4; i++ )
                    {
                        mb_analyse_inter_p4x4( h, &analysis, i );
                        int i_thresh8x4 = analysis.l0.me4x4[i][1].cost_mv + analysis.l0.me4x4[i][2].cost_mv;
                        if( !analysis.b_early_terminate || analysis.l0.i_cost4x4[i] < analysis.l0.me8x8[i].cost + i_thresh8x4 )
                        {
                            int i_cost8x8 = analysis.l0.i_cost4x4[i];
                            h->mb.i_sub_partition[i] = D_L0_4x4;

                            mb_analyse_inter_p8x4( h, &analysis, i );
                            COPY2_IF_LT( i_cost8x8, analysis.l0.i_cost8x4[i],
                                         h->mb.i_sub_partition[i], D_L0_8x4 );

                            mb_analyse_inter_p4x8( h, &analysis, i );
                            COPY2_IF_LT( i_cost8x8, analysis.l0.i_cost4x8[i],
                                         h->mb.i_sub_partition[i], D_L0_4x8 );

                            i_cost += i_cost8x8 - analysis.l0.me8x8[i].cost;
                        }
                        mb_cache_mv_p8x8( h, &analysis, i );
                    }
                    if( mobi_aprof_enabled == 1 )
                    {
                        mobi_aprof_ns[2] += mobi_aprof_tick() - mobi_sub_start;
                        mobi_aprof_calls[2]++;
                    }
                    analysis.l0.i_cost8x8 = i_cost;
                }
            }

            /* Now do 16x8/8x16 */
            int i_thresh16x8 = analysis.l0.me8x8[1].cost_mv + analysis.l0.me8x8[2].cost_mv;
            if( ( flags & X264_ANALYSE_PSUB16x16 ) && (!analysis.b_early_terminate ||
                analysis.l0.i_cost8x8 < analysis.l0.me16x16.cost + i_thresh16x8) )
            {
                int i_avg_mv_ref_cost = (analysis.l0.me8x8[2].cost_mv + analysis.l0.me8x8[2].i_ref_cost
                                      + analysis.l0.me8x8[3].cost_mv + analysis.l0.me8x8[3].i_ref_cost + 1) >> 1;
                analysis.i_cost_est16x8[1] = analysis.i_satd8x8[0][2] + analysis.i_satd8x8[0][3] + i_avg_mv_ref_cost;

                MOBI_APROF( 3, mb_analyse_inter_p16x8( h, &analysis, i_cost ) );
                COPY3_IF_LT( i_cost, analysis.l0.i_cost16x8, i_type, P_L0, i_partition, D_16x8 );

                i_avg_mv_ref_cost = (analysis.l0.me8x8[1].cost_mv + analysis.l0.me8x8[1].i_ref_cost
                                  + analysis.l0.me8x8[3].cost_mv + analysis.l0.me8x8[3].i_ref_cost + 1) >> 1;
                analysis.i_cost_est8x16[1] = analysis.i_satd8x8[0][1] + analysis.i_satd8x8[0][3] + i_avg_mv_ref_cost;

                MOBI_APROF( 4, mb_analyse_inter_p8x16( h, &analysis, i_cost ) );
                COPY3_IF_LT( i_cost, analysis.l0.i_cost8x16, i_type, P_L0, i_partition, D_8x16 );
            }

            h->mb.i_partition = i_partition;

            /* refine qpel */
            //FIXME mb_type costs?
            if( analysis.i_mbrd || !h->mb.i_subpel_refine )
            {
                /* refine later */
            }
            else if( i_partition == D_16x16 )
            {
                x264_me_refine_qpel( h, &analysis.l0.me16x16 );
                i_cost = analysis.l0.me16x16.cost;
            }
            else if( i_partition == D_16x8 )
            {
                x264_me_refine_qpel( h, &analysis.l0.me16x8[0] );
                x264_me_refine_qpel( h, &analysis.l0.me16x8[1] );
                i_cost = analysis.l0.me16x8[0].cost + analysis.l0.me16x8[1].cost;
            }
            else if( i_partition == D_8x16 )
            {
                x264_me_refine_qpel( h, &analysis.l0.me8x16[0] );
                x264_me_refine_qpel( h, &analysis.l0.me8x16[1] );
                i_cost = analysis.l0.me8x16[0].cost + analysis.l0.me8x16[1].cost;
            }
            else if( i_partition == D_8x8 )
            {
                i_cost = 0;
                for( int i8x8 = 0; i8x8 < 4; i8x8++ )
                {
                    switch( h->mb.i_sub_partition[i8x8] )
                    {
                        case D_L0_8x8:
                            x264_me_refine_qpel( h, &analysis.l0.me8x8[i8x8] );
                            i_cost += analysis.l0.me8x8[i8x8].cost;
                            break;
                        case D_L0_8x4:
                            x264_me_refine_qpel( h, &analysis.l0.me8x4[i8x8][0] );
                            x264_me_refine_qpel( h, &analysis.l0.me8x4[i8x8][1] );
                            i_cost += analysis.l0.me8x4[i8x8][0].cost +
                                      analysis.l0.me8x4[i8x8][1].cost;
                            break;
                        case D_L0_4x8:
                            x264_me_refine_qpel( h, &analysis.l0.me4x8[i8x8][0] );
                            x264_me_refine_qpel( h, &analysis.l0.me4x8[i8x8][1] );
                            i_cost += analysis.l0.me4x8[i8x8][0].cost +
                                      analysis.l0.me4x8[i8x8][1].cost;
                            break;

                        case D_L0_4x4:
                            x264_me_refine_qpel( h, &analysis.l0.me4x4[i8x8][0] );
                            x264_me_refine_qpel( h, &analysis.l0.me4x4[i8x8][1] );
                            x264_me_refine_qpel( h, &analysis.l0.me4x4[i8x8][2] );
                            x264_me_refine_qpel( h, &analysis.l0.me4x4[i8x8][3] );
                            i_cost += analysis.l0.me4x4[i8x8][0].cost +
                                      analysis.l0.me4x4[i8x8][1].cost +
                                      analysis.l0.me4x4[i8x8][2].cost +
                                      analysis.l0.me4x4[i8x8][3].cost;
                            break;
                        default:
                            x264_log( h, X264_LOG_ERROR, "internal error (!8x8 && !4x4)\n" );
                            break;
                    }
                }
            }

            if( h->mb.b_chroma_me )
            {
                if( CHROMA444 )
                {
                    MOBI_APROF( 5, mb_analyse_intra( h, &analysis, i_cost ) );
                    mb_analyse_intra_chroma( h, &analysis );
                }
                else
                {
                    mb_analyse_intra_chroma( h, &analysis );
                    MOBI_APROF( 5, mb_analyse_intra( h, &analysis, i_cost - analysis.i_satd_chroma ) );
                }
                analysis.i_satd_i16x16 += analysis.i_satd_chroma;
                analysis.i_satd_i8x8   += analysis.i_satd_chroma;
                analysis.i_satd_i4x4   += analysis.i_satd_chroma;
            }
            else
                MOBI_APROF( 5, mb_analyse_intra( h, &analysis, i_cost ) );

            i_satd_inter = i_cost;
            i_satd_intra = X264_MIN3( analysis.i_satd_i16x16,
                                      analysis.i_satd_i8x8,
                                      analysis.i_satd_i4x4 );

            if( analysis.i_mbrd )
            {
                MOBI_APROF( 6, mb_analyse_p_rd( h, &analysis, X264_MIN(i_satd_inter, i_satd_intra) ) );
                i_type = P_L0;
                i_partition = D_16x16;
                i_cost = analysis.l0.i_rd16x16;
                COPY2_IF_LT( i_cost, analysis.l0.i_cost16x8, i_partition, D_16x8 );
                COPY2_IF_LT( i_cost, analysis.l0.i_cost8x16, i_partition, D_8x16 );
                COPY3_IF_LT( i_cost, analysis.l0.i_cost8x8, i_partition, D_8x8, i_type, P_8x8 );
                h->mb.i_type = i_type;
                h->mb.i_partition = i_partition;
                if( i_cost < COST_MAX )
                    mb_analyse_transform_rd( h, &analysis, &i_satd_inter, &i_cost );
                MOBI_APROF( 7, intra_rd( h, &analysis, i_satd_inter * 5/4 + 1 ) );
            }

            /* Mobiclip: only I_4x4 intra is supported (see intra_analysis). */
            if( h->param.i_mobiclip )
            {
                COPY2_IF_LT( i_cost, analysis.i_satd_i4x4, i_type, I_4x4 );
            }
            else
            {
                COPY2_IF_LT( i_cost, analysis.i_satd_i16x16, i_type, I_16x16 );
                COPY2_IF_LT( i_cost, analysis.i_satd_i8x8, i_type, I_8x8 );
                COPY2_IF_LT( i_cost, analysis.i_satd_i4x4, i_type, I_4x4 );
                COPY2_IF_LT( i_cost, analysis.i_satd_pcm, i_type, I_PCM );
            }

            h->mb.i_type = i_type;

            if( analysis.b_force_intra && !IS_INTRA(i_type) )
            {
                /* Intra masking: copy fdec to fenc and re-encode the block as intra in order to make it appear as if
                 * it was an inter block. */
                analyse_update_cache( h, &analysis );
                x264_macroblock_encode( h );
                for( int p = 0; p < (CHROMA444 ? 3 : 1); p++ )
                    h->mc.copy[PIXEL_16x16]( h->mb.pic.p_fenc[p], FENC_STRIDE, h->mb.pic.p_fdec[p], FDEC_STRIDE, 16 );
                if( !CHROMA444 )
                {
                    int height = 16 >> CHROMA_V_SHIFT;
                    h->mc.copy[PIXEL_8x8]  ( h->mb.pic.p_fenc[1], FENC_STRIDE, h->mb.pic.p_fdec[1], FDEC_STRIDE, height );
                    h->mc.copy[PIXEL_8x8]  ( h->mb.pic.p_fenc[2], FENC_STRIDE, h->mb.pic.p_fdec[2], FDEC_STRIDE, height );
                }
                mb_analyse_init_qp( h, &analysis, X264_MAX( h->mb.i_qp - h->mb.ip_offset, h->param.rc.i_qp_min ) );
                goto intra_analysis;
            }

            uint64_t mobi_rd_start = mobi_aprof_enabled == 1 ? mobi_aprof_tick() : 0;
            if( analysis.i_mbrd >= 2 && h->mb.i_type != I_PCM )
            {
                if( IS_INTRA( h->mb.i_type ) )
                {
                    MOBI_APROF( 9, intra_rd_refine( h, &analysis ) );
                }
                else if( i_partition == D_16x16 )
                {
                    x264_macroblock_cache_ref( h, 0, 0, 4, 4, 0, analysis.l0.me16x16.i_ref );
                    analysis.l0.me16x16.cost = i_cost;
                    MOBI_APROF( 10, x264_me_refine_qpel_rd( h, &analysis.l0.me16x16, analysis.i_lambda2, 0, 0 ) );
                }
                else if( i_partition == D_16x8 )
                {
                    M32( h->mb.i_sub_partition ) = D_L0_8x8 * 0x01010101;
                    x264_macroblock_cache_ref( h, 0, 0, 4, 2, 0, analysis.l0.me16x8[0].i_ref );
                    x264_macroblock_cache_ref( h, 0, 2, 4, 2, 0, analysis.l0.me16x8[1].i_ref );
                    x264_me_refine_qpel_rd( h, &analysis.l0.me16x8[0], analysis.i_lambda2, 0, 0 );
                    x264_me_refine_qpel_rd( h, &analysis.l0.me16x8[1], analysis.i_lambda2, 8, 0 );
                }
                else if( i_partition == D_8x16 )
                {
                    M32( h->mb.i_sub_partition ) = D_L0_8x8 * 0x01010101;
                    x264_macroblock_cache_ref( h, 0, 0, 2, 4, 0, analysis.l0.me8x16[0].i_ref );
                    x264_macroblock_cache_ref( h, 2, 0, 2, 4, 0, analysis.l0.me8x16[1].i_ref );
                    x264_me_refine_qpel_rd( h, &analysis.l0.me8x16[0], analysis.i_lambda2, 0, 0 );
                    x264_me_refine_qpel_rd( h, &analysis.l0.me8x16[1], analysis.i_lambda2, 4, 0 );
                }
                else if( i_partition == D_8x8 )
                {
                    analyse_update_cache( h, &analysis );
                    for( int i8x8 = 0; i8x8 < 4; i8x8++ )
                    {
                        if( h->mb.i_sub_partition[i8x8] == D_L0_8x8 )
                        {
                            x264_me_refine_qpel_rd( h, &analysis.l0.me8x8[i8x8], analysis.i_lambda2, i8x8*4, 0 );
                        }
                        else if( h->mb.i_sub_partition[i8x8] == D_L0_8x4 )
                        {
                            x264_me_refine_qpel_rd( h, &analysis.l0.me8x4[i8x8][0], analysis.i_lambda2, i8x8*4+0, 0 );
                            x264_me_refine_qpel_rd( h, &analysis.l0.me8x4[i8x8][1], analysis.i_lambda2, i8x8*4+2, 0 );
                        }
                        else if( h->mb.i_sub_partition[i8x8] == D_L0_4x8 )
                        {
                            x264_me_refine_qpel_rd( h, &analysis.l0.me4x8[i8x8][0], analysis.i_lambda2, i8x8*4+0, 0 );
                            x264_me_refine_qpel_rd( h, &analysis.l0.me4x8[i8x8][1], analysis.i_lambda2, i8x8*4+1, 0 );
                        }
                        else if( h->mb.i_sub_partition[i8x8] == D_L0_4x4 )
                        {
                            x264_me_refine_qpel_rd( h, &analysis.l0.me4x4[i8x8][0], analysis.i_lambda2, i8x8*4+0, 0 );
                            x264_me_refine_qpel_rd( h, &analysis.l0.me4x4[i8x8][1], analysis.i_lambda2, i8x8*4+1, 0 );
                            x264_me_refine_qpel_rd( h, &analysis.l0.me4x4[i8x8][2], analysis.i_lambda2, i8x8*4+2, 0 );
                            x264_me_refine_qpel_rd( h, &analysis.l0.me4x4[i8x8][3], analysis.i_lambda2, i8x8*4+3, 0 );
                        }
                    }
                }
            }
            if( mobi_aprof_enabled == 1 )
            {
                mobi_aprof_ns[8] += mobi_aprof_tick() - mobi_rd_start;
                mobi_aprof_calls[8]++;
            }
        }
    }
    else if( h->sh.i_type == SLICE_TYPE_B )
    {
        int i_bskip_cost = COST_MAX;
        int b_skip = 0;

        if( analysis.i_mbrd )
            mb_init_fenc_cache( h, analysis.i_mbrd >= 2 );

        h->mb.i_type = B_SKIP;
        if( h->mb.b_direct_auto_write )
        {
            /* direct=auto heuristic: prefer whichever mode allows more Skip macroblocks */
            for( int i = 0; i < 2; i++ )
            {
                int b_changed = 1;
                h->sh.b_direct_spatial_mv_pred ^= 1;
                analysis.b_direct_available = x264_mb_predict_mv_direct16x16( h, i && analysis.b_direct_available ? &b_changed : NULL );
                if( analysis.b_direct_available )
                {
                    if( b_changed )
                    {
                        x264_mb_mc( h );
                        b_skip = x264_macroblock_probe_bskip( h );
                    }
                    h->stat.frame.i_direct_score[ h->sh.b_direct_spatial_mv_pred ] += b_skip;
                }
                else
                    b_skip = 0;
            }
        }
        else
            analysis.b_direct_available = x264_mb_predict_mv_direct16x16( h, NULL );

        analysis.b_try_skip = 0;
        if( analysis.b_direct_available )
        {
            if( !h->mb.b_direct_auto_write )
                x264_mb_mc( h );
            /* If the current macroblock is off the frame, just skip it. */
            if( HAVE_INTERLACED && !MB_INTERLACED && h->mb.i_mb_y * 16 >= h->param.i_height )
                b_skip = 1;
            else if( analysis.i_mbrd )
            {
                i_bskip_cost = ssd_mb( h );
                /* 6 = minimum cavlc cost of a non-skipped MB */
                b_skip = h->mb.b_skip_mc = i_bskip_cost <= ((6 * analysis.i_lambda2 + 128) >> 8);
            }
            else if( !h->mb.b_direct_auto_write )
            {
                /* Conditioning the probe on neighboring block types
                 * doesn't seem to help speed or quality. */
                analysis.b_try_skip = x264_macroblock_probe_bskip( h );
                if( h->param.analyse.i_subpel_refine < 3 )
                    b_skip = analysis.b_try_skip;
            }
            /* Set up MVs for future predictors */
            if( b_skip )
            {
                for( int i = 0; i < h->mb.pic.i_fref[0]; i++ )
                    M32( h->mb.mvr[0][i][h->mb.i_mb_xy] ) = 0;
                for( int i = 0; i < h->mb.pic.i_fref[1]; i++ )
                    M32( h->mb.mvr[1][i][h->mb.i_mb_xy] ) = 0;
            }
        }

        if( !b_skip )
        {
            const unsigned int flags = h->param.analyse.inter;
            int i_type;
            int i_partition;
            int i_satd_inter;
            h->mb.b_skip_mc = 0;
            h->mb.i_type = B_DIRECT;

            mb_analyse_load_costs( h, &analysis );

            /* select best inter mode */
            /* direct must be first */
            if( analysis.b_direct_available )
                mb_analyse_inter_direct( h, &analysis );

            mb_analyse_inter_b16x16( h, &analysis );

            if( h->mb.i_type == B_SKIP )
            {
                for( int i = 1; i < h->mb.pic.i_fref[0]; i++ )
                    M32( h->mb.mvr[0][i][h->mb.i_mb_xy] ) = 0;
                for( int i = 1; i < h->mb.pic.i_fref[1]; i++ )
                    M32( h->mb.mvr[1][i][h->mb.i_mb_xy] ) = 0;
                return;
            }

            i_type = B_L0_L0;
            i_partition = D_16x16;
            i_cost = analysis.l0.me16x16.cost;
            COPY2_IF_LT( i_cost, analysis.l1.me16x16.cost, i_type, B_L1_L1 );
            COPY2_IF_LT( i_cost, analysis.i_cost16x16bi, i_type, B_BI_BI );
            COPY2_IF_LT( i_cost, analysis.i_cost16x16direct, i_type, B_DIRECT );

            if( analysis.i_mbrd && analysis.b_early_terminate && analysis.i_cost16x16direct <= i_cost * 33/32 )
            {
                mb_analyse_b_rd( h, &analysis, i_cost );
                if( i_bskip_cost < analysis.i_rd16x16direct &&
                    i_bskip_cost < analysis.i_rd16x16bi &&
                    i_bskip_cost < analysis.l0.i_rd16x16 &&
                    i_bskip_cost < analysis.l1.i_rd16x16 )
                {
                    h->mb.i_type = B_SKIP;
                    analyse_update_cache( h, &analysis );
                    return;
                }
            }

            if( flags & X264_ANALYSE_BSUB16x16 )
            {
                if( h->param.analyse.b_mixed_references )
                    mb_analyse_inter_b8x8_mixed_ref( h, &analysis );
                else
                    mb_analyse_inter_b8x8( h, &analysis );

                COPY3_IF_LT( i_cost, analysis.i_cost8x8bi, i_type, B_8x8, i_partition, D_8x8 );

                /* Try to estimate the cost of b16x8/b8x16 based on the satd scores of the b8x8 modes */
                int i_cost_est16x8bi_total = 0, i_cost_est8x16bi_total = 0;
                int i_mb_type, i_partition16x8[2], i_partition8x16[2];
                for( int i = 0; i < 2; i++ )
                {
                    int avg_l0_mv_ref_cost, avg_l1_mv_ref_cost;
                    int i_l0_satd, i_l1_satd, i_bi_satd, i_best_cost;
                    // 16x8
                    i_best_cost = COST_MAX;
                    i_l0_satd = analysis.i_satd8x8[0][i*2] + analysis.i_satd8x8[0][i*2+1];
                    i_l1_satd = analysis.i_satd8x8[1][i*2] + analysis.i_satd8x8[1][i*2+1];
                    i_bi_satd = analysis.i_satd8x8[2][i*2] + analysis.i_satd8x8[2][i*2+1];
                    avg_l0_mv_ref_cost = ( analysis.l0.me8x8[i*2].cost_mv + analysis.l0.me8x8[i*2].i_ref_cost
                                         + analysis.l0.me8x8[i*2+1].cost_mv + analysis.l0.me8x8[i*2+1].i_ref_cost + 1 ) >> 1;
                    avg_l1_mv_ref_cost = ( analysis.l1.me8x8[i*2].cost_mv + analysis.l1.me8x8[i*2].i_ref_cost
                                         + analysis.l1.me8x8[i*2+1].cost_mv + analysis.l1.me8x8[i*2+1].i_ref_cost + 1 ) >> 1;
                    COPY2_IF_LT( i_best_cost, i_l0_satd + avg_l0_mv_ref_cost, i_partition16x8[i], D_L0_8x8 );
                    COPY2_IF_LT( i_best_cost, i_l1_satd + avg_l1_mv_ref_cost, i_partition16x8[i], D_L1_8x8 );
                    COPY2_IF_LT( i_best_cost, i_bi_satd + avg_l0_mv_ref_cost + avg_l1_mv_ref_cost, i_partition16x8[i], D_BI_8x8 );
                    analysis.i_cost_est16x8[i] = i_best_cost;

                    // 8x16
                    i_best_cost = COST_MAX;
                    i_l0_satd = analysis.i_satd8x8[0][i] + analysis.i_satd8x8[0][i+2];
                    i_l1_satd = analysis.i_satd8x8[1][i] + analysis.i_satd8x8[1][i+2];
                    i_bi_satd = analysis.i_satd8x8[2][i] + analysis.i_satd8x8[2][i+2];
                    avg_l0_mv_ref_cost = ( analysis.l0.me8x8[i].cost_mv + analysis.l0.me8x8[i].i_ref_cost
                                         + analysis.l0.me8x8[i+2].cost_mv + analysis.l0.me8x8[i+2].i_ref_cost + 1 ) >> 1;
                    avg_l1_mv_ref_cost = ( analysis.l1.me8x8[i].cost_mv + analysis.l1.me8x8[i].i_ref_cost
                                         + analysis.l1.me8x8[i+2].cost_mv + analysis.l1.me8x8[i+2].i_ref_cost + 1 ) >> 1;
                    COPY2_IF_LT( i_best_cost, i_l0_satd + avg_l0_mv_ref_cost, i_partition8x16[i], D_L0_8x8 );
                    COPY2_IF_LT( i_best_cost, i_l1_satd + avg_l1_mv_ref_cost, i_partition8x16[i], D_L1_8x8 );
                    COPY2_IF_LT( i_best_cost, i_bi_satd + avg_l0_mv_ref_cost + avg_l1_mv_ref_cost, i_partition8x16[i], D_BI_8x8 );
                    analysis.i_cost_est8x16[i] = i_best_cost;
                }
                i_mb_type = B_L0_L0 + (i_partition16x8[0]>>2) * 3 + (i_partition16x8[1]>>2);
                analysis.i_cost_est16x8[1] += analysis.i_lambda * i_mb_b16x8_cost_table[i_mb_type];
                i_cost_est16x8bi_total = analysis.i_cost_est16x8[0] + analysis.i_cost_est16x8[1];
                i_mb_type = B_L0_L0 + (i_partition8x16[0]>>2) * 3 + (i_partition8x16[1]>>2);
                analysis.i_cost_est8x16[1] += analysis.i_lambda * i_mb_b16x8_cost_table[i_mb_type];
                i_cost_est8x16bi_total = analysis.i_cost_est8x16[0] + analysis.i_cost_est8x16[1];

                /* We can gain a little speed by checking the mode with the lowest estimated cost first */
                int try_16x8_first = i_cost_est16x8bi_total < i_cost_est8x16bi_total;
                if( try_16x8_first && (!analysis.b_early_terminate || i_cost_est16x8bi_total < i_cost) )
                {
                    mb_analyse_inter_b16x8( h, &analysis, i_cost );
                    COPY3_IF_LT( i_cost, analysis.i_cost16x8bi, i_type, analysis.i_mb_type16x8, i_partition, D_16x8 );
                }
                if( !analysis.b_early_terminate || i_cost_est8x16bi_total < i_cost )
                {
                    mb_analyse_inter_b8x16( h, &analysis, i_cost );
                    COPY3_IF_LT( i_cost, analysis.i_cost8x16bi, i_type, analysis.i_mb_type8x16, i_partition, D_8x16 );
                }
                if( !try_16x8_first && (!analysis.b_early_terminate || i_cost_est16x8bi_total < i_cost) )
                {
                    mb_analyse_inter_b16x8( h, &analysis, i_cost );
                    COPY3_IF_LT( i_cost, analysis.i_cost16x8bi, i_type, analysis.i_mb_type16x8, i_partition, D_16x8 );
                }
            }

            if( analysis.i_mbrd || !h->mb.i_subpel_refine )
            {
                /* refine later */
            }
            /* refine qpel */
            else if( i_partition == D_16x16 )
            {
                analysis.l0.me16x16.cost -= analysis.i_lambda * i_mb_b_cost_table[B_L0_L0];
                analysis.l1.me16x16.cost -= analysis.i_lambda * i_mb_b_cost_table[B_L1_L1];
                if( i_type == B_L0_L0 )
                {
                    x264_me_refine_qpel( h, &analysis.l0.me16x16 );
                    i_cost = analysis.l0.me16x16.cost
                           + analysis.i_lambda * i_mb_b_cost_table[B_L0_L0];
                }
                else if( i_type == B_L1_L1 )
                {
                    x264_me_refine_qpel( h, &analysis.l1.me16x16 );
                    i_cost = analysis.l1.me16x16.cost
                           + analysis.i_lambda * i_mb_b_cost_table[B_L1_L1];
                }
                else if( i_type == B_BI_BI )
                {
                    x264_me_refine_qpel( h, &analysis.l0.bi16x16 );
                    x264_me_refine_qpel( h, &analysis.l1.bi16x16 );
                }
            }
            else if( i_partition == D_16x8 )
            {
                for( int i = 0; i < 2; i++ )
                {
                    if( analysis.i_mb_partition16x8[i] != D_L1_8x8 )
                        x264_me_refine_qpel( h, &analysis.l0.me16x8[i] );
                    if( analysis.i_mb_partition16x8[i] != D_L0_8x8 )
                        x264_me_refine_qpel( h, &analysis.l1.me16x8[i] );
                }
            }
            else if( i_partition == D_8x16 )
            {
                for( int i = 0; i < 2; i++ )
                {
                    if( analysis.i_mb_partition8x16[i] != D_L1_8x8 )
                        x264_me_refine_qpel( h, &analysis.l0.me8x16[i] );
                    if( analysis.i_mb_partition8x16[i] != D_L0_8x8 )
                        x264_me_refine_qpel( h, &analysis.l1.me8x16[i] );
                }
            }
            else if( i_partition == D_8x8 )
            {
                for( int i = 0; i < 4; i++ )
                {
                    x264_me_t *m;
                    int i_part_cost_old;
                    int i_type_cost;
                    int i_part_type = h->mb.i_sub_partition[i];
                    int b_bidir = (i_part_type == D_BI_8x8);

                    if( i_part_type == D_DIRECT_8x8 )
                        continue;
                    if( x264_mb_partition_listX_table[0][i_part_type] )
                    {
                        m = &analysis.l0.me8x8[i];
                        i_part_cost_old = m->cost;
                        i_type_cost = analysis.i_lambda * i_sub_mb_b_cost_table[D_L0_8x8];
                        m->cost -= i_type_cost;
                        x264_me_refine_qpel( h, m );
                        if( !b_bidir )
                            analysis.i_cost8x8bi += m->cost + i_type_cost - i_part_cost_old;
                    }
                    if( x264_mb_partition_listX_table[1][i_part_type] )
                    {
                        m = &analysis.l1.me8x8[i];
                        i_part_cost_old = m->cost;
                        i_type_cost = analysis.i_lambda * i_sub_mb_b_cost_table[D_L1_8x8];
                        m->cost -= i_type_cost;
                        x264_me_refine_qpel( h, m );
                        if( !b_bidir )
                            analysis.i_cost8x8bi += m->cost + i_type_cost - i_part_cost_old;
                    }
                    /* TODO: update mvp? */
                }
            }

            i_satd_inter = i_cost;

            if( analysis.i_mbrd )
            {
                mb_analyse_b_rd( h, &analysis, i_satd_inter );
                i_type = B_SKIP;
                i_cost = i_bskip_cost;
                i_partition = D_16x16;
                COPY2_IF_LT( i_cost, analysis.l0.i_rd16x16, i_type, B_L0_L0 );
                COPY2_IF_LT( i_cost, analysis.l1.i_rd16x16, i_type, B_L1_L1 );
                COPY2_IF_LT( i_cost, analysis.i_rd16x16bi, i_type, B_BI_BI );
                COPY2_IF_LT( i_cost, analysis.i_rd16x16direct, i_type, B_DIRECT );
                COPY3_IF_LT( i_cost, analysis.i_rd16x8bi, i_type, analysis.i_mb_type16x8, i_partition, D_16x8 );
                COPY3_IF_LT( i_cost, analysis.i_rd8x16bi, i_type, analysis.i_mb_type8x16, i_partition, D_8x16 );
                COPY3_IF_LT( i_cost, analysis.i_rd8x8bi, i_type, B_8x8, i_partition, D_8x8 );

                h->mb.i_type = i_type;
                h->mb.i_partition = i_partition;
            }

            if( h->mb.b_chroma_me )
            {
                if( CHROMA444 )
                {
                    mb_analyse_intra( h, &analysis, i_satd_inter );
                    mb_analyse_intra_chroma( h, &analysis );
                }
                else
                {
                    mb_analyse_intra_chroma( h, &analysis );
                    mb_analyse_intra( h, &analysis, i_satd_inter - analysis.i_satd_chroma );
                }
                analysis.i_satd_i16x16 += analysis.i_satd_chroma;
                analysis.i_satd_i8x8   += analysis.i_satd_chroma;
                analysis.i_satd_i4x4   += analysis.i_satd_chroma;
            }
            else
                mb_analyse_intra( h, &analysis, i_satd_inter );

            if( analysis.i_mbrd )
            {
                mb_analyse_transform_rd( h, &analysis, &i_satd_inter, &i_cost );
                intra_rd( h, &analysis, i_satd_inter * 17/16 + 1 );
            }

            /* Mobiclip: only I_4x4 intra is supported (see intra_analysis). */
            if( h->param.i_mobiclip )
            {
                COPY2_IF_LT( i_cost, analysis.i_satd_i4x4, i_type, I_4x4 );
            }
            else
            {
                COPY2_IF_LT( i_cost, analysis.i_satd_i16x16, i_type, I_16x16 );
                COPY2_IF_LT( i_cost, analysis.i_satd_i8x8, i_type, I_8x8 );
                COPY2_IF_LT( i_cost, analysis.i_satd_i4x4, i_type, I_4x4 );
                COPY2_IF_LT( i_cost, analysis.i_satd_pcm, i_type, I_PCM );
            }

            h->mb.i_type = i_type;
            h->mb.i_partition = i_partition;

            if( analysis.i_mbrd >= 2 && IS_INTRA( i_type ) && i_type != I_PCM )
                intra_rd_refine( h, &analysis );
            if( h->mb.i_subpel_refine >= 5 )
                refine_bidir( h, &analysis );

            if( analysis.i_mbrd >= 2 && i_type > B_DIRECT && i_type < B_SKIP )
            {
                int i_biweight;
                analyse_update_cache( h, &analysis );

                if( i_partition == D_16x16 )
                {
                    if( i_type == B_L0_L0 )
                    {
                        analysis.l0.me16x16.cost = i_cost;
                        x264_me_refine_qpel_rd( h, &analysis.l0.me16x16, analysis.i_lambda2, 0, 0 );
                    }
                    else if( i_type == B_L1_L1 )
                    {
                        analysis.l1.me16x16.cost = i_cost;
                        x264_me_refine_qpel_rd( h, &analysis.l1.me16x16, analysis.i_lambda2, 0, 1 );
                    }
                    else if( i_type == B_BI_BI )
                    {
                        i_biweight = h->mb.bipred_weight[analysis.l0.bi16x16.i_ref][analysis.l1.bi16x16.i_ref];
                        x264_me_refine_bidir_rd( h, &analysis.l0.bi16x16, &analysis.l1.bi16x16, i_biweight, 0, analysis.i_lambda2 );
                    }
                }
                else if( i_partition == D_16x8 )
                {
                    for( int i = 0; i < 2; i++ )
                    {
                        h->mb.i_sub_partition[i*2] = h->mb.i_sub_partition[i*2+1] = analysis.i_mb_partition16x8[i];
                        if( analysis.i_mb_partition16x8[i] == D_L0_8x8 )
                            x264_me_refine_qpel_rd( h, &analysis.l0.me16x8[i], analysis.i_lambda2, i*8, 0 );
                        else if( analysis.i_mb_partition16x8[i] == D_L1_8x8 )
                            x264_me_refine_qpel_rd( h, &analysis.l1.me16x8[i], analysis.i_lambda2, i*8, 1 );
                        else if( analysis.i_mb_partition16x8[i] == D_BI_8x8 )
                        {
                            i_biweight = h->mb.bipred_weight[analysis.l0.me16x8[i].i_ref][analysis.l1.me16x8[i].i_ref];
                            x264_me_refine_bidir_rd( h, &analysis.l0.me16x8[i], &analysis.l1.me16x8[i], i_biweight, i*2, analysis.i_lambda2 );
                        }
                    }
                }
                else if( i_partition == D_8x16 )
                {
                    for( int i = 0; i < 2; i++ )
                    {
                        h->mb.i_sub_partition[i] = h->mb.i_sub_partition[i+2] = analysis.i_mb_partition8x16[i];
                        if( analysis.i_mb_partition8x16[i] == D_L0_8x8 )
                            x264_me_refine_qpel_rd( h, &analysis.l0.me8x16[i], analysis.i_lambda2, i*4, 0 );
                        else if( analysis.i_mb_partition8x16[i] == D_L1_8x8 )
                            x264_me_refine_qpel_rd( h, &analysis.l1.me8x16[i], analysis.i_lambda2, i*4, 1 );
                        else if( analysis.i_mb_partition8x16[i] == D_BI_8x8 )
                        {
                            i_biweight = h->mb.bipred_weight[analysis.l0.me8x16[i].i_ref][analysis.l1.me8x16[i].i_ref];
                            x264_me_refine_bidir_rd( h, &analysis.l0.me8x16[i], &analysis.l1.me8x16[i], i_biweight, i, analysis.i_lambda2 );
                        }
                    }
                }
                else if( i_partition == D_8x8 )
                {
                    for( int i = 0; i < 4; i++ )
                    {
                        if( h->mb.i_sub_partition[i] == D_L0_8x8 )
                            x264_me_refine_qpel_rd( h, &analysis.l0.me8x8[i], analysis.i_lambda2, i*4, 0 );
                        else if( h->mb.i_sub_partition[i] == D_L1_8x8 )
                            x264_me_refine_qpel_rd( h, &analysis.l1.me8x8[i], analysis.i_lambda2, i*4, 1 );
                        else if( h->mb.i_sub_partition[i] == D_BI_8x8 )
                        {
                            i_biweight = h->mb.bipred_weight[analysis.l0.me8x8[i].i_ref][analysis.l1.me8x8[i].i_ref];
                            x264_me_refine_bidir_rd( h, &analysis.l0.me8x8[i], &analysis.l1.me8x8[i], i_biweight, i, analysis.i_lambda2 );
                        }
                    }
                }
            }
        }
    }

    analyse_update_cache( h, &analysis );

    /* In rare cases we can end up qpel-RDing our way back to a larger partition size
     * without realizing it.  Check for this and account for it if necessary. */
    if( analysis.i_mbrd >= 2 )
    {
        /* Don't bother with bipred or 8x8-and-below, the odds are incredibly low. */
        static const uint8_t check_mv_lists[X264_MBTYPE_MAX] = {[P_L0]=1, [B_L0_L0]=1, [B_L1_L1]=2};
        int list = check_mv_lists[h->mb.i_type] - 1;
        if( list >= 0 && h->mb.i_partition != D_16x16 &&
            M32( &h->mb.cache.mv[list][x264_scan8[0]] ) == M32( &h->mb.cache.mv[list][x264_scan8[12]] ) &&
            h->mb.cache.ref[list][x264_scan8[0]] == h->mb.cache.ref[list][x264_scan8[12]] )
                h->mb.i_partition = D_16x16;
    }

    if( !analysis.i_mbrd )
        mb_analyse_transform( h );

    if( analysis.i_mbrd == 3 && !IS_SKIP(h->mb.i_type) )
        mb_analyse_qp_rd( h, &analysis );

    h->mb.b_trellis = h->param.analyse.i_trellis;
    h->mb.b_noise_reduction = h->mb.b_noise_reduction || (!!h->param.analyse.i_noise_reduction && !IS_INTRA( h->mb.i_type ));

    if( !IS_SKIP(h->mb.i_type) && h->mb.i_psy_trellis && h->param.analyse.i_trellis == 1 )
        psy_trellis_init( h, 0 );
    if( h->mb.b_trellis == 1 || h->mb.b_noise_reduction )
        h->mb.i_skip_intra = 0;

    /* ACT22.1B rate-model bias trace, Hook A -- see mobi_act22_rate_trace_analyse()
     * above. This is the true single end-of-function point of
     * x264_macroblock_analyse(): analyse_update_cache() has already run (a few
     * lines above) so h->mb.i_type/i_partition/i_qp are fully finalized by
     * every code path above this point. Read-only, no-op unless
     * MOBI_ACT22_RATE_TRACE is set. */
    mobi_act22_rate_trace_analyse( h, &analysis );

    /* ACT22.2A pure-simulation hook -- see mobi_act22_2a_sim() above. Same
     * insertion point as Hook A (true end of this function, after
     * analyse_update_cache() has run). Read-only, no-op unless
     * MOBI_ACT22_2A_SIM is set. */
    mobi_act22_2a_sim( h, &analysis );

    /* ACT22.3B activation -- see mobi_act22_3_activate() above. The ONLY
     * ACT22.x hook that is a real behavioral change, and only when
     * MOBI_ACT22_3_ACTIVATE is explicitly set to a winners-CSV path; unset
     * (the default, and the state used by every other gate in this phase)
     * is a true no-op. */
    mobi_act22_3_activate( h );
}

/*-------------------- Update MB from the analysis ----------------------*/
static void analyse_update_cache( x264_t *h, x264_mb_analysis_t *a  )
{
    switch( h->mb.i_type )
    {
        case I_4x4:
            for( int i = 0; i < 16; i++ )
                h->mb.cache.intra4x4_pred_mode[x264_scan8[i]] = a->i_predict4x4[i];

            mb_analyse_intra_chroma( h, a );
            break;
        case I_8x8:
            for( int i = 0; i < 4; i++ )
                x264_macroblock_cache_intra8x8_pred( h, 2*(i&1), 2*(i>>1), a->i_predict8x8[i] );

            mb_analyse_intra_chroma( h, a );
            break;
        case I_16x16:
            h->mb.i_intra16x16_pred_mode = a->i_predict16x16;
            mb_analyse_intra_chroma( h, a );
            break;

        case I_PCM:
            break;

        case P_L0:
            switch( h->mb.i_partition )
            {
                case D_16x16:
                    x264_macroblock_cache_ref( h, 0, 0, 4, 4, 0, a->l0.me16x16.i_ref );
                    x264_macroblock_cache_mv_ptr( h, 0, 0, 4, 4, 0, a->l0.me16x16.mv );
                    break;

                case D_16x8:
                    x264_macroblock_cache_ref( h, 0, 0, 4, 2, 0, a->l0.me16x8[0].i_ref );
                    x264_macroblock_cache_ref( h, 0, 2, 4, 2, 0, a->l0.me16x8[1].i_ref );
                    x264_macroblock_cache_mv_ptr( h, 0, 0, 4, 2, 0, a->l0.me16x8[0].mv );
                    x264_macroblock_cache_mv_ptr( h, 0, 2, 4, 2, 0, a->l0.me16x8[1].mv );
                    break;

                case D_8x16:
                    x264_macroblock_cache_ref( h, 0, 0, 2, 4, 0, a->l0.me8x16[0].i_ref );
                    x264_macroblock_cache_ref( h, 2, 0, 2, 4, 0, a->l0.me8x16[1].i_ref );
                    x264_macroblock_cache_mv_ptr( h, 0, 0, 2, 4, 0, a->l0.me8x16[0].mv );
                    x264_macroblock_cache_mv_ptr( h, 2, 0, 2, 4, 0, a->l0.me8x16[1].mv );
                    break;

                default:
                    x264_log( h, X264_LOG_ERROR, "internal error P_L0 and partition=%d\n", h->mb.i_partition );
                    break;
            }
            break;

        case P_8x8:
            x264_macroblock_cache_ref( h, 0, 0, 2, 2, 0, a->l0.me8x8[0].i_ref );
            x264_macroblock_cache_ref( h, 2, 0, 2, 2, 0, a->l0.me8x8[1].i_ref );
            x264_macroblock_cache_ref( h, 0, 2, 2, 2, 0, a->l0.me8x8[2].i_ref );
            x264_macroblock_cache_ref( h, 2, 2, 2, 2, 0, a->l0.me8x8[3].i_ref );
            for( int i = 0; i < 4; i++ )
                mb_cache_mv_p8x8( h, a, i );
            break;

        case P_SKIP:
        {
            h->mb.i_partition = D_16x16;
            x264_macroblock_cache_ref( h, 0, 0, 4, 4, 0, 0 );
            x264_macroblock_cache_mv_ptr( h, 0, 0, 4, 4, 0, h->mb.cache.pskip_mv );
            break;
        }

        case B_SKIP:
        case B_DIRECT:
            h->mb.i_partition = h->mb.cache.direct_partition;
            mb_load_mv_direct8x8( h, 0 );
            mb_load_mv_direct8x8( h, 1 );
            mb_load_mv_direct8x8( h, 2 );
            mb_load_mv_direct8x8( h, 3 );
            break;

        case B_8x8:
            /* optimize: cache might not need to be rewritten */
            for( int i = 0; i < 4; i++ )
                mb_cache_mv_b8x8( h, a, i, 1 );
            break;

        default: /* the rest of the B types */
            switch( h->mb.i_partition )
            {
            case D_16x16:
                switch( h->mb.i_type )
                {
                case B_L0_L0:
                    x264_macroblock_cache_ref( h, 0, 0, 4, 4, 0, a->l0.me16x16.i_ref );
                    x264_macroblock_cache_mv_ptr( h, 0, 0, 4, 4, 0, a->l0.me16x16.mv );

                    x264_macroblock_cache_ref( h, 0, 0, 4, 4, 1, -1 );
                    x264_macroblock_cache_mv ( h, 0, 0, 4, 4, 1, 0 );
                    x264_macroblock_cache_mvd( h, 0, 0, 4, 4, 1, 0 );
                    break;
                case B_L1_L1:
                    x264_macroblock_cache_ref( h, 0, 0, 4, 4, 0, -1 );
                    x264_macroblock_cache_mv ( h, 0, 0, 4, 4, 0, 0 );
                    x264_macroblock_cache_mvd( h, 0, 0, 4, 4, 0, 0 );

                    x264_macroblock_cache_ref( h, 0, 0, 4, 4, 1, a->l1.me16x16.i_ref );
                    x264_macroblock_cache_mv_ptr( h, 0, 0, 4, 4, 1, a->l1.me16x16.mv );
                    break;
                case B_BI_BI:
                    x264_macroblock_cache_ref( h, 0, 0, 4, 4, 0, a->l0.bi16x16.i_ref );
                    x264_macroblock_cache_mv_ptr( h, 0, 0, 4, 4, 0, a->l0.bi16x16.mv );

                    x264_macroblock_cache_ref( h, 0, 0, 4, 4, 1, a->l1.bi16x16.i_ref );
                    x264_macroblock_cache_mv_ptr( h, 0, 0, 4, 4, 1, a->l1.bi16x16.mv );
                    break;
                }
                break;
            case D_16x8:
                mb_cache_mv_b16x8( h, a, 0, 1 );
                mb_cache_mv_b16x8( h, a, 1, 1 );
                break;
            case D_8x16:
                mb_cache_mv_b8x16( h, a, 0, 1 );
                mb_cache_mv_b8x16( h, a, 1, 1 );
                break;
            default:
                x264_log( h, X264_LOG_ERROR, "internal error (invalid MB type)\n" );
                break;
            }
    }

#ifndef NDEBUG
    if( h->i_thread_frames > 1 && !IS_INTRA(h->mb.i_type) )
    {
        for( int l = 0; l <= (h->sh.i_type == SLICE_TYPE_B); l++ )
        {
            int completed;
            int ref = h->mb.cache.ref[l][x264_scan8[0]];
            if( ref < 0 )
                continue;
            completed = x264_frame_cond_wait( h->fref[l][ ref >> MB_INTERLACED ]->orig, -1 );
            if( (h->mb.cache.mv[l][x264_scan8[15]][1] >> (2 - MB_INTERLACED)) + h->mb.i_mb_y*16 > completed )
            {
                x264_log( h, X264_LOG_WARNING, "internal error (MV out of thread range)\n");
                x264_log( h, X264_LOG_DEBUG, "mb type: %d \n", h->mb.i_type);
                x264_log( h, X264_LOG_DEBUG, "mv: l%dr%d (%d,%d) \n", l, ref,
                                h->mb.cache.mv[l][x264_scan8[15]][0],
                                h->mb.cache.mv[l][x264_scan8[15]][1] );
                x264_log( h, X264_LOG_DEBUG, "limit: %d \n", h->mb.mv_max_spel[1]);
                x264_log( h, X264_LOG_DEBUG, "mb_xy: %d,%d \n", h->mb.i_mb_x, h->mb.i_mb_y);
                x264_log( h, X264_LOG_DEBUG, "completed: %d \n", completed );
                x264_log( h, X264_LOG_WARNING, "recovering by using intra mode\n");
                mb_analyse_intra( h, a, COST_MAX );
                h->mb.i_type = I_16x16;
                h->mb.i_intra16x16_pred_mode = a->i_predict16x16;
                mb_analyse_intra_chroma( h, a );
            }
        }
    }
#endif
}

#include "slicetype.c"

