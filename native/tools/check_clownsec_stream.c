/* Host integration test of Clownsec forward-only MOFLEX demuxer on stdin pipe. */
#include "moflex_demux.h"
#include <stdio.h>

int main(void) {
    MfxDemux m;
    if (mfx_open_live(&m, stdin) != 0) {
        fprintf(stderr, "mfx_open_live failed\n");
        return 1;
    }
    int video = 0, audio = 0, r;
    MfxPacket pkt;
    while ((r = mfx_next_packet(&m, &pkt)) == 1) {
        if (m.streams[pkt.stream_index].media_type == MFX_TYPE_VIDEO) {
            video++;
            if (video == 1) {
                printf("FIRST_VIDEO_PACKET_RECEIVED\n");
                fflush(stdout);
            }
        } else if (m.streams[pkt.stream_index].media_type == MFX_TYPE_AUDIO) audio++;
    }
    printf("END live video=%d audio=%d parser_status=%d\n", video, audio, r);
    mfx_close(&m);
    return r < 0 || video < 1 ? 1 : 0;
}
