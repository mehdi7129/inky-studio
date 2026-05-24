import { useEffect, useState } from 'react'
import { fetchHealth, fetchDisplayState } from './lib/api'
import type { DisplayState, HealthResponse } from './lib/api'

type Status = 'loading' | 'ok' | 'error'

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [display, setDisplay] = useState<DisplayState | null>(null)
  const [status, setStatus] = useState<Status>('loading')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([fetchHealth(), fetchDisplayState()])
      .then(([h, d]) => {
        if (cancelled) return
        setHealth(h)
        setDisplay(d)
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

  return (
    <main className="min-h-screen flex flex-col items-center justify-center p-8">
      <div className="max-w-2xl w-full">
        <header className="mb-8 text-center">
          <h1 className="text-4xl font-semibold tracking-tight mb-2">Inky Studio</h1>
          <p className="text-neutral-500 dark:text-neutral-400">
            Phase 0 — scaffolding. La vraie UI arrive en Phase 2.
          </p>
        </header>

        <section className="rounded-xl border border-neutral-200 dark:border-neutral-800 p-6 bg-white/50 dark:bg-neutral-900/50 backdrop-blur">
          <h2 className="font-medium text-sm uppercase tracking-wider text-neutral-500 mb-4">
            État du backend
          </h2>

          {status === 'loading' && (
            <p className="text-neutral-500">Connexion à l'API…</p>
          )}

          {status === 'error' && (
            <div className="text-red-600 dark:text-red-400">
              <p className="font-medium">Backend injoignable</p>
              <p className="text-sm mt-1 opacity-80">{error}</p>
              <p className="text-xs mt-2 opacity-60">
                Démarre le backend : <code className="px-1.5 py-0.5 rounded bg-neutral-100 dark:bg-neutral-800">cd server &amp;&amp; inky-studio-server</code>
              </p>
            </div>
          )}

          {status === 'ok' && health && display && (
            <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
              <dt className="text-neutral-500">Backend</dt>
              <dd className="font-medium">v{health.version} · {health.status}</dd>

              <dt className="text-neutral-500">Modèle écran</dt>
              <dd className="font-medium">
                {display.model}{' '}
                {display.is_mock && (
                  <span className="ml-2 text-xs px-2 py-0.5 rounded bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
                    MOCK
                  </span>
                )}
              </dd>

              <dt className="text-neutral-500">Résolution</dt>
              <dd className="font-medium">{display.width} × {display.height}</dd>

              <dt className="text-neutral-500">Couleurs</dt>
              <dd className="font-medium">{display.colors}</dd>

              <dt className="text-neutral-500">Mode couleur</dt>
              <dd className="font-medium">{display.color_mode}</dd>
            </dl>
          )}
        </section>
      </div>
    </main>
  )
}

export default App
