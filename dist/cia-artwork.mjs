// Encode artwork into the existing player's texture formats without template assets.
export function tileRgb565(rgba, width, height) {
  if (width % 8 || height % 8 || rgba.length !== width * height * 4)
    throw Error("Invalid tiled image dimensions");
  const output = new Uint8Array(width * height * 2),
    view = new DataView(output.buffer);
  let pixel = 0;
  for (let y = 0; y < height; y += 8)
    for (let x = 0; x < width; x += 8)
      for (let morton = 0; morton < 64; morton++) {
        const sx = (morton & 1) | ((morton >> 1) & 2) | ((morton >> 2) & 4);
        const sy =
          ((morton >> 1) & 1) | ((morton >> 2) & 2) | ((morton >> 3) & 4);
        const p = ((y + sy) * width + x + sx) * 4,
          alpha = rgba[p + 3] / 255;
        const channel = (offset, bits) =>
          Math.floor(
            ((rgba[p + offset] * alpha + 255 * (1 - alpha)) *
              ((1 << bits) - 1)) /
              255,
          );
        view.setUint16(
          pixel++ * 2,
          (channel(0, 5) << 11) | (channel(1, 6) << 5) | channel(2, 5),
          true,
        );
      }
  return output;
}
async function imagePixels(
  file,
  width,
  height,
  insetWidth = width,
  insetHeight = height,
) {
  if (file.size > 32 * 1024 * 1024) throw Error("Artwork exceeds 32 MiB");
  const bitmap = await createImageBitmap(file);
  try {
    if (bitmap.width * bitmap.height > 40 * 1000 * 1000)
      throw Error("Artwork exceeds 40 megapixels");
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    context.fillStyle = "black";
    context.fillRect(0, 0, width, height);
    context.fillStyle = "white";
    context.fillRect(0, 0, insetWidth, insetHeight);
    const scale = Math.max(
      insetWidth / bitmap.width,
      insetHeight / bitmap.height,
    );
    const sourceWidth = insetWidth / scale,
      sourceHeight = insetHeight / scale;
    context.drawImage(
      bitmap,
      (bitmap.width - sourceWidth) / 2,
      (bitmap.height - sourceHeight) / 2,
      sourceWidth,
      sourceHeight,
      0,
      0,
      insetWidth,
      insetHeight,
    );
    return context.getImageData(0, 0, width, height).data;
  } finally {
    bitmap.close();
  }
}
export function isArtworkImage(file) {
  return /\.(png|bmp|jpe?g)$/i.test(file?.name || "");
}
export async function makeSmdhArtwork(file, original) {
  const output = Uint8Array.from(original);
  if (
    output.length !== 0x36c0 ||
    new TextDecoder().decode(output.subarray(0, 4)) !== "SMDH"
  )
    throw Error("Unsupported SMDH icon template");
  output.set(tileRgb565(await imagePixels(file, 24, 24), 24, 24), 0x2040);
  output.set(tileRgb565(await imagePixels(file, 48, 48), 48, 48), 0x24c0);
  return output;
}
export async function makeEpisodeArtwork(file, original) {
  if (original.size !== 0x10020)
    throw Error("Unsupported BIMG thumbnail template");
  const header = await original.slice(0, 32).arrayBuffer();
  return new Blob([
    header,
    tileRgb565(await imagePixels(file, 256, 128, 200, 120), 256, 128),
  ]);
}
