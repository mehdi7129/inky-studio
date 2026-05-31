import { useEffect, useState } from 'react'
import { convertBitmap, decode, type ConvertResult } from '../lib/converter/pipeline'
import type { DisplayInfo } from '../lib/api'
import { uploadToQueue } from '../lib/api'
import { PreviewCanvas } from './PreviewCanvas'

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
  bitmap: ImageBitmap
  wasHeic: boolean
  sourceWidth: number
  sourceHeight: number
}

export function ConverterPanel({ file, display, onUploaded, onReset }: ConverterPanelProps) {
  const [offsetX, setOffsetX] = useState(0)
  const [offsetY, setOffsetY] = useState(0)
  const [source, setSource] = useState<DecodedSource | null>(null)
  const [result, setResult] = useState<ConvertResult | null>(null)
  const [status, setStatus] = useState<Status>({ kind: 'decoding', wasHeic: isLikelyHeic(file) })

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
    if (!source) return
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
        setResult(r)
        setStatus((s) => (s.kind === 'uploading' || s.kind === 'done' ? s : { kind: 'ready', result: r }))
      } catch (err) {
        if (cancelled) return
        setStatus({ kind: 'error', message: err instanceof Error ? err.message : String(err) })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [source, display.width, display.height, offsetX, offsetY])

  const handleUpload = async () => {
    if (!result) return
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
    <section className="space-y-6">
      <header className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold">{file.name}</h2>
          <p className="text-sm text-neutral-500">
            {dimensionsHint ?? `Cible : ${display.width} × ${display.height}`} · {display.model}
          </p>
        </div>
        <button
          type="button"
          onClick={onReset}
          className="text-sm text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100"
        >
          ← Choisir une autre photo
        </button>
      </header>

      <div className="max-w-xl mx-auto">
        <PreviewCanvas image={result?.originalImage ?? null} label="Aperçu — cadré pour l'écran" />
        <p className="mt-2 text-center text-xs text-neutral-500">
          Les couleurs sont optimisées automatiquement sur l'écran e-ink lors de l'affichage.
        </p>
      </div>

      {!done && (
        <fieldset className="space-y-3 rounded-xl border border-neutral-200 dark:border-neutral-800 p-4">
          <legend className="px-2 text-xs uppercase tracking-wider text-neutral-500">
            Cadrage
          </legend>
          <div className="grid grid-cols-2 gap-4">
            <label className="block text-sm">
              <span className="font-medium">Horizontal : {offsetX.toFixed(2)}</span>
              <input
                type="range"
                min={-1}
                max={1}
                step={0.05}
                value={offsetX}
                onChange={(e) => setOffsetX(parseFloat(e.target.value))}
                className="w-full mt-1"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium">Vertical : {offsetY.toFixed(2)}</span>
              <input
                type="range"
                min={-1}
                max={1}
                step={0.05}
                value={offsetY}
                onChange={(e) => setOffsetY(parseFloat(e.target.value))}
                className="w-full mt-1"
              />
            </label>
          </div>
        </fieldset>
      )}

      <footer className="flex items-center justify-between gap-4 flex-wrap">
        <div className="text-sm min-h-[1.5rem] flex-1">
          {status.kind === 'decoding' && (
            <span className="text-neutral-500">
              {status.wasHeic ? 'Décodage HEIC (1ère fois ~1-2 s)…' : 'Préparation…'}
            </span>
          )}
          {status.kind === 'uploading' && <span className="text-neutral-500">Envoi à l'écran…</span>}
          {status.kind === 'done' && (
            <span className="text-green-600 dark:text-green-400 font-medium">
              ✓ Ajoutée à la file · {status.sizeKb} Ko
            </span>
          )}
          {status.kind === 'error' && (
            <span className="text-red-600 dark:text-red-400">Erreur : {status.message}</span>
          )}
        </div>
        {done ? (
          <button
            type="button"
            onClick={onReset}
            className="px-4 py-2 rounded-md font-medium bg-neutral-800 text-white hover:bg-neutral-900 dark:bg-neutral-200 dark:text-neutral-900 dark:hover:bg-white transition"
          >
            Envoyer une autre photo
          </button>
        ) : (
          <button
            type="button"
            onClick={handleUpload}
            disabled={!result || busy}
            className={[
              'px-4 py-2 rounded-md font-medium transition',
              result && !busy
                ? 'bg-indigo-600 text-white hover:bg-indigo-700'
                : 'bg-neutral-300 text-neutral-500 dark:bg-neutral-700 cursor-not-allowed',
            ].join(' ')}
          >
            Envoyer à l'écran
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
