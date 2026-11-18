// Convert short PCM16 RIFF/WAVE audio into a planar PCM16 Nintendo CWAV.
export function wavToCwav(input) {
  const v = new DataView(input.buffer, input.byteOffset, input.byteLength);
  const tag = (o) => new TextDecoder().decode(input.subarray(o, o + 4));
  if (
    input.length < 12 ||
    tag(0) !== "RIFF" ||
    tag(8) !== "WAVE" ||
    v.getUint32(4, true) + 8 > input.length
  )
    throw Error("Use an uncompressed PCM16 WAV file");
  let format = null,
    data = null;
  for (let p = 12; p + 8 <= input.length; ) {
    const size = v.getUint32(p + 4, true),
      end = p + 8 + size;
    if (end > input.length) throw Error("Truncated WAV chunk");
    if (tag(p) === "fmt ") {
      if (size < 16) throw Error("Invalid WAV format");
      format = {
        codec: v.getUint16(p + 8, true),
        channels: v.getUint16(p + 10, true),
        rate: v.getUint32(p + 12, true),
        align: v.getUint16(p + 20, true),
        bits: v.getUint16(p + 22, true),
      };
    }
    if (tag(p) === "data") data = input.subarray(p + 8, end);
    p = end + (size % 2);
  }
  if (
    !format ||
    !data ||
    format.codec !== 1 ||
    format.bits !== 16 ||
    ![1, 2].includes(format.channels) ||
    format.align !== format.channels * 2 ||
    format.rate < 8000 ||
    format.rate > 48000 ||
    data.length % format.align
  )
    throw Error("WAV must be mono/stereo PCM16 at 8–48 kHz");
  const frames = data.length / format.align;
  if (!frames || frames > format.rate * 10)
    throw Error("Banner audio must be between one sample and ten seconds");
  const align = (n) => Math.ceil(n / 32) * 32;
  const infoSize = align(28 + format.channels * 8 + format.channels * 20),
    dataOffset = 64 + infoSize,
    channelStride = align(frames * 2),
    dataSize = align(32 + channelStride * format.channels);
  const output = new Uint8Array(dataOffset + dataSize),
    out = new DataView(output.buffer),
    put = (o, n) => out.setUint32(o, n, true),
    short = (o, n) => out.setUint16(o, n, true),
    text = (o, s) => output.set(new TextEncoder().encode(s), o);
  text(0, "CWAV");
  short(4, 0xfeff);
  short(6, 64);
  put(8, 0x02010000);
  put(12, output.length);
  short(16, 2);
  short(20, 0x7000);
  put(24, 64);
  put(28, infoSize);
  short(32, 0x7001);
  put(36, dataOffset);
  put(40, dataSize);
  text(64, "INFO");
  put(68, infoSize);
  output[72] = 1;
  put(76, format.rate);
  put(84, frames);
  put(92, format.channels);
  const channelBase = 96 + format.channels * 8;
  for (let channel = 0; channel < format.channels; channel++) {
    const ref = 96 + channel * 8,
      entry = channelBase + channel * 20;
    short(ref, 0x7100);
    put(ref + 4, entry - 92);
    short(entry, 0x1f00);
    put(entry + 4, 24 + channel * channelStride);
    put(entry + 12, 0xffffffff);
    for (let frame = 0; frame < frames; frame++)
      output.set(
        data.subarray(
          (frame * format.channels + channel) * 2,
          (frame * format.channels + channel) * 2 + 2,
        ),
        dataOffset + 32 + channel * channelStride + frame * 2,
      );
  }
  text(dataOffset, "DATA");
  put(dataOffset + 4, dataSize);
  return output;
}
export async function bannerWithWav(banner, wav) {
  if (wav.size > 2 * 1024 * 1024) throw Error("WAV exceeds 2 MiB");
  const audio = wavToCwav(new Uint8Array(await wav.arrayBuffer())),
    header = banner.slice();
  const v = new DataView(header.buffer, header.byteOffset, header.byteLength),
    old = v.getUint32(132, true);
  const end = old || header.length,
    offset = Math.ceil(end / 16) * 16;
  if (end < 136 || end > header.length)
    throw Error("Invalid banner audio offset");
  const output = new Uint8Array(offset + audio.length);
  output.set(header.subarray(0, end));
  new DataView(output.buffer).setUint32(132, offset, true);
  output.set(audio, offset);
  return output;
}
