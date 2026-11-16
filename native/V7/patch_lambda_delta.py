#!/usr/bin/env python3
"""Add reversible experimental MobiClip lambda offset to x264 analysis.
Default 0 keeps V5 behavior. Separate from the legacy all-the-way QYX_RDO flag.
"""
import pathlib,sys
f=pathlib.Path(sys.argv[1]);s=f.read_text()
old='''    int effective_chroma_qp = h->chroma_qp_table[SPEC_QP(qp)] + X264_MAX( qp - QP_MAX_SPEC, 0 );'''
new='''    /* V7: test intermediate lambda indexes between x264 raw QP and the
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

    int effective_chroma_qp = h->chroma_qp_table[SPEC_QP(qp)] + X264_MAX( qp - QP_MAX_SPEC, 0 );'''
assert old in s
f.write_text(s.replace(old,new,1));print('Patched',f)
