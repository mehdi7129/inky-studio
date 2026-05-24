import { useState } from 'react'
import type { DisplayState, QueueEntry } from '../lib/api'
import { photoFileUrl, triggerNext, triggerPrevious } from '../lib/api'
import { formatAbsolute, formatBytes, formatRelative } from '../lib/format'
import { Uploader } from './Uploader'
import { ConverterPanel } from './ConverterPanel'

interface DashboardProps {
  state: DisplayState
  queue: QueueEntry[]
  onChange: () => void
}

const SOURCE_LABEL: Record<string, string> = {
  auto: 'rotation automatique',
  manual_next: 'bouton suivant',
  manual_previous: 'bouton précédent',
  recycle: 'recyclage historique',
  upload: 'upload',
}

export function Dashboard({ state, queue, onChange }: DashboardProps) {
  const [pickedFile, setPickedFile] = useState<File | null>(null)
  const [navBusy, setNavBusy] = useState(false)
  const { display, current } = state

  const handleNext = async () => {
    setNavBusy(true)
    try {
      await triggerNext()
      onChange()
    } finally {
      setNavBusy(false)
    }
  }

  const handlePrevious = async () => {
    setNavBusy(true)
    try {
      await triggerPrevious()
      onChange()
    } finally {
      setNavBusy(false)
    }
  }

  return (
    <div className="space-y-10">
      <section className="grid lg:grid-cols-[2fr_1fr] gap-6">
        <article className="rounded-2xl border border-neutral-200 dark:border-neutral-800 overflow-hidden bg-white dark:bg-neutral-900">
          <header className="px-5 py-3 border-b border-neutral-200 dark:border-neutral-800 flex items-center justify-between">
            <h2 className="text-xs uppercase tracking-wider text-neutral-500">
              Actuellement à l'écran
            </h2>
            {current && (
              <span className="text-xs text-neutral-500">
                {SOURCE_LABEL[current.source] ?? current.source}
              </span>
            )}
          </header>
          <div className="bg-neutral-100 dark:bg-neutral-800 flex items-center justify-center aspect-[5/3] relative">
            {current ? (
              <img
                src={photoFileUrl(current.photo.id)}
                alt={current.photo.original_filename}
                className="max-w-full max-h-full object-contain"
                style={{ imageRendering: 'pixelated' }}
              />
            ) : (
              <div className="text-center text-neutral-500 p-8">
                <p className="text-lg font-medium mb-1">Aucune photo affichée</p>
                <p className="text-sm">
                  Le service n'a encore poussé aucune image sur l'écran.
                </p>
              </div>
            )}
          </div>
          <footer className="px-5 py-3 border-t border-neutral-200 dark:border-neutral-800 flex items-center justify-between gap-3 flex-wrap">
            <div className="min-w-0 flex-1">
              {current ? (
                <>
                  <p className="font-medium truncate" title={current.photo.original_filename}>
                    {current.photo.original_filename}
                  </p>
                  <p className="text-xs text-neutral-500">
                    {formatRelative(current.displayed_at)} ·{' '}
                    {formatAbsolute(current.displayed_at)} ·{' '}
                    {formatBytes(current.photo.size_bytes)}
                  </p>
                </>
              ) : (
                <p className="text-sm text-neutral-500">—</p>
              )}
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handlePrevious}
                disabled={navBusy}
                className="px-3 py-1.5 rounded-md text-sm border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-800 disabled:opacity-50"
                title="Photo précédente (depuis l'historique)"
              >
                ← Précédente
              </button>
              <button
                type="button"
                onClick={handleNext}
                disabled={navBusy}
                className="px-3 py-1.5 rounded-md text-sm border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-800 disabled:opacity-50"
                title="Photo suivante (pop la queue ou recycle)"
              >
                Suivante →
              </button>
            </div>
          </footer>
        </article>

        <aside className="rounded-2xl border border-neutral-200 dark:border-neutral-800 p-5 bg-white dark:bg-neutral-900 space-y-4">
          <h2 className="text-xs uppercase tracking-wider text-neutral-500">Écran</h2>
          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-neutral-500">Modèle</dt>
            <dd className="font-medium">
              {display.model}
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
            <dt className="text-neutral-500">Mode</dt>
            <dd className="font-medium">{display.color_mode}</dd>
          </dl>

          <hr className="border-neutral-200 dark:border-neutral-800" />

          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-neutral-500">Queue</dt>
            <dd className="font-medium">
              {state.queue_count === 0
                ? 'vide'
                : `${state.queue_count} photo${state.queue_count > 1 ? 's' : ''}`}
            </dd>
            <dt className="text-neutral-500">Prochain</dt>
            <dd className="font-medium">{formatRelative(state.next_change_at)}</dd>
          </dl>
        </aside>
      </section>

      <section>
        <h2 className="text-sm uppercase tracking-wider text-neutral-500 mb-3">
          Ajouter une photo
        </h2>
        {!pickedFile ? (
          <Uploader onFile={setPickedFile} />
        ) : (
          <ConverterPanel
            file={pickedFile}
            display={display}
            onUploaded={onChange}
            onReset={() => setPickedFile(null)}
          />
        )}
      </section>

      {queue.length > 0 && (
        <section>
          <h2 className="text-sm uppercase tracking-wider text-neutral-500 mb-3">
            Aperçu de la file ({queue.length})
          </h2>
          <ul className="flex flex-wrap gap-3">
            {queue.slice(0, 6).map((entry) => (
              <li
                key={entry.id}
                className="rounded-lg border border-neutral-200 dark:border-neutral-800 overflow-hidden bg-white dark:bg-neutral-900"
              >
                <img
                  src={photoFileUrl(entry.photo.id)}
                  alt={entry.photo.original_filename}
                  className="w-28 h-auto block"
                  style={{ imageRendering: 'pixelated' }}
                />
                <div className="p-2 text-xs">
                  <p className="font-medium truncate w-28" title={entry.photo.original_filename}>
                    {entry.photo.original_filename}
                  </p>
                  <p className="text-neutral-500">{formatBytes(entry.photo.size_bytes)}</p>
                </div>
              </li>
            ))}
            {queue.length > 6 && (
              <li className="rounded-lg border border-dashed border-neutral-300 dark:border-neutral-700 p-3 w-28 flex items-center justify-center text-xs text-neutral-500">
                + {queue.length - 6} autres
              </li>
            )}
          </ul>
        </section>
      )}
    </div>
  )
}
