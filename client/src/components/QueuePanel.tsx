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
import { Icon } from './Icon'

interface QueuePanelProps {
  queue: QueueEntry[]
  onChange: () => void | Promise<void>
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
    if (busy) return
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
      await onChange()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setOrder(null)
    } finally {
      setOrder(null)
      setBusy(false)
    }
  }

  const handleRemove = async (photoId: string) => {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      await removeFromQueue(photoId)
      await onChange()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-7">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="bento-eyebrow mb-3">Votre collection</p>
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Les prochaines vues.</h1>
          <p className="mt-2 text-sm text-neutral-500 sm:text-base">
            Vos photos attendent leur tour. À vous de choisir l'ordre.
          </p>
        </div>
        <span className="bento-badge">{queue.length} photo{queue.length > 1 ? 's' : ''}</span>
      </header>

      {error && <div className="bento-alert" role="alert">{error}</div>}

      {queue.length === 0 ? (
        <section className="bento-card flex min-h-80 flex-col items-center justify-center px-6 py-14 text-center">
          <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-50 text-blue-600">
            <Icon name="image" size={25} />
          </div>
          <h2 className="text-xl font-semibold tracking-tight">File d'attente vide</h2>
          <p className="mt-2 max-w-sm text-sm leading-relaxed text-neutral-500">
            Ajoute une photo depuis le tableau de bord.
          </p>
        </section>
      ) : (
        <section className="bento-card p-4 sm:p-6" aria-label="File d'attente" aria-busy={busy}>
          <div className="mb-5 flex flex-wrap items-center justify-between gap-2">
            <h2 className="bento-panel-heading">Dans l'ordre d'affichage</h2>
            <p className="text-xs text-neutral-500" role="status">
              {busy ? 'Mise à jour…' : 'Glissez les photos pour changer leur ordre'}
            </p>
          </div>
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
            <SortableContext items={liveIds} strategy={verticalListSortingStrategy}>
              <ul className="space-y-3">
                {orderedEntries.map((entry, idx) => (
                  <SortableRow
                    key={entry.photo.id}
                    entry={entry}
                    index={idx}
                    disabled={busy}
                    onRemove={() => handleRemove(entry.photo.id)}
                  />
                ))}
              </ul>
            </SortableContext>
          </DndContext>
          <p className="mt-5 text-xs leading-relaxed text-neutral-500">
            Au clavier : sélectionnez la poignée, appuyez sur Espace, puis utilisez les flèches.
          </p>
        </section>
      )}
    </div>
  )
}

interface SortableRowProps {
  entry: QueueEntry
  index: number
  onRemove: () => void
  disabled: boolean
}

function SortableRow({ entry, index, onRemove, disabled }: SortableRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: entry.photo.id,
    disabled,
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
      className="flex items-center gap-2 rounded-2xl border border-neutral-200/70 bg-white p-2.5 transition-shadow sm:gap-4 sm:p-3"
    >
      <button
        type="button"
        disabled={disabled}
        {...attributes}
        {...listeners}
        className="bento-button bento-button-quiet h-11 w-8 shrink-0 touch-none cursor-grab px-0 text-neutral-500 active:cursor-grabbing sm:w-10"
        aria-label={`Réordonner ${entry.photo.original_filename}`}
        title="Glisse pour réordonner"
      >
        <Icon name="grip" size={18} />
      </button>
      <span className="hidden w-5 shrink-0 text-center text-xs tabular-nums text-neutral-400 sm:block">{String(index + 1).padStart(2, '0')}</span>
      <img
        src={photoFileUrl(entry.photo.id)}
        alt={entry.photo.original_filename}
        className="h-16 w-20 shrink-0 rounded-xl object-cover sm:h-20 sm:w-32"
      />
      <div className="flex-1 min-w-0">
        <p className="truncate text-sm font-medium sm:text-base" title={entry.photo.original_filename}>
          {entry.photo.original_filename}
        </p>
        <p className="mt-1 truncate text-xs text-neutral-500">
          <span className="hidden sm:inline">{formatBytes(entry.photo.size_bytes)} · </span>
          ajoutée {formatAbsolute(entry.added_at)}
        </p>
        {index === 0 && <span className="mt-2 inline-block text-[11px] font-medium text-blue-600">À suivre sur le cadre</span>}
      </div>
      <button
        type="button"
        onClick={onRemove}
        disabled={disabled}
        className="bento-button bento-button-quiet h-11 w-10 shrink-0 px-0 text-neutral-500 hover:bg-red-50 hover:text-red-600"
        aria-label={`Retirer ${entry.photo.original_filename} de la file`}
        title="Retirer de la file"
      >
        <Icon name="close" size={18} />
      </button>
    </li>
  )
}
