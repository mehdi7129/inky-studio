/**
 * Fetch a server-side preview of the processed image.
 *
 * Sends the resized RGB PNG to POST /api/preview?color_mode=... and receives
 * back the Pillow-processed result — exactly what the e-ink will display.
 *
 * Falls back gracefully (returns null) if the server is unreachable or if the
 * request takes too long (> 10 s), so the JS dither preview is always shown
 * immediately while this fetch is in flight.
 */

export async function fetchServerPreview(
  pngBlob: Blob,
  colorMode: string,
  signal?: AbortSignal,
): Promise<ImageData | null> {
  try {
    const form = new FormData()
    form.append('file', pngBlob, 'preview.png')
    const response = await fetch(`/api/preview?color_mode=${encodeURIComponent(colorMode)}`, {
      method: 'POST',
      credentials: 'include',
      body: form,
      signal,
    })
    if (!response.ok) return null

    const arrayBuf = await response.arrayBuffer()
    const blob = new Blob([arrayBuf], { type: 'image/png' })
    const bitmap = await createImageBitmap(blob)
    const canvas = document.createElement('canvas')
    canvas.width = bitmap.width
    canvas.height = bitmap.height
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return null
    ctx.drawImage(bitmap, 0, 0)
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
    bitmap.close?.()
    return imageData
  } catch {
    return null
  }
}
