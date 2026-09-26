import { useEffect, useState } from 'react'
import { convertBitmap, decode, type ConvertResult } from '../lib/converter/pipeline'
import type { DisplayInfo } from '../lib/api'
import { uploadToQueue } from '../lib/api'
import { PreviewCanvas } from './PreviewCanvas'
import { Icon } from './Icon'

interface ConverterPanelProps {
  file: File
  display: DisplayInfo
  onUploaded: () => void
  onReset: () => void
}

type Status =
  | { kind: 'decoding'; wasHeic: boolean }
  | { kind: 'ready'; result: ConvertResult }
  | { kind: 'uploading' }
  | { kind: 'done'; sizeKb: number }
  | { kind: 'error'; message: string }

interface DecodedSource {
  file: File
  bitmap: ImageBitmap
  wasHeic: boolean
  sourceWidth: number
  sourceHeight: number
}

export function ConverterPanel({ file, display, onUploaded, onReset }: ConverterPanelProps) {
  const [offsetX, setOffsetX] = useState(0)
  const [offsetY, setOffsetY] = useState(0)
  const [source, setSource] = useState<DecodedSource | null>(null)
  const [prepared, setPrepared] = useState<{
    result: ConvertResult
    source: DecodedSource
    file: File
    width: number
    height: number
    offsetX: number
    offsetY: number
  } | null>(null)
  const [status, setStatus] = useState<Status>({ kind: 'decoding', wasHeic: isLikelyHeic(file) })
  const result = prepared?.result ?? null
  const cropReady = prepared !== null && prepared.source === source && prepared.file === file &&
    prepared.width === display.width && prepared.height === display.height &&
    prepared.offsetX === offsetX && prepared.offsetY === offsetY

  // Decode the file once. HEIC may take 1-2s via WASM; everything else is instant.
  useEffect(() => {
    let cancelled = false
    let acquiredBitmap: ImageBitmap | null = null
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStatus({ kind: 'decoding', wasHeic: isLikelyHeic(file) })

    void (async () => {
      try {
        const decoded = await decode(file)
        acquiredBitmap = decoded.bitmap
        if (cancelled) {
          decoded.bitmap.close?.()
          return
        }
        setSource({
          file,
          bitmap: decoded.bitmap,
          wasHeic: decoded.wasHeic,
          sourceWidth: decoded.bitmap.width,
          sourceHeight: decoded.bitmap.height,
        })
      } catch (err) {
        if (cancelled) return
        setStatus({ kind: 'error', message: err instanceof Error ? err.message : String(err) })
      }
    })()

    return () => {
      cancelled = true
      acquiredBitmap?.close?.()
    }
  }, [file])

  // Re-crop to the panel size whenever the source, framing, or panel changes.
  // Cheap (~5-20ms) since the costly decode already happened.
  useEffect(() => {
    if (!source || source.file !== file) return
    let cancelled = false
    void (async () => {
      try {
        const r = await convertBitmap({
          bitmap: source.bitmap,
          targetWidth: display.width,
          targetHeight: display.height,
          offsetX,
          offsetY,
        })
        if (cancelled) return
        setPrepared({ result: r, source, file, width: display.width, height: display.height, offsetX, offsetY })
        setStatus((s) => (s.kind === 'uploading' || s.kind === 'done' ? s : { kind: 'ready', result: r }))
      } catch (err) {
        if (cancelled) return
        setStatus({ kind: 'error', message: err instanceof Error ? err.message : String(err) })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [source, file, display.width, display.height, offsetX, offsetY])

  const handleUpload = async () => {
    if (!result || !cropReady || status.kind === 'uploading' || status.kind === 'done') return
    setStatus({ kind: 'uploading' })
    try {
      await uploadToQueue(result.pngBlob, file.name.replace(/\.[^.]+$/, '') + '.png')
      setStatus({ kind: 'done', sizeKb: Math.round(result.pngBlob.size / 1024) })
      onUploaded()
    } catch (err) {
      setStatus({ kind: 'error', message: err instanceof Error ? err.message : String(err) })
    }
  }

  const dimensionsHint = source
    ? `${source.sourceWidth}×${source.sourceHeight} → ${display.width}×${display.height}`
    : null
  const busy = status.kind === 'uploading'
  const done = status.kind === 'done'

  return (
    <section className="bento-card converter-card" aria-label="Cadrage de la photo">
      <header className="converter-header">
        <div>
          <h2>{file.name}</h2>
          <p>
            {dimensionsHint ?? `Cible : ${display.width} × ${display.height}`} · {display.model}
          </p>
        </div>
        <button
          type="button"
          onClick={onReset}
          disabled={busy}
          className="bento-button bento-button-quiet"
        >
          <Icon name="arrowLeft" size={16} />Choisir une autre photo
        </button>
      </header>

      <div className="converter-workspace">
        <div>
          <PreviewCanvas image={result?.originalImage ?? null} label="Aperçu — cadré pour l'écran" aspectRatio={display.width / display.height} />
          <p className="converter-preview-note">
            Les couleurs sont optimisées automatiquement sur l'écran e-ink lors de l'affichage.
          </p>
        </div>

        {!done && (
          <fieldset disabled={busy} className="converter-crop">
            <legend>
              Cadrage
            </legend>
            <p>Gardez ce qui compte. Déplacez la photo pour trouver le bon cadre.</p>
            <div className="converter-sliders">
              <label>
                <span className="converter-slider-label"><span>Horizontal</span><output>{Math.round(offsetX * 100)} %</output></span>
                <input
                  type="range"
                  min={-1}
                  max={1}
                  step={0.05}
                  value={offsetX}
                  onChange={(e) => setOffsetX(parseFloat(e.target.value))}
                  aria-valuetext={`${Math.round(offsetX * 100)} %`}
                />
              </label>
              <label>
                <span className="converter-slider-label"><span>Vertical</span><output>{Math.round(offsetY * 100)} %</output></span>
                <input
                  type="range"
                  min={-1}
                  max={1}
                  step={0.05}
                  value={offsetY}
                  onChange={(e) => setOffsetY(parseFloat(e.target.value))}
                  aria-valuetext={`${Math.round(offsetY * 100)} %`}
                />
              </label>
            </div>
          </fieldset>
        )}
        {done && (
          <div className="converter-complete">
            <Icon name="check" size={28} />
            <h3>Une nouvelle vue vous attend.</h3>
            <p>Votre photo a rejoint la file. Elle sera affichée à son tour.</p>
          </div>
        )}
      </div>

      <footer className="converter-footer">
        <div className="converter-status" role={status.kind === 'error' ? 'alert' : 'status'}>
          {status.kind === 'decoding' && (
            <span>
              {status.wasHeic ? 'Préparation de votre photo HEIC…' : 'Préparation…'}
            </span>
          )}
          {status.kind === 'uploading' && <span>Ajout à la file…</span>}
          {status.kind === 'ready' && <span>{cropReady ? 'Prête à rejoindre votre file de photos.' : 'Préparation du cadrage…'}</span>}
          {status.kind === 'done' && (
            <span className="converter-status-success">
              ✓ Ajoutée à la file · {status.sizeKb} Ko
            </span>
          )}
          {status.kind === 'error' && (
            <span className="converter-status-error">Erreur : {status.message}</span>
          )}
        </div>
        {done ? (
          <button
            type="button"
            onClick={onReset}
            className="bento-button bento-button-primary"
          >
            <Icon name="plus" size={17} />Envoyer une autre photo
          </button>
        ) : (
          <button
            type="button"
            onClick={handleUpload}
            disabled={!cropReady || busy}
            className="bento-button bento-button-primary"
          >
            <Icon name="upload" size={17} />Envoyer à l'écran
          </button>
        )}
      </footer>
    </section>
  )
}

function isLikelyHeic(file: File): boolean {
  if (file.type === 'image/heic' || file.type === 'image/heif') return true
  const lower = file.name.toLowerCase()
  return lower.endsWith('.heic') || lower.endsWith('.heif')
}
