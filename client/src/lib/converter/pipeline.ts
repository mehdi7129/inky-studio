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

export interface ConvertResult {
  /** ImageData ready to draw to a <canvas> for preview. */
  previewImage: ImageData
  /** PNG Blob ready to POST to /api/queue. */
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

export async function convert(options: ConvertOptions): Promise<ConvertResult> {
  const t0 = performance.now()

  const decoded = await decode(options.file)
  const imageData = transformToImageData(decoded.bitmap, {
    targetWidth: options.targetWidth,
    targetHeight: options.targetHeight,
    offsetX: options.offsetX,
    offsetY: options.offsetY,
  })

  if (options.colorMode === 'warmth_boost') {
    applyWarmth(
      imageData.data,
      WARMTH_ADJUSTMENTS.red_gain,
      WARMTH_ADJUSTMENTS.green_gain,
      WARMTH_ADJUSTMENTS.blue_gain,
      WARMTH_ADJUSTMENTS.brightness,
      WARMTH_ADJUSTMENTS.saturation,
    )
  }

  // 'pimoroni' mode uses a 7-color palette; 'spectra_palette' and 'warmth_boost' both
  // use the calibrated 6-color palette (warmth_boost has already adjusted the pixels above).
  const paletteFlat = paletteFlatFor(options.colorMode)

  let ditheredPixels: Uint8ClampedArray
  if (options.forceInline) {
    ditheredPixels = dither({
      width: imageData.width,
      height: imageData.height,
      pixels: imageData.data,
      paletteFlat,
    }).pixels
  } else {
    ditheredPixels = await ditherInWorker(imageData, paletteFlat)
  }

  // Copy into a guaranteed-non-shared buffer so ImageData's strict typing is happy.
  const previewBuffer = new Uint8ClampedArray(ditheredPixels.length)
  previewBuffer.set(ditheredPixels)
  const previewImage = new ImageData(previewBuffer, imageData.width, imageData.height)
  const pngBlob = await imageDataToPng(previewImage)

  decoded.bitmap.close?.()

  return {
    previewImage,
    pngBlob,
    durationMs: performance.now() - t0,
    wasHeic: decoded.wasHeic,
  }
}
