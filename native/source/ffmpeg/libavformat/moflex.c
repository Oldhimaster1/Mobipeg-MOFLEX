/*
 * MOFLEX demuxer
 * Copyright (c) 2015-2016 Florian Nouwt
 * Copyright (c) 2017 Adib Surani
 * Copyright (c) 2020 Paul B Mahol
 * Copyright (c) 2026 quatric - quatricsoftware@gmail.com
 *
 * This file is part of FFmpeg.
 *
 * FFmpeg is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2.1 of the License, or (at your option) any later version.
 *
 * FFmpeg is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with FFmpeg; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
 */

#include "libavcodec/bytestream.h"
#include "libavutil/intreadwrite.h"
#include "demux.h"

#include "avformat.h"
#include "internal.h"

typedef struct BitReader {
    unsigned last;
    unsigned pos;
} BitReader;

typedef struct MOFLEXDemuxContext {
    unsigned size;
    int64_t pos;
    int64_t ts;
    int flags;
    int in_block;

    BitReader br;

    int64_t stream_pts[16]; /* cumulative pts per stream index */
    uint32_t expected_video_frames; /* validated MobiPEG front seek-table */
} MOFLEXDemuxContext;

static int moflex_eof_status(AVFormatContext *s)
{
    const MOFLEXDemuxContext *m = s->priv_data;

    /* An intact front seek-table states the exact frame count.  Do not
     * silently accept a truncated media region as normal EOF. */
    if (m->expected_video_frames &&
        m->stream_pts[0] < m->expected_video_frames)
        return AVERROR_INVALIDDATA;

    /* Do not infer expected audio duration from video frames: some valid
     * source clips deliberately end their audio earlier (silent tail).
     * Use the release SHA256 manifest to detect missing audio-only blocks. */
    return AVERROR_EOF;
}

static int pop(BitReader *br, AVIOContext *pb)
{
    if (avio_feof(pb))
        return AVERROR_EOF;

    if ((br->pos & 7) == 0)
        br->last = (unsigned)avio_r8(pb) << 24U;
    else
        br->last <<= 1;

    br->pos++;
    return !!(br->last & 0x80000000);
}

static int pop_int(BitReader *br, AVIOContext *pb, int n)
{
    int value = 0;

    for (int i = 0; i < n; i++) {
        int ret = pop(br, pb);

        if (ret < 0)
            return ret;
        if (ret > INT_MAX - value - value)
            return AVERROR_INVALIDDATA;
        value = 2 * value + ret;
    }

    return value;
}

static int pop_length(BitReader *br, AVIOContext *pb)
{
    int ret, n = 1;

    while ((ret = pop(br, pb)) == 0)
        n++;

    if (ret < 0)
        return ret;
    return n;
}

static int read_var_byte(AVFormatContext *s, unsigned *out)
{
    AVIOContext *pb = s->pb;
    unsigned value = 0, data;

    data = avio_r8(pb);
    if (!(data & 0x80)) {
        *out = data;
        return 0;
    }

    value = (data & 0x7F) << 7;
    data = avio_r8(pb);
    if (!(data & 0x80)) {
        value |= data;
        *out = value;
        return 0;
    }

    value = ((data & 0x7F) | value) << 7;
    data = avio_r8(pb);
    if (!(data & 0x80)) {
        value |= data;
        *out = value;
        return 0;
    }

    value = (((data & 0x7F) | value) << 7) | avio_r8(pb);
    *out = value;

    return 0;
}

static int moflex_probe(const AVProbeData *p)
{
    GetByteContext gb;
    int score = 0;

    bytestream2_init(&gb, p->buf, p->buf_size);

    if (bytestream2_get_be16(&gb) != 0x4C32)
        return 0;
    score += 10;

    bytestream2_skip(&gb, 10);
    if (bytestream2_get_be16(&gb) == 0)
        return 0;
    score += 5;

    while (bytestream2_get_bytes_left(&gb) > 0) {
        int type = bytestream2_get_byte(&gb);
        int size = bytestream2_get_byte(&gb);

        if (type == 0) {
            score += 5 * (size == 0);
            break;
        }
        if ((type == 1 && size == 12) ||
            (type == 2 && size ==  6) ||
            (type == 3 && size == 13) ||
            (type == 4 && size ==  2))
            score += 20;
        bytestream2_skip(&gb, size);
    }

    return FFMIN(AVPROBE_SCORE_MAX, score);
}

