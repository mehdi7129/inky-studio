import { useCallback, useEffect, useState } from 'react'
import { Uploader } from './components/Uploader'
import { ConverterPanel } from './components/ConverterPanel'
import { fetchDisplayState, fetchHealth, fetchQueue } from './lib/api'
import type { DisplayState, HealthResponse, QueueEntry } from './lib/api'
import { useWebSocket } from './lib/useWebSocket'

type BootStatus = 'loading' | 'ok' | 'error'

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [display, setDisplay] = useState<DisplayState | null>(null)
  const [queue, setQueue] = useState<QueueEntry[]>([])
  const [status, setStatus] = useState<BootStatus>('loading')
  const [error, setError] = useState<string | null>(null)
  const [pickedFile, setPickedFile] = useState<File | null>(null)

  const refreshQueue = useCallback(() => {
    void fetchQueue().then(setQueue).catch(() => {})
  }, [])

  useEffect(() => {
    let cancelled = false
    Promise.all([fetchHealth(), fetchDisplayState(), fetchQueue()])
      .then(([h, d, q]) => {
        if (cancelled) return
        setHealth(h)
        setDisplay(d)
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
        if (event.type === 'queue_updated' || event.type === 'photo_uploaded') {
          refreshQueue()
        }
      },
      [refreshQueue],
    ),
  )

  return (
    <main className="min-h-screen p-6 md:p-10 max-w-5xl mx-auto">
      <header className="mb-8">
        <h1 className="text-3xl font-semibold tracking-tight">Inky Studio</h1>
        {status === 'ok' && display && health && (
          <p className="text-sm text-neutral-500 mt-1">
            {display.model} · {display.width}×{display.height} · {display.colors} couleurs
            {display.is_mock && (
              <span className="ml-2 px-2 py-0.5 rounded bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 text-xs">
                MOCK
              </span>
            )}
            <span className="ml-3 opacity-60">backend v{health.version}</span>
          </p>
        )}
      </header>

      {status === 'loading' && <p className="text-neutral-500">Connexion à l'API…</p>}

      {status === 'error' && (
        <div className="rounded-lg border border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950/30 p-4">
          <p className="font-medium text-red-700 dark:text-red-300">Backend injoignable</p>
          <p className="text-sm text-red-600 dark:text-red-400 mt-1">{error}</p>
          <p className="text-xs text-red-500 mt-2">
            Démarre le backend : <code>cd server && .venv/bin/inky-studio-server</code>
          </p>
        </div>
      )}

      {status === 'ok' && display && (
        <>
          {!pickedFile ? (
            <Uploader onFile={setPickedFile} />
          ) : (
            <ConverterPanel
              file={pickedFile}
              display={display}
              onUploaded={refreshQueue}
              onReset={() => setPickedFile(null)}
            />
          )}

          <section className="mt-10">
            <h2 className="text-sm uppercase tracking-wider text-neutral-500 mb-3">
              File d'attente ({queue.length})
            </h2>
            {queue.length === 0 ? (
              <p className="text-sm text-neutral-500">
                Aucune photo en attente. Ajoutes-en une ci-dessus.
              </p>
            ) : (
              <ul className="flex flex-wrap gap-3">
                {queue.map((entry) => (
                  <li
                    key={entry.id}
                    className="rounded-lg border border-neutral-200 dark:border-neutral-800 overflow-hidden bg-white dark:bg-neutral-900"
                  >
                    <img
                      src={`/api/photos/${entry.photo.id}`}
                      alt={entry.photo.original_filename}
                      className="w-28 h-auto block"
                      style={{ imageRendering: 'pixelated' }}
                    />
                    <div className="p-2 text-xs">
                      <p className="font-medium truncate w-28" title={entry.photo.original_filename}>
                        {entry.photo.original_filename}
                      </p>
                      <p className="text-neutral-500">
                        {Math.round(entry.photo.size_bytes / 1024)} Ko
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </main>
  )
}

export default App
