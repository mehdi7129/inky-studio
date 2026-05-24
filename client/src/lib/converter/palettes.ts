import palettesData from '@shared/palettes.json'

export type RGB = readonly [number, number, number]

export interface PaletteColor {
  readonly name: string
  readonly rgb: RGB
}

export interface SpectraPalette {
  readonly description: string
  readonly models: readonly string[]
  readonly colors: readonly PaletteColor[]
}

interface WarmthAdjustments {
  readonly red_gain: number
  readonly green_gain: number
  readonly blue_gain: number
  readonly brightness: number
  readonly saturation: number
}

export const SPECTRA_PALETTE: SpectraPalette = {
  description: palettesData.spectra_palette.description,
  models: palettesData.spectra_palette.models,
  colors: palettesData.spectra_palette.colors.map((c) => ({
    name: c.name,
    rgb: [c.rgb[0], c.rgb[1], c.rgb[2]] as const,
  })),
}

export const WARMTH_ADJUSTMENTS: WarmthAdjustments = palettesData.warmth_boost.adjustments

export type ColorMode = 'pimoroni' | 'spectra_palette' | 'warmth_boost'

/** Flat Uint8 array of the palette: [r,g,b, r,g,b, ...]. Faster for inner loops. */
export function spectraPaletteFlat(): Uint8Array {
  const flat = new Uint8Array(SPECTRA_PALETTE.colors.length * 3)
  SPECTRA_PALETTE.colors.forEach((color, idx) => {
    flat[idx * 3] = color.rgb[0]
    flat[idx * 3 + 1] = color.rgb[1]
    flat[idx * 3 + 2] = color.rgb[2]
  })
  return flat
}

/**
 * The 7-color "pimoroni" palette mirrors the older Inky Impression 7.3" (classic).
 * Used when COLOR_MODE='pimoroni' on a classic display — we keep it as a fallback
 * even though our hardware target is Spectra 6.
 */
export const PIMORONI_PALETTE: SpectraPalette = {
  description: 'Classic 7-color Inky palette (saturation 0.5 in the Pimoroni lib).',
  models: ['inky-7.3-classic'],
  colors: [
    { name: 'black', rgb: [0, 0, 0] },
    { name: 'white', rgb: [255, 255, 255] },
    { name: 'green', rgb: [0, 128, 0] },
    { name: 'blue', rgb: [0, 0, 255] },
    { name: 'red', rgb: [255, 0, 0] },
    { name: 'yellow', rgb: [255, 255, 0] },
    { name: 'orange', rgb: [255, 140, 0] },
  ],
}
