import { useCallback, useEffect, useRef, useState } from 'react'
import type { HistoryEntry } from '../lib/api'
import {
  clearHistory,
  deleteHistoryEntry,
  fetchHistory,
  photoFileUrl,
  uploadToQueue,
} from '../lib/api'
import { formatAbsolute, formatBytes, formatRelative } from '../lib/format'
import { Icon } from './Icon'

interface HistoryPanelProps {
  onChange: () => void
  revision?: number
}

const SOURCE_LABEL: Record<string, string> = {
  auto: 'Automatique',
  manual_next: 'Suivante',
  manual_previous: 'Précédente',
  recycle: 'Rejouée',
  upload: 'Ajoutée',
}

export function HistoryPanel({ onChange, revision = 0 }: HistoryPanelProps) {
  const [history, setHistory] = useState<HistoryEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [requeueingId, setRequeueingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)
  const requestVersion = useRef(0)
  const invalidateRequests = useCallback(() => { ++requestVersion.current }, [])

  const reload = useCallback(() => {
    const version = ++requestVersion.current
    return fetchHistory(200, 0)
      .then((entries) => {
        if (version === requestVersion.current) {
          setHistory(entries)
          setError(null)
        }
      })
      .catch((err) => {
        if (version === requestVersion.current) {
          setError(err instanceof Error ? err.message : String(err))
        }
      })
  }, [])

  useEffect(() => {
    void reload()
    return invalidateRequests
  }, [revision, reload, invalidateRequests])

  const handleRequeue = async (entry: HistoryEntry) => {
    setRequeueingId(entry.photo.id)
    try {
      const response = await fetch(photoFileUrl(entry.photo.id))
      if (!response.ok) throw new Error(`Impossible de récupérer la photo (HTTP ${response.status})`)
      const blob = await response.blob()
      await uploadToQueue(blob, entry.photo.original_filename)
      onChange()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setRequeueingId(null)
    }
  }

  const handleDelete = async (entry: HistoryEntry) => {
    ++requestVersion.current
    setDeletingId(entry.id)
    try {
      await deleteHistoryEntry(entry.id)
      await reload()
      onChange()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setDeletingId(null)
    }
  }

  const handleClearAll = async () => {
    ++requestVersion.current
    try {
      await clearHistory()
      setConfirmClear(false)
      await reload()
      onChange()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  if (error && !history) {
    return <p className="bento-alert" role="alert">Erreur : {error}</p>
  }
  if (!history) {
    return <p className="bento-card p-8 text-sm text-neutral-500" role="status">Chargement…</p>
  }

  return (
    <div className="space-y-7">
      <header className="flex flex-wrap items-end justify-between gap-5">
        <div>
          <p className="bento-eyebrow mb-3">Les souvenirs restent</p>
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Déjà sur votre cadre.</h1>
          <p className="mt-2 text-sm text-neutral-500 sm:text-base">
            Retrouvez une photo, offrez-lui un nouveau tour.
          </p>
        </div>
        {history.length > 0 && (
          confirmClear ? (
            <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-red-100 bg-red-50/60 p-3 text-sm">
              <span className="mr-1 text-red-700">Tout supprimer ?</span>
              <button
                type="button"
                onClick={handleClearAll}
                className="bento-button border border-red-600 bg-red-600 text-white hover:bg-red-700"
              >
                Confirmer
              </button>
              <button
                type="button"
                onClick={() => setConfirmClear(false)}
                className="bento-button bento-button-secondary"
              >
                Annuler
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmClear(true)}
              className="bento-button bento-button-secondary text-neutral-500 hover:text-red-600"
            >
              <Icon name="trash" size={16} />
              Tout supprimer
            </button>
          )
        )}
      </header>

      {error && <p className="bento-alert" role="alert">{error}</p>}

      {history.length === 0 ? (
        <section className="bento-card flex min-h-80 flex-col items-center justify-center px-6 py-14 text-center">
          <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-amber-50 text-amber-600">
            <Icon name="history" size={25} />
          </div>
          <h2 className="text-xl font-semibold tracking-tight">Aucun historique pour l'instant</h2>
          <p className="mt-2 max-w-sm text-sm leading-relaxed text-neutral-500">
            Les photos passent ici une fois affichées à l'écran.
          </p>
        </section>
      ) : (
        <>
          <div className="flex items-center gap-3">
            <h2 className="bento-panel-heading">Au fil des jours</h2>
            <span className="bento-badge">{history.length} photo{history.length > 1 ? 's' : ''}</span>
          </div>
          <ul className="grid grid-cols-1 gap-5 min-[480px]:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {history.map((entry) => (
              <li key={entry.id} className="bento-card overflow-hidden p-3">
                <img
                  src={photoFileUrl(entry.photo.id)}
                  alt={entry.photo.original_filename}
                  loading="lazy"
                  className="aspect-[5/4] w-full rounded-xl bg-neutral-100 object-cover"
                />
                <div className="px-1 pb-1 pt-4">
                  <p className="truncate text-sm font-medium" title={entry.photo.original_filename}>
                    {entry.photo.original_filename}
                  </p>
                  <p className="mt-1 text-xs text-neutral-500" title={formatAbsolute(entry.displayed_at)}>
                    {formatRelative(entry.displayed_at)}
                  </p>
                  <div className="mt-4 flex items-center justify-between gap-2 text-[11px] text-neutral-500">
                    <span className="rounded-full bg-neutral-100 px-2.5 py-1">{SOURCE_LABEL[entry.source] ?? entry.source}</span>
                    <span>{formatBytes(entry.photo.size_bytes)}</span>
                  </div>
                  <div className="mt-4 flex gap-2 border-t border-neutral-100 pt-3">
                    <button
                      type="button"
                      onClick={() => handleRequeue(entry)}
                      disabled={requeueingId === entry.photo.id}
                      className="bento-button bento-button-secondary min-w-0 flex-1 px-2 text-xs"
                    >
                      <Icon name="plus" size={15} />
                      {requeueingId === entry.photo.id ? 'Ajout…' : 'Remettre en file'}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(entry)}
                      disabled={deletingId === entry.id}
                      aria-label={`Supprimer ${entry.photo.original_filename} de l'historique`}
                      title="Supprimer de l'historique"
                      className="bento-button bento-button-quiet w-10 shrink-0 px-0 text-neutral-500 hover:bg-red-50 hover:text-red-600"
                    >
                      {deletingId === entry.id ? '…' : <Icon name="trash" size={16} />}
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
