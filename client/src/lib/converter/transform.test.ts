import { afterEach, describe, expect, it, vi } from 'vitest'
import { transformToImageData } from './transform'

afterEach(() => vi.restoreAllMocks())

// Geometry uses the real transform; the canvas port is recorded, not a PNG
// encoder or a browser rendering qualification.
describe('crop geometry for Spectra and seven-color panel formats', () => {
  const sizes = [[600, 400], [800, 480], [1600, 1200], [600, 448], [640, 400]]
  for (const [width, height] of sizes) {
    it.each([[4000, 3000], [3000, 4000]])(
      `${width}x${height} fills the panel for source %ix%i at both crop extremes`,
      (sourceWidth, sourceHeight) => {
        const drawImage = vi.fn()
        const getImageData = vi.fn(() => ({ width, height }) as ImageData)
        const context = { drawImage, getImageData }
        vi.spyOn(HTMLCanvasElement.prototype, 'getContext')
          .mockReturnValue(context as unknown as CanvasRenderingContext2D)
        const bitmap = { width: sourceWidth, height: sourceHeight } as ImageBitmap

        for (const offset of [-10, 0, 10]) {
          const output = transformToImageData(bitmap, {
            targetWidth: width, targetHeight: height, offsetX: offset, offsetY: offset,
          })
          expect([output.width, output.height]).toEqual([width, height])
          expect(getImageData).toHaveBeenLastCalledWith(0, 0, width, height)
          const [, x, y, drawWidth, drawHeight] = drawImage.mock.lastCall!
          expect(x).toBeLessThanOrEqual(0)
          expect(y).toBeLessThanOrEqual(0)
          expect(x + drawWidth).toBeGreaterThanOrEqual(width)
          expect(y + drawHeight).toBeGreaterThanOrEqual(height)
          expect(drawWidth / drawHeight).toBeCloseTo(sourceWidth / sourceHeight)
          expect(Math.min(drawWidth / width, drawHeight / height)).toBeCloseTo(1)
        }
      },
    )
  }
})