static int moflex_read_sync(AVFormatContext *s)
{
    MOFLEXDemuxContext *m = s->priv_data;
    AVIOContext *pb = s->pb;

    if (avio_rb16(pb) != 0x4C32) {
        if (avio_feof(pb))
            return AVERROR_EOF;
        avio_seek(pb, -2, SEEK_CUR);
        return 1;
    }

    avio_skip(pb, 2);
    m->ts = avio_rb64(pb);
    m->size = avio_rb16(pb) + 1;

    while (!avio_feof(pb)) {
        unsigned type, ssize, codec_id = 0;
        unsigned codec_type, width = 0, height = 0, sample_rate = 0, channels = 0;
        int stream_index = -1;
        AVRational tb = av_make_q(0, 1);

        read_var_byte(s, &type);
        read_var_byte(s, &ssize);

        switch (type) {
        case 0:
            if (ssize > 0)
                avio_skip(pb, ssize);
            return 0;
        case 2:
            codec_type = AVMEDIA_TYPE_AUDIO;
            stream_index = avio_r8(pb);
            codec_id = avio_r8(pb);
            switch (codec_id) {
            case 0: codec_id = AV_CODEC_ID_FASTAUDIO; break;
            case 1: codec_id = AV_CODEC_ID_ADPCM_IMA_MOFLEX; break;
            case 2: codec_id = AV_CODEC_ID_PCM_S16LE; break;
            default:
                av_log(s, AV_LOG_ERROR, "Unsupported audio codec: %d\n", codec_id);
                return AVERROR_PATCHWELCOME;
            }
            sample_rate = avio_rb24(pb) + 1;
            tb = av_make_q(1, sample_rate);
            channels = avio_r8(pb) + 1;
            break;
        case 1:
        case 3:
            codec_type = AVMEDIA_TYPE_VIDEO;
            stream_index = avio_r8(pb);
            codec_id = avio_r8(pb);
            switch (codec_id) {
            case 0: codec_id = AV_CODEC_ID_MOBICLIP; break;
            case 1: codec_id = AV_CODEC_ID_H264; break;
            default:
                av_log(s, AV_LOG_ERROR, "Unsupported video codec: %d\n", codec_id);
                return AVERROR_PATCHWELCOME;
            }
            tb.den = avio_rb16(pb);
            tb.num = avio_rb16(pb);
            width = avio_rb16(pb);
            height = avio_rb16(pb);
            if (type == 3) {
                /* VideoWithLayout advertises the *displayed frame-pair*
                 * rate for interleaved 3D (layout 0/1). Every coded packet
                 * is a single eye, L,R,L,R, so the FFmpeg packet time base
                 * must run at twice the descriptor rate. In particular this
                 * keeps accurate seek, -t, and audio/video remux from seeing
                 * a stereo movie as two times its real duration. Layout 2D
                 * and packed SBS/TB retain their normal frame rate. */
                int layout;
                avio_skip(pb, 2); /* PelRatioRate / PelRatioScale */
                layout = avio_r8(pb) & 0x0f;
                if ((layout == 0 || layout == 1) && tb.num > 0 && tb.den > 0)
                    tb.den *= 2;
            } else {
                avio_skip(pb, 2);
            }
            break;
        case 4:
            codec_type = AVMEDIA_TYPE_DATA;
            stream_index = avio_r8(pb);
            avio_skip(pb, 1);
            break;
        }

        if (stream_index == s->nb_streams) {
            AVStream *st = avformat_new_stream(s, NULL);

            if (!st)
                return AVERROR(ENOMEM);

            st->codecpar->codec_type = codec_type;
            st->codecpar->codec_id   = codec_id;
            st->codecpar->width      = width;
            st->codecpar->height     = height;
            st->codecpar->sample_rate= sample_rate;
            st->codecpar->ch_layout.nb_channels = channels;
            st->priv_data            = av_packet_alloc();
            if (!st->priv_data)
                return AVERROR(ENOMEM);

            if (tb.num)
                avpriv_set_pts_info(st, 63, tb.num, tb.den);
        }
    }

    return 0;
}

static int moflex_read_header(AVFormatContext *s)
{
    int ret;

    ret = moflex_read_sync(s);
    if (ret < 0)
        return ret;

    s->ctx_flags |= AVFMTCTX_NOHEADER;
    avio_seek(s->pb, 0, SEEK_SET);

    return 0;
}

