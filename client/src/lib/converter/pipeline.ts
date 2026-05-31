/**
 * Crop pipeline: decode → cover-crop to the panel size → encode PNG.
 *
 * No colour conversion happens in the browser. The Raspberry Pi's official
 * Pimoroni `inky.set_image()` performs the single, faithful quantisation to the
 * exact palette of the auto-detected panel. The browser only produces a
 * full-colour PNG cropped to the display's resolution.
 */
import { decode } from './decode'
import { transformToImageData } from './transform'
import { imageDataToPng } from './encode'

export interface ConvertOptions {
  file: File
  targetWidth: number
  targetHeight: number
  offsetX?: number
  offsetY?: number
}

export interface ConvertBitmapOptions {
  bitmap: ImageBitmap
  targetWidth: number
  targetHeight: number
  offsetX?: number
  offsetY?: number
}

export interface ConvertResult {
  /** Source image cropped to the display dimensions (full colour) — shown + uploaded. */
  originalImage: ImageData
  /** Full-colour PNG cropped to the panel, ready to POST to /api/queue. */
  pngBlob: Blob
  /** Total milliseconds spent in the pipeline. */
  durationMs: number
  /** Whether the input had to go through HEIC decode. */
  wasHeic: boolean
}

/** Decode the file, then crop to the display dimensions. */
export async function convert(options: ConvertOptions): Promise<ConvertResult> {
  const decoded = await decode(options.file)
  try {
    const result = await convertBitmap({
      bitmap: decoded.bitmap,
      targetWidth: options.targetWidth,
      targetHeight: options.targetHeight,
      offsetX: options.offsetX,
      offsetY: options.offsetY,
    })
    return { ...result, wasHeic: decoded.wasHeic }
  } finally {
    decoded.bitmap.close?.()
  }
}

export async function convertBitmap(options: ConvertBitmapOptions): Promise<ConvertResult> {
  const t0 = performance.now()
  const { bitmap, targetWidth, targetHeight } = options
  const originalImage = transformToImageData(bitmap, {
    targetWidth,
    targetHeight,
    offsetX: options.offsetX,
    offsetY: options.offsetY,
  })
  const pngBlob = await imageDataToPng(originalImage)
  return {
    originalImage,
    pngBlob,
    durationMs: performance.now() - t0,
    wasHeic: false,
  }
}

export { decode } from './decode'
