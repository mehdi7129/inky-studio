import { useCallback, useEffect, useState } from 'react'
import { Dashboard } from './components/Dashboard'
import { HistoryPanel } from './components/HistoryPanel'
import { Layout, type TabId } from './components/Layout'
import { QueuePanel } from './components/QueuePanel'
import { SettingsPanel } from './components/SettingsPanel'
import { fetchHealth, fetchQueue, fetchState } from './lib/api'
import type { DisplayState, HealthResponse, QueueEntry } from './lib/api'
import { useWebSocket } from './lib/useWebSocket'

type BootStatus = 'loading' | 'ok' | 'error'

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [state, setState] = useState<DisplayState | null>(null)
  const [queue, setQueue] = useState<QueueEntry[]>([])
  const [status, setStatus] = useState<BootStatus>('loading')
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<TabId>('dashboard')

  const refresh = useCallback(() => {
    void Promise.all([fetchState(), fetchQueue()])
      .then(([s, q]) => {
        setState(s)
        setQueue(q)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    let cancelled = false
    Promise.all([fetchHealth(), fetchState(), fetchQueue()])
      .then(([h, s, q]) => {
        if (cancelled) return
        setHealth(h)
        setState(s)
        setQueue(q)
        setStatus('ok')
      })
      .catch((err: Error) => {
        if (cancelled) return
        setError(err.message)
        setStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [])

  useWebSocket(
    useCallback(
      (event) => {
        if (
          event.type === 'queue_updated' ||
          event.type === 'photo_uploaded' ||
          event.type === 'display_changed' ||
          event.type === 'settings_changed' ||
          event.type === 'photo_deleted'
        ) {
          refresh()
        }
      },
      [refresh],
    ),
  )

  // Tick once a minute so "il y a 3 min" labels stay fresh without a full refresh
  useEffect(() => {
    const id = setInterval(() => setState((s) => (s ? { ...s } : s)), 60_000)
    return () => clearInterval(id)
  }, [])

  if (status === 'loading') {
    return (
      <main className="min-h-screen flex items-center justify-center text-neutral-500">
        Connexion à l'API…
      </main>
    )
  }

  if (status === 'error' || !state) {
    return (
      <main className="min-h-screen p-6 max-w-2xl mx-auto pt-20">
        <div className="rounded-lg border border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950/30 p-6">
          <h1 className="text-xl font-semibold text-red-700 dark:text-red-300">
            Backend injoignable
          </h1>
          <p className="text-sm text-red-600 dark:text-red-400 mt-2">{error}</p>
          <p className="text-xs text-red-500 mt-4">
            Démarre le backend avec <code>cd server && .venv/bin/inky-studio-server</code>
          </p>
        </div>
      </main>
    )
  }

  return (
    <Layout
      activeTab={tab}
      onTabChange={setTab}
      display={state.display}
      health={health}
      queueCount={queue.length}
    >
      {tab === 'dashboard' && <Dashboard state={state} queue={queue} onChange={refresh} />}
      {tab === 'queue' && <QueuePanel queue={queue} onChange={refresh} />}
      {tab === 'settings' && <SettingsPanel onChange={refresh} />}
      {tab === 'history' && <HistoryPanel onChange={refresh} />}
    </Layout>
  )
}

export default App
