/**
 * ImageData → PNG Blob via OffscreenCanvas when available, fallback to <canvas>.
 *
 * We use the browser's native PNG encoder because:
 *  - It's free (zero JS bytes added)
 *  - The Inky-side server doesn't care how the PNG is compressed
 *  - The output dimensions/palette are already locked by the dither step
 */
export async function imageDataToPng(image: ImageData): Promise<Blob> {
  if (typeof OffscreenCanvas !== 'undefined') {
    const canvas = new OffscreenCanvas(image.width, image.height)
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('OffscreenCanvas 2D context unavailable')
    ctx.putImageData(image, 0, 0)
    return canvas.convertToBlob({ type: 'image/png' })
  }

  const canvas = document.createElement('canvas')
  canvas.width = image.width
  canvas.height = image.height
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas 2D context unavailable')
  ctx.putImageData(image, 0, 0)
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (!blob) {
        reject(new Error('Canvas failed to encode PNG'))
        return
      }
      resolve(blob)
    }, 'image/png')
  })
}
