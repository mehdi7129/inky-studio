import { useState } from 'react'
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  type DragEndEvent,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import type { QueueEntry } from '../lib/api'
import { photoFileUrl, removeFromQueue, reorderQueue } from '../lib/api'
import { formatAbsolute, formatBytes } from '../lib/format'

interface QueuePanelProps {
  queue: QueueEntry[]
  onChange: () => void
}

export function QueuePanel({ queue, onChange }: QueuePanelProps) {
  const [order, setOrder] = useState<string[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  // Use optimistic order while a drag is in flight, fall back to props otherwise
  const liveIds = order ?? queue.map((entry) => entry.photo.id)
  const entriesByPhotoId = new Map(queue.map((entry) => [entry.photo.id, entry]))
  const orderedEntries = liveIds
    .map((id) => entriesByPhotoId.get(id))
    .filter((entry): entry is QueueEntry => entry !== undefined)

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const ids = liveIds
    const fromIdx = ids.indexOf(String(active.id))
    const toIdx = ids.indexOf(String(over.id))
    if (fromIdx === -1 || toIdx === -1) return

    const newIds = arrayMove(ids, fromIdx, toIdx)
    setOrder(newIds)
    setBusy(true)
    setError(null)
    try {
      await reorderQueue(newIds)
      onChange()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setOrder(null)
    } finally {
      setBusy(false)
    }
  }

  const handleRemove = async (photoId: string) => {
    setBusy(true)
    setError(null)
    try {
      await removeFromQueue(photoId)
      onChange()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  if (queue.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-neutral-300 dark:border-neutral-700 p-10 text-center">
        <p className="font-medium text-neutral-700 dark:text-neutral-200">
          File d'attente vide
        </p>
        <p className="text-sm text-neutral-500 mt-1">
          Ajoute une photo depuis le tableau de bord.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-xl font-semibold">File d'attente</h2>
          <p className="text-sm text-neutral-500">
            {queue.length} photo{queue.length > 1 ? 's' : ''} · glisse pour réordonner
          </p>
        </div>
        {busy && <p className="text-xs text-neutral-500">Mise à jour…</p>}
      </header>

      {error && (
        <div className="rounded-lg border border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950/30 p-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext items={liveIds} strategy={verticalListSortingStrategy}>
          <ul className="space-y-2">
            {orderedEntries.map((entry, idx) => (
              <SortableRow
                key={entry.photo.id}
                entry={entry}
                index={idx}
                onRemove={() => handleRemove(entry.photo.id)}
              />
            ))}
          </ul>
        </SortableContext>
      </DndContext>
    </div>
  )
}

interface SortableRowProps {
  entry: QueueEntry
  index: number
  onRemove: () => void
}

function SortableRow({ entry, index, onRemove }: SortableRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: entry.photo.id,
  })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  return (
    <li
      ref={setNodeRef}
      style={style}
      className="flex items-center gap-4 rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-3"
    >
      <button
        type="button"
        {...attributes}
        {...listeners}
        className="cursor-grab active:cursor-grabbing px-2 py-1 text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300"
        aria-label="Réordonner"
        title="Glisse pour réordonner"
      >
        ⋮⋮
      </button>
      <span className="text-xs font-mono text-neutral-400 w-6 tabular-nums">{index + 1}</span>
      <img
        src={photoFileUrl(entry.photo.id)}
        alt={entry.photo.original_filename}
        className="w-20 h-12 object-cover rounded-md"
        style={{ imageRendering: 'pixelated' }}
      />
      <div className="flex-1 min-w-0">
        <p className="font-medium truncate" title={entry.photo.original_filename}>
          {entry.photo.original_filename}
        </p>
        <p className="text-xs text-neutral-500">
          {formatBytes(entry.photo.size_bytes)} · ajoutée {formatAbsolute(entry.added_at)}
        </p>
      </div>
      <button
        type="button"
        onClick={onRemove}
        className="px-2 py-1 text-sm text-neutral-500 hover:text-red-600 dark:hover:text-red-400"
        aria-label="Retirer de la file"
        title="Retirer de la file"
      >
        ✕
      </button>
    </li>
  )
}
