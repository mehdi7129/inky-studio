import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useWebSocket } from './useWebSocket'
import { fetchAuthStatus } from './api'

vi.mock('./api', () => ({ fetchAuthStatus: vi.fn() }))

class Socket extends EventTarget {
  static instances: Socket[] = []
  url: string
  close = vi.fn()
  constructor(url: string) {
    super()
    this.url = url
    Socket.instances.push(this)
  }
}

beforeEach(() => {
  vi.useFakeTimers()
  Socket.instances = []
  vi.mocked(fetchAuthStatus).mockReset()
  vi.mocked(fetchAuthStatus).mockResolvedValue({ authenticated: true, auth_required: true })
  vi.stubGlobal('WebSocket', Socket)
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

it('connects only when enabled and cancels pending reconnects on logout', () => {
  const { rerender } = renderHook(({ enabled }) => useWebSocket(vi.fn(), enabled), {
    initialProps: { enabled: false },
  })
  expect(Socket.instances).toHaveLength(0)
  rerender({ enabled: true })
  expect(Socket.instances).toHaveLength(1)
  act(() => { Socket.instances[0].dispatchEvent(new CloseEvent('close', { code: 1006 })) })
  rerender({ enabled: false })
  act(() => { vi.runAllTimers() })
  expect(Socket.instances).toHaveLength(1)
  expect(Socket.instances[0].close).toHaveBeenCalled()
})

it('reconnects after an ordinary disconnect and delivers the new hello', async () => {
  const onEvent = vi.fn()
  renderHook(() => useWebSocket(onEvent))
  await act(async () => {
    Socket.instances[0].dispatchEvent(new CloseEvent('close', { code: 1006 }))
    await Promise.resolve()
    vi.advanceTimersByTime(500)
  })
  expect(Socket.instances).toHaveLength(2)
  act(() => {
    Socket.instances[1].dispatchEvent(new MessageEvent('message', { data: '{"type":"hello"}' }))
  })
  expect(onEvent).toHaveBeenCalledWith({ type: 'hello' })
})

it('requests login when the server closes an expired authenticated connection', () => {
  const onEvent = vi.fn()
  renderHook(() => useWebSocket(onEvent))
  act(() => {
    Socket.instances[0].dispatchEvent(new CloseEvent('close', { code: 1008 }))
    vi.runAllTimers()
  })
  expect(onEvent).toHaveBeenCalledWith({ type: 'auth_required' })
  expect(Socket.instances).toHaveLength(1)
})

it('requests login after a failed handshake with a stale session cookie', async () => {
  vi.mocked(fetchAuthStatus).mockResolvedValue({ authenticated: false, auth_required: true })
  const onEvent = vi.fn()
  renderHook(() => useWebSocket(onEvent))
  await act(async () => {
    Socket.instances[0].dispatchEvent(new CloseEvent('close', { code: 1006 }))
    await Promise.resolve()
    vi.runAllTimers()
  })
  expect(fetchAuthStatus).toHaveBeenCalledOnce()
  expect(onEvent).toHaveBeenCalledWith({ type: 'auth_required' })
  expect(Socket.instances).toHaveLength(1)
})

it('keeps retrying with backoff when the auth probe cannot reach the server', async () => {
  vi.mocked(fetchAuthStatus).mockRejectedValue(new TypeError('Network unreachable'))
  const onEvent = vi.fn()
  renderHook(() => useWebSocket(onEvent))
  await act(async () => {
    Socket.instances[0].dispatchEvent(new CloseEvent('close', { code: 1006 }))
    await Promise.resolve()
    vi.advanceTimersByTime(499)
  })
  expect(Socket.instances).toHaveLength(1)
  act(() => { vi.advanceTimersByTime(1) })
  expect(Socket.instances).toHaveLength(2)
  await act(async () => {
    Socket.instances[1].dispatchEvent(new CloseEvent('close', { code: 1006 }))
    await Promise.resolve()
    vi.advanceTimersByTime(999)
  })
  expect(Socket.instances).toHaveLength(2)
  act(() => { vi.advanceTimersByTime(1) })
  expect(Socket.instances).toHaveLength(3)
  expect(onEvent).not.toHaveBeenCalled()
})

it('bounds a hanging auth probe and aborts it when the hook is disabled', async () => {
  vi.mocked(fetchAuthStatus).mockImplementation((signal) => new Promise((_, reject) => {
    signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  }))
  const onEvent = vi.fn()
  const { rerender } = renderHook(({ enabled }) => useWebSocket(onEvent, enabled), {
    initialProps: { enabled: true },
  })
  await act(async () => {
    Socket.instances[0].dispatchEvent(new CloseEvent('close', { code: 1006 }))
    await vi.advanceTimersByTimeAsync(3500)
  })
  expect(Socket.instances).toHaveLength(2)
  act(() => { Socket.instances[1].dispatchEvent(new CloseEvent('close', { code: 1006 })) })
  const signal = vi.mocked(fetchAuthStatus).mock.calls.at(-1)![0]!
  rerender({ enabled: false })
  expect(signal.aborted).toBe(true)
  await act(async () => { await vi.runAllTimersAsync() })
  expect(Socket.instances).toHaveLength(2)
  expect(onEvent).not.toHaveBeenCalled()
})
