/**
 * File → HTMLImageElement (via Blob URL).
 *
 * HEIC files are converted to JPEG first using libheif-js (loaded lazily so
 * the WASM blob — ~2 MB — never costs anything until a HEIC is dropped).
 * Everything else goes straight through createImageBitmap-friendly paths.
 */

const HEIC_MIMES = new Set([
  'image/heic',
  'image/heic-sequence',
  'image/heif',
  'image/heif-sequence',
])

function isHeic(file: File): boolean {
  if (HEIC_MIMES.has(file.type)) return true
  const lower = file.name.toLowerCase()
  return lower.endsWith('.heic') || lower.endsWith('.heif')
}

async function decodeHeicToBlob(file: File): Promise<Blob> {
  const { default: heic2any } = await import('heic2any')
  const result = await heic2any({ blob: file, toType: 'image/jpeg', quality: 0.92 })
  return Array.isArray(result) ? result[0] : result
}

export interface DecodedImage {
  bitmap: ImageBitmap
  width: number
  height: number
  sourceFilename: string
  /** Whether the input went through the HEIC fallback. */
  wasHeic: boolean
}

export async function decode(file: File): Promise<DecodedImage> {
  const wasHeic = isHeic(file)
  const blob = wasHeic ? await decodeHeicToBlob(file) : file
  const bitmap = await createImageBitmap(blob)
  return {
    bitmap,
    width: bitmap.width,
    height: bitmap.height,
    sourceFilename: file.name,
    wasHeic,
  }
}
