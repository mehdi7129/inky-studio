/**
 * File → ImageBitmap, using the browser's native decoder first.
 *
 * Unsupported HEIC/HEIF files fall back to heic-to's libheif decoder (asm.js),
 * loaded only when needed. It returns a bitmap without JPEG recompression.
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

async function decodeHeic(file: File): Promise<ImageBitmap> {
  try {
    const { heicTo } = await import('heic-to')
    return await heicTo({ blob: file, type: 'bitmap' })
  } catch (cause) {
    throw new Error(
      'Impossible de lire cette photo HEIC/HEIF. Exportez-la en JPEG ou PNG, puis réessayez.',
      { cause },
    )
  }
}

export interface DecodedImage {
  bitmap: ImageBitmap
  width: number
  height: number
  sourceFilename: string
  /** Whether the input is recognized as HEIC/HEIF, including native decoding. */
  wasHeic: boolean
}

export async function decode(file: File): Promise<DecodedImage> {
  const wasHeic = isHeic(file)
  let bitmap: ImageBitmap
  try {
    bitmap = await createImageBitmap(file)
  } catch (error) {
    if (!wasHeic) throw error
    bitmap = await decodeHeic(file)
  }
  return {
    bitmap,
    width: bitmap.width,
    height: bitmap.height,
    sourceFilename: file.name,
    wasHeic,
  }
}
