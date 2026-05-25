/**
 * End-to-end conversion pipeline orchestrating decode → transform → (warmth →) dither → encode.
 *
 * Heavy CPU work (dithering) is offloaded to a Web Worker so the UI thread
 * keeps animating during conversion of a 1600×1200 photo (~1.9 MP). The
 * worker is reused across conversions — instantiated once on first run.
 */
import { decode } from './decode'
import { transformToImageData } from './transform'
import {
  PIMORONI_PALETTE,
  WARMTH_ADJUSTMENTS,
  spectraPaletteFlat,
  type ColorMode,
} from './palettes'
import { applyWarmth, dither } from './dither'
import { imageDataToPng } from './encode'

export interface ConvertOptions {
  file: File
  targetWidth: number
  targetHeight: number
  colorMode: ColorMode
  offsetX?: number
  offsetY?: number
  /** Set to true to use the main thread instead of the worker (for tests). */
  forceInline?: boolean
}

export interface ConvertBitmapOptions {
  bitmap: ImageBitmap
  targetWidth: number
  targetHeight: number
  colorMode: ColorMode
  offsetX?: number
  offsetY?: number
  forceInline?: boolean
}

export interface ConvertResult {
  /** Source image cropped to display dimensions (no palette/dither) — what we upload. */
  originalImage: ImageData
  /**
   * JS-dithered approximation for in-browser preview only.
   * The server re-applies Pillow Floyd-Steinberg at display time, so the actual
   * quality on the e-ink will be better than this canvas preview.
   */
  previewImage: ImageData
  /**
   * Undithered RGB PNG ready to POST to /api/queue.
   * The server does the final palette conversion with Pillow (much better quality
   * than the in-browser dithering shown in the preview canvas).
   */
  pngBlob: Blob
  /** Total milliseconds spent in the pipeline. */
  durationMs: number
  /** Whether the input had to go through HEIC decode. */
  wasHeic: boolean
}

let cachedWorker: Worker | null = null

function getWorker(): Worker {
  if (cachedWorker) return cachedWorker
  cachedWorker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' })
  return cachedWorker
}

function paletteFlatFor(mode: ColorMode): Uint8Array {
  if (mode === 'pimoroni') {
    const flat = new Uint8Array(PIMORONI_PALETTE.colors.length * 3)
    PIMORONI_PALETTE.colors.forEach((color, i) => {
      flat[i * 3] = color.rgb[0]
      flat[i * 3 + 1] = color.rgb[1]
      flat[i * 3 + 2] = color.rgb[2]
    })
    return flat
  }
  return spectraPaletteFlat()
}

function ditherInWorker(
  imageData: ImageData,
  paletteFlat: Uint8Array,
): Promise<Uint8ClampedArray> {
  return new Promise((resolve, reject) => {
    const worker = getWorker()
    const onMessage = (event: MessageEvent) => {
      worker.removeEventListener('message', onMessage)
      worker.removeEventListener('error', onError)
      if (event.data?.type === 'ok') resolve(event.data.pixels as Uint8ClampedArray)
      else reject(new Error(event.data?.error ?? 'Unknown worker error'))
    }
    const onError = (event: ErrorEvent) => {
      worker.removeEventListener('message', onMessage)
      worker.removeEventListener('error', onError)
      reject(event.error ?? new Error(event.message))
    }
    worker.addEventListener('message', onMessage)
    worker.addEventListener('error', onError)
    worker.postMessage(
      {
        type: 'dither',
        width: imageData.width,
        height: imageData.height,
        pixels: imageData.data,
        paletteFlat,
      },
      [imageData.data.buffer, paletteFlat.buffer],
    )
  })
}

/**
 * High-level entry: decode the file, then run the full conversion pipeline.
 * Convenient for one-shot conversions (e.g. tests). For interactive UIs, prefer
 * caching the decoded bitmap and calling `convertBitmap` directly so that
 * HEIC decode (~1.5s) doesn't happen on every slider/mode tweak.
 */
export async function convert(options: ConvertOptions): Promise<ConvertResult> {
  const decoded = await decode(options.file)
  try {
    const result = await convertBitmap({
      bitmap: decoded.bitmap,
      targetWidth: options.targetWidth,
      targetHeight: options.targetHeight,
      colorMode: options.colorMode,
      offsetX: options.offsetX,
      offsetY: options.offsetY,
      forceInline: options.forceInline,
    })
    return { ...result, wasHeic: decoded.wasHeic }
  } finally {
    decoded.bitmap.close?.()
  }
}

export async function convertBitmap(options: ConvertBitmapOptions): Promise<ConvertResult> {
  const t0 = performance.now()
  const { bitmap, targetWidth, targetHeight, colorMode } = options

  // Two passes through the resize: one we keep as the "original" preview, one
  // we mutate (warmth) and dither. Re-running transformToImageData is cheap
  // (~5-20ms on 800×480) compared to a HEIC decode (~1500ms).
  const originalImage = transformToImageData(bitmap, {
    targetWidth,
    targetHeight,
    offsetX: options.offsetX,
    offsetY: options.offsetY,
  })
  const working = transformToImageData(bitmap, {
    targetWidth,
    targetHeight,
    offsetX: options.offsetX,
    offsetY: options.offsetY,
  })

  if (colorMode === 'warmth_boost') {
    applyWarmth(
      working.data,
      WARMTH_ADJUSTMENTS.red_gain,
      WARMTH_ADJUSTMENTS.green_gain,
      WARMTH_ADJUSTMENTS.blue_gain,
      WARMTH_ADJUSTMENTS.brightness,
      WARMTH_ADJUSTMENTS.saturation,
    )
  }

  const paletteFlat = paletteFlatFor(colorMode)

  let ditheredPixels: Uint8ClampedArray
  if (options.forceInline) {
    ditheredPixels = dither({
      width: working.width,
      height: working.height,
      pixels: working.data,
      paletteFlat,
    }).pixels
  } else {
    ditheredPixels = await ditherInWorker(working, paletteFlat)
  }

  const previewBuffer = new Uint8ClampedArray(ditheredPixels.length)
  previewBuffer.set(ditheredPixels)
  const previewImage = new ImageData(previewBuffer, working.width, working.height)

  // Upload the ORIGINAL (undithered) crop — the server applies Pillow Floyd-Steinberg
  // which is far superior to our JS approximation. The browser preview is indicative only.
  const pngBlob = await imageDataToPng(originalImage)

  return {
    originalImage,
    previewImage,
    pngBlob,
    durationMs: performance.now() - t0,
    wasHeic: false,
  }
}

export { decode } from './decode'
