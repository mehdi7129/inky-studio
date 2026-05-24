/**
 * Minimal WebSocket hook with auto-reconnect.
 *
 * Used to keep the UI in sync with backend state changes (queue updates,
 * display changes, settings changes). Reconnects with exponential backoff
 * up to 30 s so a dev-server restart doesn't permanently break the page.
 */
import { useEffect, useRef } from 'react'

export interface EventMessage {
  type: string
  payload?: Record<string, unknown>
}

export function useWebSocket(onEvent: (event: EventMessage) => void) {
  const handlerRef = useRef(onEvent)
  handlerRef.current = onEvent

  useEffect(() => {
    let socket: WebSocket | null = null
    let cancelled = false
    let backoffMs = 500

    const connect = () => {
      if (cancelled) return
      const wsUrl = new URL('/api/ws', window.location.origin)
      wsUrl.protocol = wsUrl.protocol === 'https:' ? 'wss:' : 'ws:'
      socket = new WebSocket(wsUrl.toString())

      socket.addEventListener('open', () => {
        backoffMs = 500
      })
      socket.addEventListener('message', (msg) => {
        try {
          const data = JSON.parse(msg.data) as EventMessage
          handlerRef.current(data)
        } catch {
          // Ignore malformed messages — the server only emits JSON.
        }
      })
      socket.addEventListener('close', () => {
        if (cancelled) return
        setTimeout(connect, backoffMs)
        backoffMs = Math.min(backoffMs * 2, 30_000)
      })
      socket.addEventListener('error', () => {
        socket?.close()
      })
    }

    connect()

    return () => {
      cancelled = true
      socket?.close()
    }
  }, [])
}
