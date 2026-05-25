import { useEffect, useRef, useState } from 'react'
import { convertBitmap, decode, type ConvertResult } from '../lib/converter/pipeline'
import { fetchServerPreview } from '../lib/converter/serverPreview'
import type { ColorMode } from '../lib/converter/palettes'
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
  | { kind: 'converting'; firstRun: boolean }
  | { kind: 'ready'; result: ConvertResult }
  | { kind: 'uploading' }
  | { kind: 'done'; sizeKb: number; durationMs: number }
  | { kind: 'error'; message: string }

interface DecodedSource {
  bitmap: ImageBitmap
  wasHeic: boolean
  /** Source dimensions, useful in the UI for "5184×3888 → 800×480" hints. */
  sourceWidth: number
  sourceHeight: number
}

export function ConverterPanel({ file, display, onUploaded, onReset }: ConverterPanelProps) {
  const [colorMode, setColorMode] = useState<ColorMode>(display.color_mode)
  const [offsetX, setOffsetX] = useState(0)
  const [offsetY, setOffsetY] = useState(0)
  const [source, setSource] = useState<DecodedSource | null>(null)
  const [lastResult, setLastResult] = useState<ConvertResult | null>(null)
  const [status, setStatus] = useState<Status>({ kind: 'decoding', wasHeic: isLikelyHeic(file) })
  // Server-side Pillow preview — replaces the JS dither approximation when ready.
  const [serverPreview, setServerPreview] = useState<ImageData | null>(null)
  const serverPreviewAbort = useRef<AbortController | null>(null)

  // Effect 1 — decode the file once. HEIC may take 1-2s via WASM; everything else is near-instant.
  useEffect(() => {
    let cancelled = false
    let acquiredBitmap: ImageBitmap | null = null

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
        setStatus({
          kind: 'error',
          message: err instanceof Error ? err.message : String(err),
        })
      }
    })()

    return () => {
      cancelled = true
      acquiredBitmap?.close?.()
    }
  }, [file])

  // Effect 2 — convert (transform + dither + encode) whenever the cached source or settings change.
  // Re-runs in 100-400ms because the costly decode has already happened in Effect 1.
  useEffect(() => {
    if (!source) return
    let cancelled = false
    const firstRun = lastResult === null
    setStatus({ kind: 'converting', firstRun })

    void (async () => {
      try {
        const result = await convertBitmap({
          bitmap: source.bitmap,
          targetWidth: display.width,
          targetHeight: display.height,
          colorMode,
          offsetX,
          offsetY,
        })
        if (cancelled) return
        setLastResult(result)
        setStatus({ kind: 'ready', result })
      } catch (err) {
        if (cancelled) return
        setStatus({
          kind: 'error',
          message: err instanceof Error ? err.message : String(err),
        })
      }
    })()

    return () => {
      cancelled = true
    }
    // lastResult is intentionally omitted — it's a derived signal, not an input
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, display.width, display.height, colorMode, offsetX, offsetY])

  // Effect 3 — fetch the server-side Pillow preview whenever the upload-PNG changes.
  // We cancel any in-flight request so rapid slider changes don't pile up.
  useEffect(() => {
    if (!lastResult) return
    const blob = lastResult.pngBlob
    serverPreviewAbort.current?.abort()
    const ctrl = new AbortController()
    serverPreviewAbort.current = ctrl
    setServerPreview(null)
    void fetchServerPreview(blob, colorMode, ctrl.signal).then((data) => {
      if (data) setServerPreview(data)
    })
    return () => ctrl.abort()
  }, [lastResult, colorMode])

  const handleUpload = async () => {
    if (status.kind !== 'ready') return
    const blob = status.result.pngBlob
    const durationMs = status.result.durationMs
    setStatus({ kind: 'uploading' })
    try {
      await uploadToQueue(blob, file.name.replace(/\.[^.]+$/, '') + '.png')
      setStatus({
        kind: 'done',
        sizeKb: Math.round(blob.size / 1024),
        durationMs,
      })
      // Tell the parent to refresh the queue, but keep this panel mounted so
      // the success message is visible until the user explicitly picks another.
      onUploaded()
    } catch (err) {
      setStatus({
        kind: 'error',
        message: err instanceof Error ? err.message : String(err),
      })
    }
  }

  const displayedOriginal = lastResult?.originalImage ?? null
  // Show the server Pillow preview as soon as it arrives, fall back to JS dither
  const displayedPreview = serverPreview ?? lastResult?.previewImage ?? null
  const previewLabel = serverPreview
    ? 'Rendu e-ink (exact)'
    : lastResult?.previewImage
      ? 'Rendu e-ink (approx. — chargement…)'
      : 'Rendu e-ink'
  const pngSizeKb = lastResult ? Math.round(lastResult.pngBlob.size / 1024) : null

  const dimensionsHint = source
    ? `${source.sourceWidth}×${source.sourceHeight} → ${display.width}×${display.height}`
    : null

  return (
    <section className="space-y-6">
      <header className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold">{file.name}</h2>
          <p className="text-sm text-neutral-500">
            {dimensionsHint ?? `Cible : ${display.width} × ${display.height}`} · {display.colors} couleurs
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

      <div className="grid md:grid-cols-2 gap-6">
        <PreviewCanvas image={displayedOriginal} label="Original (centre crop)" />
        <PreviewCanvas image={displayedPreview} label={previewLabel} />
      </div>

      <fieldset className="space-y-4 rounded-xl border border-neutral-200 dark:border-neutral-800 p-4">
        <legend className="px-2 text-xs uppercase tracking-wider text-neutral-500">
          Réglages
        </legend>

        <div>
          <label className="block text-sm font-medium mb-2">Mode couleur</label>
          <div className="flex gap-2 flex-wrap">
            {(['pimoroni', 'spectra_palette', 'warmth_boost'] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setColorMode(mode)}
                className={[
                  'px-3 py-1.5 rounded-md text-sm border transition',
                  colorMode === mode
                    ? 'bg-indigo-600 text-white border-indigo-600 shadow-sm'
                    : 'border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-800',
                ].join(' ')}
              >
                {mode}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <label className="block text-sm">
            <span className="font-medium">Décalage horizontal : {offsetX.toFixed(2)}</span>
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
            <span className="font-medium">Décalage vertical : {offsetY.toFixed(2)}</span>
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

      <footer className="flex items-center justify-between gap-4 flex-wrap">
        <div className="text-sm min-h-[1.5rem] flex-1">
          {status.kind === 'decoding' && (
            <span className="text-neutral-500">
              {status.wasHeic
                ? 'Décodage HEIC (1ère fois ~1-2 s)…'
                : 'Décodage…'}
            </span>
          )}
          {status.kind === 'converting' && (
            <span className="text-neutral-500">
              {status.firstRun
                ? 'Conversion (resize + dither)…'
                : 'Mise à jour du rendu…'}
            </span>
          )}
          {status.kind === 'ready' && pngSizeKb !== null && (
            <span className="text-neutral-500">
              PNG prêt · <span className="font-medium text-neutral-700 dark:text-neutral-200">{pngSizeKb} Ko</span>{' '}
              · {status.result.durationMs.toFixed(0)} ms
            </span>
          )}
          {status.kind === 'uploading' && (
            <span className="text-neutral-500">Envoi au Pi…</span>
          )}
          {status.kind === 'done' && (
            <span className="text-green-600 dark:text-green-400 font-medium">
              ✓ Ajoutée à la file · {status.sizeKb} Ko envoyés
            </span>
          )}
          {status.kind === 'error' && (
            <span className="text-red-600 dark:text-red-400">Erreur : {status.message}</span>
          )}
        </div>
        {status.kind === 'done' ? (
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
            disabled={status.kind !== 'ready'}
            className={[
              'px-4 py-2 rounded-md font-medium transition',
              status.kind === 'ready'
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
