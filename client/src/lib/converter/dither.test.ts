import { describe, expect, it } from 'vitest'
import { applyWarmth, dither } from './dither'

const SPECTRA: Uint8Array = new Uint8Array([
  0, 0, 0,        // black
  255, 255, 255,  // white
  160, 32, 32,    // red
  240, 224, 80,   // yellow
  96, 128, 80,    // green
  80, 128, 184,   // blue
])

function makeRGBA(width: number, height: number, fill: [number, number, number]): Uint8ClampedArray {
  const arr = new Uint8ClampedArray(width * height * 4)
  for (let i = 0; i < width * height; i++) {
    arr[i * 4] = fill[0]
    arr[i * 4 + 1] = fill[1]
    arr[i * 4 + 2] = fill[2]
    arr[i * 4 + 3] = 255
  }
  return arr
}

describe('dither (Floyd-Steinberg)', () => {
  it('snaps a solid black image to the black palette color', () => {
    const pixels = makeRGBA(4, 4, [0, 0, 0])
    const result = dither({ width: 4, height: 4, pixels, paletteFlat: SPECTRA })
    for (let i = 0; i < 16; i++) {
      expect(result.pixels[i * 4]).toBe(0)
      expect(result.pixels[i * 4 + 1]).toBe(0)
      expect(result.pixels[i * 4 + 2]).toBe(0)
      expect(result.pixels[i * 4 + 3]).toBe(255)
    }
  })

  it('snaps a solid white image to the white palette color', () => {
    const pixels = makeRGBA(4, 4, [255, 255, 255])
    const result = dither({ width: 4, height: 4, pixels, paletteFlat: SPECTRA })
    for (let i = 0; i < 16; i++) {
      expect(result.pixels[i * 4]).toBe(255)
      expect(result.pixels[i * 4 + 1]).toBe(255)
      expect(result.pixels[i * 4 + 2]).toBe(255)
    }
  })

  it('only emits colors that exist in the palette', () => {
    // Random-ish gradient — every output pixel should match one palette entry
    const width = 16
    const height = 16
    const pixels = new Uint8ClampedArray(width * height * 4)
    for (let i = 0; i < width * height; i++) {
      pixels[i * 4] = (i * 7) % 256
      pixels[i * 4 + 1] = (i * 13) % 256
      pixels[i * 4 + 2] = (i * 23) % 256
      pixels[i * 4 + 3] = 255
    }
    const result = dither({ width, height, pixels, paletteFlat: SPECTRA })
    const allowed = new Set<string>()
    for (let p = 0; p < SPECTRA.length / 3; p++) {
      allowed.add(`${SPECTRA[p * 3]},${SPECTRA[p * 3 + 1]},${SPECTRA[p * 3 + 2]}`)
    }
    for (let i = 0; i < width * height; i++) {
      const key = `${result.pixels[i * 4]},${result.pixels[i * 4 + 1]},${result.pixels[i * 4 + 2]}`
      expect(allowed.has(key)).toBe(true)
    }
  })

  it('preserves the average tone of a mid-gray image', () => {
    // Mid-gray (128,128,128) is between black and white; FS should produce
    // a mix whose average stays near 128 ± 4
    const pixels = makeRGBA(32, 32, [128, 128, 128])
    const result = dither({ width: 32, height: 32, pixels, paletteFlat: SPECTRA })
    let sumR = 0
    let sumG = 0
    let sumB = 0
    const total = 32 * 32
    for (let i = 0; i < total; i++) {
      sumR += result.pixels[i * 4]
      sumG += result.pixels[i * 4 + 1]
      sumB += result.pixels[i * 4 + 2]
    }
    expect(sumR / total).toBeGreaterThan(110)
    expect(sumR / total).toBeLessThan(145)
    expect(sumG / total).toBeGreaterThan(110)
    expect(sumG / total).toBeLessThan(145)
    expect(sumB / total).toBeGreaterThan(110)
    expect(sumB / total).toBeLessThan(145)
  })

  it('forces alpha to 255 in the output', () => {
    const pixels = makeRGBA(2, 2, [0, 0, 0])
    pixels[3] = 0
    pixels[7] = 50
    const result = dither({ width: 2, height: 2, pixels, paletteFlat: SPECTRA })
    for (let i = 0; i < 4; i++) {
      expect(result.pixels[i * 4 + 3]).toBe(255)
    }
  })
})

describe('applyWarmth', () => {
  it('shifts a neutral gray toward warmer tones', () => {
    const pixels = makeRGBA(1, 1, [128, 128, 128])
    applyWarmth(pixels, 1.15, 0.92, 0.75, 1.0, 1.0)
    // Red gain > blue gain → red should end up higher than blue
    expect(pixels[0]).toBeGreaterThan(pixels[2])
  })

  it('clamps values into [0, 255]', () => {
    const pixels = makeRGBA(1, 1, [240, 240, 240])
    applyWarmth(pixels, 2.0, 2.0, 2.0, 2.0, 1.0)
    expect(pixels[0]).toBe(255)
    expect(pixels[1]).toBe(255)
    expect(pixels[2]).toBe(255)
  })
})
