/**
 * Minimal WebSocket hook with auto-reconnect.
 *
 * Used to keep the UI in sync with backend state changes (queue updates,
 * display changes, settings changes). Reconnects with exponential backoff
 * up to 30 s so a dev-server restart doesn't permanently break the page.
 */
import { useEffect, useRef } from 'react'
import { fetchAuthStatus } from './api'

export interface EventMessage {
  type: string
  payload?: Record<string, unknown>
}

export function useWebSocket(onEvent: (event: EventMessage) => void, enabled = true) {
  const handlerRef = useRef(onEvent)

  // Keep the latest handler without re-opening the socket on every render.
  useEffect(() => {
    handlerRef.current = onEvent
  })

  useEffect(() => {
    if (!enabled) return
    let socket: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout> | undefined
    let probeTimeout: ReturnType<typeof setTimeout> | undefined
    let authProbe: AbortController | null = null
    let cancelled = false
    let backoffMs = 500

    const connect = () => {
      if (cancelled) return
      const wsUrl = new URL('/api/ws', window.location.origin)
      wsUrl.protocol = wsUrl.protocol === 'https:' ? 'wss:' : 'ws:'
      const connection = new WebSocket(wsUrl.toString())
      socket = connection

      socket.addEventListener('open', () => {
        backoffMs = 500
      })
      socket.addEventListener('message', (msg) => {
        if (cancelled) return
        try {
          const data = JSON.parse(msg.data) as EventMessage
          handlerRef.current(data)
        } catch {
          // Ignore malformed messages — the server only emits JSON.
        }
      })
      socket.addEventListener('close', async (event) => {
        if (cancelled) return
        if (event.code === 1008) {
          handlerRef.current({ type: 'auth_required' })
          return
        }
        // A rejected handshake becomes 1006 in browsers, even if the server
        // requested 1008. Recheck HTTP auth before retrying with a stale cookie.
        const controller = new AbortController()
        authProbe = controller
        probeTimeout = setTimeout(() => controller.abort(), 3000)
        try {
          const auth = await fetchAuthStatus(controller.signal)
          if (cancelled) return
          if (!auth.authenticated) {
            handlerRef.current({ type: 'auth_required' })
            return
          }
        } catch {
          // Offline/restarting: preserve the ordinary bounded reconnect loop.
        } finally {
          clearTimeout(probeTimeout)
          authProbe = null
        }
        if (!cancelled) {
          retry = setTimeout(connect, backoffMs)
          backoffMs = Math.min(backoffMs * 2, 30_000)
        }
      })
      socket.addEventListener('error', () => {
        connection.close()
      })
    }

    connect()

    return () => {
      cancelled = true
      clearTimeout(retry)
      clearTimeout(probeTimeout)
      authProbe?.abort()
      socket?.close()
    }
  }, [enabled])
}
