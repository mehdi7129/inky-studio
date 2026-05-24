/**
 * Geometry transforms: resize + crop a source bitmap into the exact display dims.
 *
 * Strategy = "cover" with center crop — fills the display, crops the parts that
 * don't fit the aspect ratio. We always upscale or downscale to the target size
 * in a single drawImage call, leaning on the browser's built-in resampling
 * (which on modern engines is bilinear-or-better and good enough for e-ink).
 *
 * Returns ImageData (RGBA byte array) so the dithering pass can run on it
 * without going through canvas again.
 */
export interface TransformOptions {
  targetWidth: number
  targetHeight: number
  /**
   * Center offset in [-1, 1] for horizontal/vertical re-centering of the crop.
   * 0,0 = perfect center, -1,0 = pin to the left, 1,0 = pin to the right.
   */
  offsetX?: number
  offsetY?: number
}

export function transformToImageData(
  bitmap: ImageBitmap,
  options: TransformOptions,
): ImageData {
  const { targetWidth, targetHeight } = options
  const offsetX = clamp(options.offsetX ?? 0, -1, 1)
  const offsetY = clamp(options.offsetY ?? 0, -1, 1)

  const sourceAspect = bitmap.width / bitmap.height
  const targetAspect = targetWidth / targetHeight

  let drawWidth: number
  let drawHeight: number
  let drawX: number
  let drawY: number

  if (sourceAspect > targetAspect) {
    // Source is wider than target — scale to height, crop sides
    drawHeight = targetHeight
    drawWidth = targetHeight * sourceAspect
    drawY = 0
    const slack = drawWidth - targetWidth
    drawX = -slack / 2 + (offsetX * slack) / 2
  } else {
    // Source is taller (or same aspect) — scale to width, crop top/bottom
    drawWidth = targetWidth
    drawHeight = targetWidth / sourceAspect
    drawX = 0
    const slack = drawHeight - targetHeight
    drawY = -slack / 2 + (offsetY * slack) / 2
  }

  const canvas = document.createElement('canvas')
  canvas.width = targetWidth
  canvas.height = targetHeight
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  if (!ctx) throw new Error('2D canvas context unavailable')
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(bitmap, drawX, drawY, drawWidth, drawHeight)
  return ctx.getImageData(0, 0, targetWidth, targetHeight)
}

function clamp(n: number, lo: number, hi: number): number {
  if (n < lo) return lo
  if (n > hi) return hi
  return n
}
