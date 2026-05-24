import { useEffect, useState } from 'react'
import { convert, type ConvertResult } from '../lib/converter/pipeline'
import { decode } from '../lib/converter/decode'
import { transformToImageData } from '../lib/converter/transform'
import type { ColorMode } from '../lib/converter/palettes'
import type { DisplayState } from '../lib/api'
import { uploadToQueue } from '../lib/api'
import { PreviewCanvas } from './PreviewCanvas'

interface ConverterPanelProps {
  file: File
  display: DisplayState
  onUploaded: () => void
  onReset: () => void
}

type Status =
  | { kind: 'idle' }
  | { kind: 'converting' }
  | { kind: 'ready'; result: ConvertResult }
  | { kind: 'uploading' }
  | { kind: 'done'; result: ConvertResult; sizeKb: number }
  | { kind: 'error'; message: string }

export function ConverterPanel({ file, display, onUploaded, onReset }: ConverterPanelProps) {
  const [colorMode, setColorMode] = useState<ColorMode>(display.color_mode)
  const [offsetX, setOffsetX] = useState(0)
  const [offsetY, setOffsetY] = useState(0)
  const [originalPreview, setOriginalPreview] = useState<ImageData | null>(null)
  const [status, setStatus] = useState<Status>({ kind: 'idle' })

  useEffect(() => {
    let cancelled = false
    setStatus({ kind: 'converting' })

    void (async () => {
      try {
        const result = await convert({
          file,
          targetWidth: display.width,
          targetHeight: display.height,
          colorMode,
          offsetX,
          offsetY,
        })
        if (cancelled) return

        const original = await renderOriginalPreview(file, display.width, display.height)
        if (cancelled) return
        setOriginalPreview(original)
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
  }, [file, display.width, display.height, colorMode, offsetX, offsetY])

  const handleUpload = async () => {
    if (status.kind !== 'ready') return
    const readyResult = status.result
    const blob = readyResult.pngBlob
    setStatus({ kind: 'uploading' })
    try {
      await uploadToQueue(blob, file.name.replace(/\.[^.]+$/, '') + '.png')
      setStatus({
        kind: 'done',
        result: readyResult,
        sizeKb: Math.round(blob.size / 1024),
      })
      onUploaded()
    } catch (err) {
      setStatus({
        kind: 'error',
        message: err instanceof Error ? err.message : String(err),
      })
    }
  }

  const previewImage =
    status.kind === 'ready' || status.kind === 'done' ? status.result.previewImage : null

  const pngSizeKb =
    status.kind === 'ready' || status.kind === 'done'
      ? Math.round(status.result.pngBlob.size / 1024)
      : null

  return (
    <section className="space-y-6">
      <header className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold">{file.name}</h2>
          <p className="text-sm text-neutral-500">
            Cible : {display.width} × {display.height} · {display.colors} couleurs
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
        <PreviewCanvas image={originalPreview} label="Original (centre crop)" />
        <PreviewCanvas image={previewImage} label="Rendu e-ink (palette + dither)" />
      </div>

      <fieldset className="space-y-4 rounded-xl border border-neutral-200 dark:border-neutral-800 p-4">
        <legend className="px-2 text-xs uppercase tracking-wider text-neutral-500">
          Réglages
        </legend>

        <div>
          <label className="block text-sm font-medium mb-2">Mode couleur</label>
          <div className="flex gap-2">
            {(['pimoroni', 'spectra_palette', 'warmth_boost'] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setColorMode(mode)}
                className={[
                  'px-3 py-1.5 rounded-md text-sm border',
                  colorMode === mode
                    ? 'bg-indigo-600 text-white border-indigo-600'
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

      <footer className="flex items-center justify-between gap-4">
        <div className="text-sm text-neutral-500 min-h-[1.5rem]">
          {status.kind === 'converting' && 'Conversion…'}
          {status.kind === 'uploading' && 'Envoi au Pi…'}
          {status.kind === 'ready' && pngSizeKb !== null && (
            <>PNG prêt · {pngSizeKb} Ko · {status.result.durationMs.toFixed(0)} ms</>
          )}
          {status.kind === 'done' && (
            <span className="text-green-600 dark:text-green-400">
              ✓ Ajouté à la file · {status.sizeKb} Ko envoyés
            </span>
          )}
          {status.kind === 'error' && (
            <span className="text-red-600 dark:text-red-400">Erreur : {status.message}</span>
          )}
        </div>
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
      </footer>
    </section>
  )
}

async function renderOriginalPreview(
  file: File,
  targetWidth: number,
  targetHeight: number,
): Promise<ImageData> {
  const decoded = await decode(file)
  const data = transformToImageData(decoded.bitmap, { targetWidth, targetHeight })
  decoded.bitmap.close?.()
  return data
}