static int moflex_read_packet(AVFormatContext *s, AVPacket *pkt)
{
    MOFLEXDemuxContext *m = s->priv_data;
    AVIOContext *pb = s->pb;
    BitReader *br = &m->br;
    int ret;

    while (!avio_feof(pb)) {
        if (!m->in_block) {
            m->pos = avio_tell(pb);

            ret = moflex_read_sync(s);
            if (ret == AVERROR_EOF)
                return moflex_eof_status(s);
            if (ret < 0)
                return ret;

            m->flags = avio_r8(pb);
            if (m->flags & 2)
                avio_skip(pb, 2);

            if (getenv("MOFLEX_DEBUG"))
                av_log(s, AV_LOG_INFO,
                       "BLOCK pos=0x%"PRIx64" sync=%d flags=0x%02x size=%d\n",
                       (int64_t)m->pos, ret == 0, m->flags, m->size);
        }

        while ((avio_tell(pb) < m->pos + m->size) && !avio_feof(pb) && avio_r8(pb)) {
            int stream_index, bits, pkt_size, endframe;
            AVPacket *packet;

            m->in_block = 1;

            avio_seek(pb, -1, SEEK_CUR);
            br->pos = br->last = 0;

            bits = pop_length(br, pb);
            if (bits < 0)
                return bits;
            stream_index = pop_int(br, pb, bits);
            if (stream_index < 0)
                return stream_index;
            if (stream_index >= s->nb_streams)
                return AVERROR_INVALIDDATA;

            endframe = pop(br, pb);
            if (endframe < 0)
                return endframe;
            if (endframe) {
                bits = pop_length(br, pb);
                if (bits < 0)
                    return bits;
                pop_int(br, pb, bits);
                pop(br, pb);
                bits = pop_length(br, pb);
                if (bits < 0)
                    return bits;
                pop_int(br, pb, bits * 2 + 26);
            }

            pkt_size = pop_int(br, pb, 13) + 1;
            if (pkt_size > m->size)
                return AVERROR_INVALIDDATA;
            if (getenv("MOFLEX_DEBUG"))
                av_log(s, AV_LOG_INFO,
                       "  CHUNK si=%d endframe=%d pkt_size=%d payload@0x%"PRIx64"\n",
                       stream_index, endframe, pkt_size, (int64_t)avio_tell(pb));
            packet   = s->streams[stream_index]->priv_data;
            if (!packet) {
                avio_skip(pb, pkt_size);
                continue;
            }

            ret = av_append_packet(pb, packet, pkt_size);
            if (ret < 0)
                return ret;

            /* Helper lambda-equivalent: fill audio packet fields and advance PTS. */
#define FILL_AUDIO_PKT(p, si_idx) do {                                          \
            (p)->pos          = m->pos;                                          \
            (p)->stream_index = (si_idx);                                        \
            (p)->flags       |= AV_PKT_FLAG_KEY;                                 \
            if ((si_idx) < FF_ARRAY_ELEMS(m->stream_pts)) {                      \
                (p)->pts = m->stream_pts[(si_idx)];                               \
                (p)->dts = (p)->pts;                                              \
            }                                                                    \
            {                                                                    \
                AVCodecParameters *_par = s->streams[(si_idx)]->codecpar;        \
                int64_t _dur = 0;                                                 \
                int _ch = _par->ch_layout.nb_channels;                           \
                if (_ch <= 0) _ch = 1;                                           \
                if (_par->codec_id == AV_CODEC_ID_PCM_S16LE) {                  \
                    _dur = (p)->size / (_ch * 2);                                 \
                } else if (_par->codec_id == AV_CODEC_ID_ADPCM_IMA_MOFLEX) {    \
                    /* one shared header (ch*4), then ch*128 nibbles per subframe */ \
                    _dur = _ch > 0 ? ((p)->size - 4 * _ch) * 2 / _ch : 0;     \
                } else if (_par->codec_id == AV_CODEC_ID_FASTAUDIO) {           \
                    /* A MOFLEX packet may aggregate several 40-byte/channel    \
                     * FastAudio frames. Each frame decodes to 256 samples. */   \
                    _dur = _ch > 0 ? ((p)->size / (40 * _ch)) * 256 : 0;         \
                }                                                                \
                (p)->duration = _dur;                                             \
                if ((si_idx) < FF_ARRAY_ELEMS(m->stream_pts))                    \
                    m->stream_pts[(si_idx)] += _dur;                              \
            }                                                                    \
        } while (0)

            if (endframe && packet->size > 0) {
                av_packet_move_ref(pkt, packet);
                pkt->pos = m->pos;
                pkt->stream_index = stream_index;
                /* Recognize only the front table emitted by this MobiPEG
                 * muxer: [u32 entry_count][u32 video_frames][u32 us][u32 0]
                 * followed by entry_count 24-byte index entries.  Other
                 * vendor data streams are left uninterpreted. */
                if (s->streams[stream_index]->codecpar->codec_type == AVMEDIA_TYPE_DATA &&
                    pkt->size >= 40) {
                    uint32_t entries = AV_RL32(pkt->data);
                    uint32_t frames = AV_RL32(pkt->data + 4);
                    if (entries > 0 && entries < 65536 && frames > 0 &&
                        (uint64_t)pkt->size == 16ULL + 24ULL * entries &&
                        AV_RL32(pkt->data + 12) == 0)
                        m->expected_video_frames = frames;
                }
                if (stream_index < FF_ARRAY_ELEMS(m->stream_pts)) {
                    pkt->pts = m->stream_pts[stream_index];
                    pkt->dts = pkt->pts;
                }
                if (s->streams[stream_index]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO) {
                    pkt->duration = 1;
                    /* Key-frame detection for MobiClip: the decoder applies
                     * bswap16 before parsing, so the first decoded bit is
                     * bit7 of pkt->data[1] (not data[0]).  A 1 there = I-frame.
                     * For H.264 Annex-B streams scan for IDR/SPS NAL type. */
                    if (s->streams[stream_index]->codecpar->codec_id == AV_CODEC_ID_MOBICLIP) {
                        if (pkt->size >= 2 && (pkt->data[1] & 0x80))
                            pkt->flags |= AV_PKT_FLAG_KEY;
                    } else {
                        /* Annex-B: find first non-zero byte past start codes */
                        int si = 0;
                        while (si < pkt->size - 1 && pkt->data[si] == 0) si++;
                        if (si < pkt->size && pkt->data[si] == 0x01) si++;
                        if (si < pkt->size) {
                            int nal_type = pkt->data[si] & 0x1F;
                            if (nal_type == 5 || nal_type == 7)
                                pkt->flags |= AV_PKT_FLAG_KEY;
                        }
                    }
                    if (stream_index < FF_ARRAY_ELEMS(m->stream_pts))
                        m->stream_pts[stream_index] += 1;
                } else {
                    FILL_AUDIO_PKT(pkt, stream_index);
                }
                return 0;
            }
        }

        m->in_block = 0;

        if (m->flags % 2 == 0) {
            if (m->size <= 0)
                return AVERROR_INVALIDDATA;
            avio_seek(pb, m->pos + m->size, SEEK_SET);
        }
    }

    return moflex_eof_status(s);
}

