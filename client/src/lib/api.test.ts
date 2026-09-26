import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, removeFromQueue, triggerNext, triggerPrevious, updateSettings } from './api'

const fetchMock = vi.fn<typeof fetch>()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => vi.unstubAllGlobals())

describe('API mutation response handling', () => {
  it.each([
    ['next', triggerNext],
    ['previous', triggerPrevious],
  ])('accepts an empty 202 from display/%s', async (direction, trigger) => {
    fetchMock.mockResolvedValue(new Response(null, { status: 202 }))
    await expect(trigger()).resolves.toBeUndefined()
    expect(fetchMock).toHaveBeenCalledWith(`/api/display/${direction}`, expect.objectContaining({
      method: 'POST', credentials: 'include',
    }))
  })

  it('accepts an empty 204 from queue deletion', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    await expect(removeFromQueue('photo-id')).resolves.toBeUndefined()
  })

  it('decodes a JSON success response and serializes the request', async () => {
    const settings = { change_mode: 'manual', change_hour: 8, change_interval_minutes: 60, saturation: 1.5 }
    fetchMock.mockResolvedValue(new Response(JSON.stringify(settings), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }))
    await expect(updateSettings({ saturation: 1.5 })).resolves.toEqual(settings)
    expect(fetchMock).toHaveBeenCalledWith('/api/settings', expect.objectContaining({
      method: 'POST', body: '{"saturation":1.5}',
    }))
  })

  it('preserves HTTP status and error body on failure', async () => {
    fetchMock.mockResolvedValue(new Response('{"detail":"Display unavailable"}', { status: 503 }))
    const promise = triggerNext()
    await expect(promise).rejects.toBeInstanceOf(ApiError)
    await expect(promise).rejects.toMatchObject({
      status: 503,
      message: 'POST /api/display/next → 503: {"detail":"Display unavailable"}',
    })
  })

  it('does not silently accept malformed non-empty JSON', async () => {
    fetchMock.mockResolvedValue(new Response('not JSON', { status: 200 }))
    await expect(updateSettings({ saturation: 1.5 })).rejects.toBeInstanceOf(SyntaxError)
  })
})
