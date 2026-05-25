/**
 * Floyd-Steinberg dithering against a fixed palette.
 *
 * The algorithm walks the image left-to-right, top-to-bottom. For each pixel:
 *  1. Find the closest palette color (Euclidean RGB distance).
 *  2. Compute the quantization error (old - new).
 *  3. Spread the error to the 4 forward neighbours with weights:
 *
 *        .   *   7/16
 *       3/16 5/16 1/16
 *
 * We work in-place on a Float32Array so error accumulation doesn't truncate
 * between pixels. Output is a fresh Uint8ClampedArray with the same RGBA
 * layout — alpha is forced to 255 (the Inky is opaque).
 */
export interface DitherParams {
  width: number
  height: number
  /** RGBA pixels, length = width * height * 4. */
  pixels: Uint8ClampedArray
  /** Flat RGB palette, length must be a multiple of 3. */
  paletteFlat: Uint8Array
}

export interface DitherResult {
  /** Dithered RGBA buffer ready to be put back into a canvas. */
  pixels: Uint8ClampedArray
}

export function dither(params: DitherParams): DitherResult {
  const { width, height, paletteFlat } = params
  const total = width * height
  const buf = new Float32Array(total * 3)
  for (let i = 0; i < total; i++) {
    buf[i * 3] = params.pixels[i * 4]
    buf[i * 3 + 1] = params.pixels[i * 4 + 1]
    buf[i * 3 + 2] = params.pixels[i * 4 + 2]
  }

  const out = new Uint8ClampedArray(total * 4)
  const paletteSize = paletteFlat.length / 3

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const idx = (y * width + x) * 3
      const r = buf[idx]
      const g = buf[idx + 1]
      const b = buf[idx + 2]

      let bestDist = Infinity
      let bestR = 0
      let bestG = 0
      let bestB = 0
      for (let p = 0; p < paletteSize; p++) {
        const pr = paletteFlat[p * 3]
        const pg = paletteFlat[p * 3 + 1]
        const pb = paletteFlat[p * 3 + 2]
        const dr = r - pr
        const dg = g - pg
        const db = b - pb
        const dist = dr * dr + dg * dg + db * db
        if (dist < bestDist) {
          bestDist = dist
          bestR = pr
          bestG = pg
          bestB = pb
          if (dist === 0) break
        }
      }

      const outIdx = (y * width + x) * 4
      out[outIdx] = bestR
      out[outIdx + 1] = bestG
      out[outIdx + 2] = bestB
      out[outIdx + 3] = 255

      const errR = r - bestR
      const errG = g - bestG
      const errB = b - bestB

      if (x + 1 < width) {
        const ni = (y * width + (x + 1)) * 3
        buf[ni] += (errR * 7) / 16
        buf[ni + 1] += (errG * 7) / 16
        buf[ni + 2] += (errB * 7) / 16
      }
      if (y + 1 < height) {
        if (x > 0) {
          const ni = ((y + 1) * width + (x - 1)) * 3
          buf[ni] += (errR * 3) / 16
          buf[ni + 1] += (errG * 3) / 16
          buf[ni + 2] += (errB * 3) / 16
        }
        const niC = ((y + 1) * width + x) * 3
        buf[niC] += (errR * 5) / 16
        buf[niC + 1] += (errG * 5) / 16
        buf[niC + 2] += (errB * 5) / 16
        if (x + 1 < width) {
          const niR = ((y + 1) * width + (x + 1)) * 3
          buf[niR] += errR / 16
          buf[niR + 1] += errG / 16
          buf[niR + 2] += errB / 16
        }
      }
    }
  }

  return { pixels: out }
}

/**
 * Boost contrast and colour saturation in-place.
 *
 * Matches v2.0's _apply_spectra_palette() preprocessing:
 *   - contrast  +20% (factor 1.2)
 *   - saturation +30% (factor 1.3)
 *
 * This step is essential before palette quantisation: it pushes colours apart,
 * making the nearest-palette-colour mapping more accurate and reducing noise in
 * dark regions.
 */
export function applyContrastAndSaturation(
  pixels: Uint8ClampedArray,
  contrastFactor: number,
  saturationFactor: number,
): void {
  const total = pixels.length / 4
  for (let i = 0; i < total; i++) {
    const idx = i * 4
    let r = pixels[idx]
    let g = pixels[idx + 1]
    let b = pixels[idx + 2]

    // Contrast: scale around mid-grey (128)
    r = clampByte((r - 128) * contrastFactor + 128)
    g = clampByte((g - 128) * contrastFactor + 128)
    b = clampByte((b - 128) * contrastFactor + 128)

    // Saturation: lerp toward grey
    const gray = 0.299 * r + 0.587 * g + 0.114 * b
    r = clampByte(gray + (r - gray) * saturationFactor)
    g = clampByte(gray + (g - gray) * saturationFactor)
    b = clampByte(gray + (b - gray) * saturationFactor)

    pixels[idx] = r
    pixels[idx + 1] = g
    pixels[idx + 2] = b
  }
}

/**
 * Apply RGB gain + brightness + saturation adjustments in-place. Used as the
 * pre-step for the "warmth_boost" color mode, matching the Pimoroni v2.0 config.
 */
export function applyWarmth(
  pixels: Uint8ClampedArray,
  redGain: number,
  greenGain: number,
  blueGain: number,
  brightness: number,
  saturation: number,
): void {
  const total = pixels.length / 4
  for (let i = 0; i < total; i++) {
    const idx = i * 4
    let r = pixels[idx] * redGain * brightness
    let g = pixels[idx + 1] * greenGain * brightness
    let b = pixels[idx + 2] * blueGain * brightness

    const gray = 0.299 * r + 0.587 * g + 0.114 * b
    r = gray + (r - gray) * saturation
    g = gray + (g - gray) * saturation
    b = gray + (b - gray) * saturation

    pixels[idx] = clampByte(r)
    pixels[idx + 1] = clampByte(g)
    pixels[idx + 2] = clampByte(b)
  }
}

function clampByte(n: number): number {
  if (n < 0) return 0
  if (n > 255) return 255
  return n
}
