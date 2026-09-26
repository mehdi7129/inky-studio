import { useEffect, useRef, useState } from 'react'
import type { DisplayState, QueueEntry } from '../lib/api'
import { photoFileUrl, triggerNext, triggerPrevious } from '../lib/api'
import { formatAbsolute, formatBytes, formatRelative } from '../lib/format'
import { Uploader } from './Uploader'
import { ConverterPanel } from './ConverterPanel'
import { Icon } from './Icon'
import './Dashboard.css'

interface DashboardProps {
  state: DisplayState
  queue: QueueEntry[]
  onChange: () => void
  onOpenQueue?: () => void
  onOpenSettings?: () => void
}

const SOURCE_LABEL: Record<string, string> = {
  auto: 'rotation automatique',
  manual_next: 'photo suivante',
  manual_previous: 'photo précédente',
  recycle: 'depuis l’historique',
  upload: 'ajoutée au cadre',
}

function nextChangeLabel(timestamp: number | null): string {
  if (timestamp === null) return 'À votre rythme'
  const date = new Date(timestamp * 1000)
  const today = new Date()
  const tomorrow = new Date(today)
  tomorrow.setDate(today.getDate() + 1)
  const day = date.toDateString() === today.toDateString()
    ? 'Aujourd’hui'
    : date.toDateString() === tomorrow.toDateString()
      ? 'Demain'
      : date.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' })
  const time = date.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
  return `${day}, ${time}`
}

