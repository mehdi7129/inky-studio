import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, fetchState, removeFromQueue, triggerNext, triggerPrevious, updateSettings, uploadToQueue } from './api'

const fetchMock = vi.fn<typeof fetch>()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => vi.unstubAllGlobals())

describe('API error response handling', () => {
  it.each([
    ['GET', fetchState],
    ['POST', triggerNext],
    ['upload', () => uploadToQueue(new Blob(['photo']), 'photo.png')],
  ])('shows the server detail for a failed %s request', async (_method, request) => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({
      detail: 'L’écran du cadre est indisponible.', code: 'display_unavailable',
    }), { status: 503 }))
    const promise = request()
    await expect(promise).rejects.toBeInstanceOf(ApiError)
    await expect(promise).rejects.toMatchObject({
      status: 503, message: 'L’écran du cadre est indisponible.',
    })
  })

  it.each([
    '<html>Service unavailable</html>',
    '{"detail":',
    '{"detail":{"error":"unavailable"}}',
    '{"detail":[{"msg":"unavailable"}]}',
    '{"detail":"  "}',
    'null',
    '',
  ])('uses a readable fallback for an unusable error body (%s)', async (body) => {
    fetchMock.mockResolvedValue(new Response(body, { status: 503 }))
    await expect(fetchState()).rejects.toMatchObject({
      status: 503, message: 'La requête a échoué (HTTP 503).',
    })
  })
})

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

  it('does not silently accept malformed non-empty JSON', async () => {
    fetchMock.mockResolvedValue(new Response('not JSON', { status: 200 }))
    await expect(updateSettings({ saturation: 1.5 })).rejects.toBeInstanceOf(SyntaxError)
  })
})
