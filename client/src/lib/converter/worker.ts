/// <reference lib="webworker" />
import { dither } from './dither'

interface DitherRequest {
  type: 'dither'
  width: number
  height: number
  pixels: Uint8ClampedArray
  paletteFlat: Uint8Array
}

self.addEventListener('message', (event: MessageEvent<DitherRequest>) => {
  const data = event.data
  try {
    if (data?.type !== 'dither') throw new Error(`Unknown message type: ${data?.type}`)
    const result = dither({
      width: data.width,
      height: data.height,
      pixels: data.pixels,
      paletteFlat: data.paletteFlat,
    })
    ;(self as DedicatedWorkerGlobalScope).postMessage(
      { type: 'ok', pixels: result.pixels },
      { transfer: [result.pixels.buffer] },
    )
  } catch (err) {
    ;(self as DedicatedWorkerGlobalScope).postMessage({
      type: 'error',
      error: err instanceof Error ? err.message : String(err),
    })
  }
})
