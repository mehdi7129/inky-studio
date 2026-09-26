import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { decode } from './decode'

const { heicTo } = vi.hoisted(() => ({ heicTo: vi.fn() }))
vi.mock('heic-to', () => ({ heicTo }))

const createImageBitmapMock = vi.fn<typeof createImageBitmap>()
const bitmap = { width: 4032, height: 3024, close: vi.fn() } as unknown as ImageBitmap

beforeEach(() => {
  createImageBitmapMock.mockReset()
  heicTo.mockReset()
  vi.stubGlobal('createImageBitmap', createImageBitmapMock)
})
afterEach(() => vi.unstubAllGlobals())

describe('image decoding', () => {
  it.each([
    ['photo.HEIC', 'image/heic', true],
    ['photo.png', 'image/png', false],
  ])('uses native decoding for %s without invoking the HEIC fallback', async (name, type, wasHeic) => {
    const file = new File(['image bytes'], name, { type })
    createImageBitmapMock.mockResolvedValue(bitmap)

    await expect(decode(file)).resolves.toEqual({
      bitmap, width: 4032, height: 3024, sourceFilename: name, wasHeic,
    })
    expect(createImageBitmapMock).toHaveBeenCalledExactlyOnceWith(file)
    expect(heicTo).not.toHaveBeenCalled()
  })

  it.each([
    ['photo', 'image/heic'],
    ['photo', 'image/heic-sequence'],
    ['photo', 'image/heif'],
    ['photo', 'image/heif-sequence'],
    ['photo.HEIC', ''],
    ['photo.HeIf', 'application/octet-stream'],
  ])('falls back to a bitmap decoder for %s (%s) after native rejection', async (name, type) => {
    const file = new File(['image bytes'], name, { type })
    createImageBitmapMock.mockRejectedValue(new DOMException('Unsupported image', 'InvalidStateError'))
    heicTo.mockResolvedValue(bitmap)

    await expect(decode(file)).resolves.toEqual({
      bitmap, width: 4032, height: 3024, sourceFilename: name, wasHeic: true,
    })
    expect(createImageBitmapMock).toHaveBeenCalledExactlyOnceWith(file)
    expect(heicTo).toHaveBeenCalledExactlyOnceWith({ blob: file, type: 'bitmap' })
  })

  it('preserves non-HEIC native failures without invoking the HEIC fallback', async () => {
    const error = new DOMException('Corrupt image', 'InvalidStateError')
    createImageBitmapMock.mockRejectedValue(error)

    await expect(decode(new File(['invalid'], 'photo.png', { type: 'image/png' }))).rejects.toBe(error)
    expect(heicTo).not.toHaveBeenCalled()
  })

  it('wraps structured HEIC decoder failures in an actionable Error and keeps the cause', async () => {
    const cause = { code: 2, subcode: 2000, message: 'Unsupported codec' }
    createImageBitmapMock.mockRejectedValue(new DOMException('Unsupported image'))
    heicTo.mockRejectedValue(cause)

    const result = decode(new File(['invalid'], 'photo.HEIC'))
    await expect(result).rejects.toBeInstanceOf(Error)
    await expect(result).rejects.toMatchObject({
      message: 'Impossible de lire cette photo HEIC/HEIF. Exportez-la en JPEG ou PNG, puis réessayez.',
      cause,
    })
  })
})
