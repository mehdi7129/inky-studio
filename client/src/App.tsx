import { useCallback, useEffect, useRef, useState } from 'react'
import { Dashboard } from './components/Dashboard'
import { HistoryPanel } from './components/HistoryPanel'
import { Layout, type TabId } from './components/Layout'
import { LoginScreen } from './components/LoginScreen'
import { QueuePanel } from './components/QueuePanel'
import { SettingsPanel } from './components/SettingsPanel'
import { ApiError, fetchAuthStatus, fetchHealth, fetchQueue, fetchState, logout } from './lib/api'
import type { AuthStatus, DisplayState, HealthResponse, QueueEntry } from './lib/api'
import { useWebSocket } from './lib/useWebSocket'
import { Icon } from './components/Icon'

type BootStatus = 'auth-check' | 'login-required' | 'loading' | 'ok' | 'error'

function App() {
  const [bootStatus, setBootStatus] = useState<BootStatus>('auth-check')
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [state, setState] = useState<DisplayState | null>(null)
  const [queue, setQueue] = useState<QueueEntry[]>([])
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<TabId>('dashboard')
  const [historyRevision, setHistoryRevision] = useState(0)
  const [settingsRevision, setSettingsRevision] = useState(0)
  const requestVersion = useRef(0)

  const refresh = useCallback(() => {
    const version = ++requestVersion.current
    return Promise.all([fetchState(), fetchQueue()])
      .then(([s, q]) => {
        if (version !== requestVersion.current) return
        setState(s)
        setQueue(q)
        setError(null)
      })
      .catch((err: Error) => {
        if (version !== requestVersion.current) return
        if (err instanceof ApiError && err.status === 401) {
          setBootStatus('login-required')
        } else {
          setError(err.message)
        }
      })
  }, [])

  const loadAll = useCallback(() => {
    const version = ++requestVersion.current
    setError(null)
    setBootStatus('loading')
    Promise.all([fetchHealth(), fetchState(), fetchQueue()])
      .then(([h, s, q]) => {
        if (version !== requestVersion.current) return
        setHealth(h)
        setState(s)
        setQueue(q)
        setBootStatus('ok')
      })
      .catch((err: Error) => {
        if (version !== requestVersion.current) return
        setError(err.message)
        setBootStatus(err instanceof ApiError && err.status === 401 ? 'login-required' : 'error')
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
        if (event.type === 'auth_required') {
          ++requestVersion.current
          setBootStatus('login-required')
          return
        }
        if (event.type === 'hello' || event.type === 'settings_changed') {
          setSettingsRevision((revision) => revision + 1)
        }
        if (event.type === 'hello' || event.type === 'display_changed' ||
            event.type === 'history_changed' || event.type === 'photo_deleted') {
          setHistoryRevision((revision) => revision + 1)
        }
        if (
          event.type === 'hello' ||
          event.type === 'queue_updated' ||
          event.type === 'photo_uploaded' ||
          event.type === 'display_changed' ||
          event.type === 'settings_changed' ||
          event.type === 'photo_deleted' ||
          event.type === 'history_changed'
        ) {
          refresh()
        }
      },
      [refresh, bootStatus],
    ),
    bootStatus === 'ok',
  )

  useEffect(() => {
    const id = setInterval(() => setState((s) => (s ? { ...s } : s)), 60_000)
    return () => clearInterval(id)
  }, [])

  const handleLogout = async () => {
    ++requestVersion.current
    try {
      await logout()
    } catch {
      /* ignore — we reset client state anyway */
    }
    setAuthStatus((prev) => (prev ? { ...prev, authenticated: false } : prev))
    ++requestVersion.current
    setHealth(null)
    setState(null)
    setQueue([])
    setBootStatus('login-required')
  }

  if (bootStatus === 'auth-check') {
    return (
      <main className="studio-boot">
        <div className="studio-boot-card bento-card" role="status">
          <p className="studio-brand mb-6"><span className="studio-brand-mark" aria-hidden="true" />Inky Studio</p>
          <p className="text-sm text-neutral-500">Vérification de l'authentification…</p>
          <div className="studio-boot-line mt-5 w-3/4" aria-hidden="true" />
          <div className="studio-boot-line mt-3 w-1/2" aria-hidden="true" />
        </div>
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
      <main className="studio-boot">
        <div className="studio-boot-card bento-card" role="status">
          <p className="studio-brand mb-6"><span className="studio-brand-mark" aria-hidden="true" />Inky Studio</p>
          <p className="text-sm text-neutral-500">Chargement de votre cadre…</p>
          <div className="studio-boot-line mt-5 w-3/4" aria-hidden="true" />
          <div className="studio-boot-line mt-3 w-1/2" aria-hidden="true" />
        </div>
      </main>
    )
  }

  if (bootStatus === 'error' || !state) {
    return (
      <main className="studio-boot">
        <div className="studio-boot-card bento-card">
          <h1 className="text-xl font-semibold mb-3">Le cadre est indisponible</h1>
          <p role="alert" className="bento-alert">{error}</p>
          <button type="button" className="bento-button bento-button-primary mt-5" onClick={() => window.location.reload()}>
            <Icon name="refresh" size={16} />Réessayer
          </button>
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
      {error && <p role="alert" className="bento-alert mb-4">{error}</p>}
      {tab === 'dashboard' && <Dashboard state={state} queue={queue} onChange={refresh} onOpenQueue={() => setTab('queue')} onOpenSettings={() => setTab('settings')} />}
      {tab === 'queue' && <QueuePanel queue={queue} onChange={refresh} />}
      {tab === 'settings' && <SettingsPanel onChange={refresh} health={health} revision={settingsRevision} />}
      {tab === 'history' && <HistoryPanel onChange={refresh} revision={historyRevision} />}
    </Layout>
  )
}

export default App