static int moflex_read_seek(AVFormatContext *s, int stream_index,
                            int64_t pts, int flags)
{
    MOFLEXDemuxContext *m = s->priv_data;
    int64_t ret;
    int i;

    /*
     * Safe compatibility path: seek back to the beginning and allow the
     * caller's accurate-seek logic to decode/drop frames until 'pts'.
     *
     * The generic packet index includes block-start addresses which are
     * NOT guaranteed to start at MobiClip I-frames. Seeking directly to a
     * nominal timestamp can therefore feed a P-frame into an empty picture
     * ring and produce "P-frame setup_qtables failed".  Rewind preserves
     * correctness while a real keyframe+timestamp index is implemented.
     *
     * This is intentionally O(video duration) for mid-file seeks.
     */
    if (!(s->pb->seekable & AVIO_SEEKABLE_NORMAL))
        return AVERROR(ENOSYS);

    ret = avio_seek(s->pb, 0, SEEK_SET);
    if (ret < 0)
        return (int)ret;

    for (i = 0; i < FF_ARRAY_ELEMS(m->stream_pts); i++)
        m->stream_pts[i] = 0;
    for (i = 0; i < s->nb_streams; i++)
        if (s->streams[i]->priv_data)
            av_packet_unref(s->streams[i]->priv_data);

    m->pos = 0;
    m->size = 0;
    m->flags = 0;
    m->in_block = 0;
    return 0;
}

static int moflex_read_close(AVFormatContext *s)
{
    for (int i = 0; i < s->nb_streams; i++) {
        av_packet_free((AVPacket **)&s->streams[i]->priv_data);
    }

    return 0;
}

const FFInputFormat ff_moflex_demuxer = {
    .p.name           = "moflex",
    .p.long_name      = NULL_IF_CONFIG_SMALL("MobiClip MOFLEX"),
    .priv_data_size = sizeof(MOFLEXDemuxContext),
    .read_probe     = moflex_probe,
    .read_header    = moflex_read_header,
    .read_packet    = moflex_read_packet,
    .read_seek      = moflex_read_seek,
    .read_close     = moflex_read_close,
    .p.extensions     = "moflex",
    .p.flags          = AVFMT_GENERIC_INDEX,
    .flags_internal = FF_INFMT_FLAG_INIT_CLEANUP,
};