export function Dashboard({ state, queue, onChange, onOpenQueue, onOpenSettings }: DashboardProps) {
  const [pickedFile, setPickedFile] = useState<File | null>(null)
  const [navBusy, setNavBusy] = useState(false)
  const [navError, setNavError] = useState<string | null>(null)
  const uploadInput = useRef<HTMLInputElement>(null)
  const addPhotoButton = useRef<HTMLButtonElement>(null)
  const converterRegion = useRef<HTMLDivElement>(null)
  const { display, current } = state
  const photoRatio = current
    ? `${current.photo.width} / ${current.photo.height}`
    : `${display.width} / ${display.height}`

  useEffect(() => {
    if (!pickedFile) return
    converterRegion.current?.focus({ preventScroll: true })
    converterRegion.current?.scrollIntoView?.({ block: 'start' })
  }, [pickedFile])

  const handleNext = async () => {
    setNavBusy(true)
    setNavError(null)
    try {
      await triggerNext()
      onChange()
    } catch (err) {
      setNavError(err instanceof Error ? err.message : String(err))
    } finally {
      setNavBusy(false)
    }
  }

  const handlePrevious = async () => {
    setNavBusy(true)
    setNavError(null)
    try {
      await triggerPrevious()
      onChange()
    } catch (err) {
      setNavError(err instanceof Error ? err.message : String(err))
    } finally {
      setNavBusy(false)
    }
  }

  const choosePhoto = () => {
    if (pickedFile) {
      converterRegion.current?.focus({ preventScroll: true })
      converterRegion.current?.scrollIntoView?.({ block: 'start' })
    } else {
      uploadInput.current?.click()
    }
  }

  return (
    <div className="dashboard">
      <header className="dashboard-hero">
        <div>
          <h1>Votre cadre, à votre rythme.</h1>
          <p>Une nouvelle photo. Un autre regard.</p>
        </div>
        <button ref={addPhotoButton} type="button" onClick={choosePhoto} className="bento-button bento-button-primary dashboard-add">
          <Icon name="plus" size={20} />
          {pickedFile ? 'Ajuster ma photo' : 'Ajouter une photo'}
        </button>
      </header>

      <div className="dashboard-grid">
        <article className="bento-card current-card">
          <header className="dashboard-card-heading">
            <h2><Icon name="image" size={20} />Sur le cadre</h2>
            {navBusy && <span className="bento-badge" role="status">Actualisation…</span>}
          </header>
          <div className="current-photo" style={{ aspectRatio: photoRatio }}>
            {current ? (
              <img src={photoFileUrl(current.photo.id)} alt={current.photo.original_filename} />
            ) : (
              <div className="current-empty">
                <span className="empty-frame"><Icon name="image" size={32} /></span>
                <h3>Votre première vue commence ici.</h3>
                <p>Ajoutez une photo pour donner vie à votre cadre.</p>
                <button type="button" className="bento-button bento-button-secondary" onClick={choosePhoto}>
                  <Icon name="plus" size={16} />{pickedFile ? 'Ajuster ma photo' : 'Choisir ma première photo'}
                </button>
              </div>
            )}
          </div>
          <footer className="current-footer">
            <div className="current-caption">
              {current ? (
                <>
                  <h3 title={current.photo.original_filename}>{current.photo.original_filename}</h3>
                  <p title={`${formatAbsolute(current.displayed_at)} · ${SOURCE_LABEL[current.source] ?? current.source} · ${formatBytes(current.photo.size_bytes)}`}>
                    Affichée {formatRelative(current.displayed_at)}
                  </p>
                </>
              ) : (
                <div><h3>Un cadre à votre image</h3><p>Prêt pour vos souvenirs préférés.</p></div>
              )}
            </div>
            <div className="current-actions">
              <button type="button" onClick={handlePrevious} disabled={navBusy} className="bento-button bento-button-secondary"
                title="Afficher la photo précédente depuis l’historique">
                Précédente
              </button>
              <button type="button" onClick={handleNext} disabled={navBusy} className="bento-button bento-button-primary"
                title="Afficher la prochaine photo de la file ou de l’historique">
                Afficher la suivante<Icon name="arrowRight" size={18} />
              </button>
            </div>
          </footer>
          {navError && <p role="alert" className="bento-alert current-error">{navError}</p>}
        </article>

        <section className="bento-card schedule-card" aria-labelledby="schedule-heading">
          <header className="dashboard-card-heading">
            <h2 id="schedule-heading"><Icon name="clock" size={21} />Prochain changement</h2>
          </header>
          <p className="schedule-time" title={formatAbsolute(state.next_change_at)}>
            {nextChangeLabel(state.next_change_at)}
          </p>
          <div className="schedule-footer">
            <span className="bento-badge">{state.next_change_at === null ? 'Manuel' : 'Planifié'}</span>
            {onOpenSettings && (
              <button type="button" onClick={onOpenSettings} className="bento-button bento-button-secondary">Modifier</button>
            )}
          </div>
        </section>

        <section className="bento-card upload-card" aria-label="Ajouter une photo">
          <Uploader inputRef={uploadInput} onFile={setPickedFile} disabled={pickedFile !== null} />
          {pickedFile && (
            <button type="button" className="bento-button bento-button-secondary upload-resume" onClick={choosePhoto}>
              Reprendre le cadrage<Icon name="arrowRight" size={16} />
            </button>
          )}
        </section>

        {pickedFile && (
          <div ref={converterRegion} tabIndex={-1} className="dashboard-converter" aria-label="Préparer la photo">
            <ConverterPanel
              file={pickedFile}
              display={display}
              onUploaded={onChange}
              onReset={() => {
                setPickedFile(null)
                requestAnimationFrame(() => addPhotoButton.current?.focus())
              }}
            />
          </div>
        )}

        <section className="bento-card queue-preview-card" aria-labelledby="queue-preview-heading">
          <header className="dashboard-card-heading">
            <div className="queue-preview-title">
              <h2 id="queue-preview-heading"><Icon name="queue" size={20} />À suivre</h2>
              <span className="bento-badge">{queue.length} photo{queue.length > 1 ? 's' : ''}</span>
            </div>
            {onOpenQueue && (
              <button type="button" onClick={onOpenQueue} className="bento-button bento-button-secondary bento-button-small">
                Voir la file<Icon name="arrowRight" size={14} />
              </button>
            )}
          </header>
          {queue.length > 0 ? (
            <ol className="queue-preview-list">
              {queue.slice(0, 4).map((entry, index) => (
                <li key={entry.id}>
                  <div className="queue-preview-image" style={{ aspectRatio: `${entry.photo.width} / ${entry.photo.height}` }}>
                    <img src={photoFileUrl(entry.photo.id)} alt={entry.photo.original_filename} loading="lazy" />
                  </div>
                  <p title={entry.photo.original_filename}>{entry.photo.original_filename}</p>
                  <span>{index === 0 ? 'La prochaine' : `Position ${index + 1}`} · {formatBytes(entry.photo.size_bytes)}</span>
                </li>
              ))}
            </ol>
          ) : (
            <div className="queue-preview-empty">
              <p>La suite reste à imaginer.</p>
              <span>Vos prochaines photos vous attendront ici.</span>
            </div>
          )}
          {queue.length > 4 && <p className="queue-preview-more">Et {queue.length - 4} autre{queue.length > 5 ? 's' : ''} dans la file.</p>}
        </section>

        <section className="bento-card hardware-card" aria-label="Votre écran">
          <span className="hardware-frame"><Icon name="monitor" size={40} /></span>
          <h2>{display.model}</h2>
          <p>{display.width} × {display.height} · {display.colors} couleurs</p>
          <span className={`bento-badge ${display.is_mock ? 'bento-badge-warning' : 'bento-badge-success'}`}>
            <span className="bento-status-dot" />{display.is_mock ? 'Mode démo' : 'Écran détecté'}
          </span>
        </section>
      </div>
    </div>
  )
}
