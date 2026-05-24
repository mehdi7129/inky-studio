import { useEffect, useState } from 'react'
import type { HistoryEntry } from '../lib/api'
import { fetchHistory, photoFileUrl, uploadToQueue } from '../lib/api'
import { formatAbsolute, formatBytes, formatRelative } from '../lib/format'

interface HistoryPanelProps {
  onChange: () => void
}

const SOURCE_LABEL: Record<string, string> = {
  auto: 'auto',
  manual_next: 'next',
  manual_previous: 'prev',
  recycle: 'recycle',
  upload: 'upload',
}

export function HistoryPanel({ onChange }: HistoryPanelProps) {
  const [history, setHistory] = useState<HistoryEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [requeueingId, setRequeueingId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchHistory(200, 0)
      .then((entries) => {
        if (!cancelled) setHistory(entries)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  const handleRequeue = async (entry: HistoryEntry) => {
    setRequeueingId(entry.photo.id)
    try {
      const response = await fetch(photoFileUrl(entry.photo.id))
      const blob = await response.blob()
      await uploadToQueue(blob, entry.photo.original_filename)
      onChange()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setRequeueingId(null)
    }
  }

  if (error && !history) {
    return <p className="text-red-600 dark:text-red-400 text-sm">Erreur : {error}</p>
  }
  if (!history) {
    return <p className="text-neutral-500 text-sm">Chargement…</p>
  }
  if (history.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-neutral-300 dark:border-neutral-700 p-10 text-center">
        <p className="font-medium text-neutral-700 dark:text-neutral-200">
          Aucun historique pour l'instant
        </p>
        <p className="text-sm text-neutral-500 mt-1">
          Les photos passent ici une fois affichées à l'écran.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <header>
        <h2 className="text-xl font-semibold">Historique</h2>
        <p className="text-sm text-neutral-500">{history.length} entrées</p>
      </header>

      {error && (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      )}

      <ul className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
        {history.map((entry) => (
          <li
            key={entry.id}
            className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 overflow-hidden"
          >
            <img
              src={photoFileUrl(entry.photo.id)}
              alt={entry.photo.original_filename}
              className="w-full aspect-[5/3] object-cover"
              style={{ imageRendering: 'pixelated' }}
            />
            <div className="p-3 space-y-2">
              <p className="text-xs font-medium truncate" title={entry.photo.original_filename}>
                {entry.photo.original_filename}
              </p>
              <div className="flex items-center justify-between text-[10px] uppercase tracking-wider text-neutral-500">
                <span>{SOURCE_LABEL[entry.source] ?? entry.source}</span>
                <span title={formatAbsolute(entry.displayed_at)}>
                  {formatRelative(entry.displayed_at)}
                </span>
              </div>
              <p className="text-[10px] text-neutral-500">
                {formatBytes(entry.photo.size_bytes)}
              </p>
              <button
                type="button"
                onClick={() => handleRequeue(entry)}
                disabled={requeueingId === entry.photo.id}
                className="w-full text-xs px-2 py-1.5 rounded-md border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-800 disabled:opacity-50"
              >
                {requeueingId === entry.photo.id ? '…' : 'Remettre en file'}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
