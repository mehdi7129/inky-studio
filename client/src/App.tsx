import { useCallback, useEffect, useState } from 'react'
import { Dashboard } from './components/Dashboard'
import { HistoryPanel } from './components/HistoryPanel'
import { Layout, type TabId } from './components/Layout'
import { LoginScreen } from './components/LoginScreen'
import { QueuePanel } from './components/QueuePanel'
import { SettingsPanel } from './components/SettingsPanel'
import { fetchAuthStatus, fetchHealth, fetchQueue, fetchState, logout } from './lib/api'
import type { AuthStatus, DisplayState, HealthResponse, QueueEntry } from './lib/api'
import { useWebSocket } from './lib/useWebSocket'

type BootStatus = 'auth-check' | 'login-required' | 'loading' | 'ok' | 'error'

function App() {
  const [bootStatus, setBootStatus] = useState<BootStatus>('auth-check')
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [state, setState] = useState<DisplayState | null>(null)
  const [queue, setQueue] = useState<QueueEntry[]>([])
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

  const loadAll = useCallback(() => {
    setBootStatus('loading')
    Promise.all([fetchHealth(), fetchState(), fetchQueue()])
      .then(([h, s, q]) => {
        setHealth(h)
        setState(s)
        setQueue(q)
        setBootStatus('ok')
      })
      .catch((err: Error) => {
        setError(err.message)
        setBootStatus('error')
      })
  }, [])

  useEffect(() => {
    fetchAuthStatus()
      .then((status) => {
        setAuthStatus(status)
        if (status.authenticated) {
          loadAll()
        } else {
          setBootStatus('login-required')
        }
      })
      .catch((err: Error) => {
        setError(err.message)
        setBootStatus('error')
      })
  }, [loadAll])

  useWebSocket(
    useCallback(
      (event) => {
        if (bootStatus !== 'ok') return
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
      [refresh, bootStatus],
    ),
  )

  useEffect(() => {
    const id = setInterval(() => setState((s) => (s ? { ...s } : s)), 60_000)
    return () => clearInterval(id)
  }, [])

  const handleLogout = async () => {
    try {
      await logout()
    } catch {
      /* ignore — we reset client state anyway */
    }
    setAuthStatus((prev) => (prev ? { ...prev, authenticated: false } : prev))
    setHealth(null)
    setState(null)
    setQueue([])
    setBootStatus('login-required')
  }

  if (bootStatus === 'auth-check') {
    return (
      <main className="min-h-screen flex items-center justify-center text-neutral-500">
        Vérification de l'authentification…
      </main>
    )
  }

  if (bootStatus === 'login-required') {
    return (
      <LoginScreen
        onSuccess={() => {
          setAuthStatus((prev) =>
            prev ? { ...prev, authenticated: true } : { authenticated: true, auth_required: true },
          )
          loadAll()
        }}
      />
    )
  }

  if (bootStatus === 'loading') {
    return (
      <main className="min-h-screen flex items-center justify-center text-neutral-500">
        Connexion à l'API…
      </main>
    )
  }

  if (bootStatus === 'error' || !state) {
    return (
      <main className="min-h-screen p-6 max-w-2xl mx-auto pt-20">
        <div className="rounded-lg border border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950/30 p-6">
          <h1 className="text-xl font-semibold text-red-700 dark:text-red-300">
            Erreur
          </h1>
          <p className="text-sm text-red-600 dark:text-red-400 mt-2">{error}</p>
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
      authRequired={authStatus?.auth_required ?? false}
      onLogout={handleLogout}
    >
      {tab === 'dashboard' && <Dashboard state={state} queue={queue} onChange={refresh} />}
      {tab === 'queue' && <QueuePanel queue={queue} onChange={refresh} />}
      {tab === 'settings' && <SettingsPanel onChange={refresh} />}
      {tab === 'history' && <HistoryPanel onChange={refresh} />}
    </Layout>
  )
}

export default App
