import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useWebSocket } from './useWebSocket'

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

it('reconnects after an ordinary disconnect and delivers the new hello', () => {
  const onEvent = vi.fn()
  renderHook(() => useWebSocket(onEvent))
  act(() => {
    Socket.instances[0].dispatchEvent(new CloseEvent('close', { code: 1006 }))
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
