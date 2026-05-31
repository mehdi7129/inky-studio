import { useCallback, useEffect, useRef, useState } from 'react'
import type { ChangeModeApi, ColorModeApi, HealthResponse, Settings, UpdateStatus } from '../lib/api'
import {
  fetchHealth,
  fetchSettings,
  fetchUpdateStatus,
  startUpdate,
  updateSettings,
} from '../lib/api'
import { useWebSocket } from '../lib/useWebSocket'

interface SettingsPanelProps {
  onChange: () => void
  health: HealthResponse | null
}

type UpdatePhase = 'idle' | 'checking' | 'running' | 'restarting' | 'error'

const STAGE_PCT: Record<string, number> = {
  checking: 5,
  downloading: 35,
  extracting: 55,
  installing: 75,
  restarting: 95,
}

const STAGE_LABELS: Record<string, string> = {
  checking: 'Recherche de la dernière version…',
  downloading: 'Téléchargement…',
  extracting: 'Extraction de l\'archive…',
  installing: 'Installation…',
  restarting: 'Redémarrage…',
}

const COLOR_MODES: { id: ColorModeApi; label: string; help: string }[] = [
  {
    id: 'spectra_palette',
    label: 'Spectra',
    help: 'Palette 6 couleurs calibrée pour les écrans Inky 2025 (recommandé).',
  },
  {
    id: 'warmth_boost',
    label: 'Warmth boost',
    help: 'Ajustements RGB chauds avant dithering — bon pour les portraits.',
  },
  {
    id: 'pimoroni',
    label: 'Pimoroni 7 couleurs',
    help: 'Palette des Inky 7.3" classique (7 couleurs). À éviter sur Spectra.',
  },
]

const CHANGE_MODES: { id: ChangeModeApi; label: string; help: string }[] = [
  {
    id: 'daily',
    label: 'Quotidien',
    help: 'Change la photo une fois par jour, à l\'heure choisie.',
  },
  {
    id: 'interval',
    label: 'Intervalle',
    help: 'Change toutes les N minutes (1 à 1440).',
  },
  {
    id: 'manual',
    label: 'Manuel uniquement',
    help: 'Le scheduler ne change rien tout seul — tu utilises Next/Prev.',
  },
]

export function SettingsPanel({ onChange, health }: SettingsPanelProps) {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  // ── Update feature state ──────────────────────────────────────────────────
  const [updateInfo, setUpdateInfo] = useState<UpdateStatus | null>(null)
  const [phase, setPhase] = useState<UpdatePhase>('idle')
  const [stage, setStage] = useState<string>('')
  const [log, setLog] = useState<string[]>([])
  const [updateError, setUpdateError] = useState<string | null>(null)
  const restartingRef = useRef(false)
  const logEndRef = useRef<HTMLDivElement | null>(null)

  const currentVersion = updateInfo?.current ?? health?.version ?? '?'

  useEffect(() => {
    let cancelled = false
    fetchSettings()
      .then((s) => {
        if (!cancelled) setSettings(s)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })
    fetchUpdateStatus()
      .then((u) => {
        if (!cancelled) setUpdateInfo(u)
      })
      .catch(() => {
        /* offline / GitHub unreachable — ignore, the button still lets you retry */
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ block: 'end' })
  }, [log])

  const pollUntilBackThenReload = useCallback(async () => {
    await new Promise((r) => setTimeout(r, 4000)) // let the service go down first
    for (let i = 0; i < 90; i++) {
      try {
        await fetchHealth()
        window.location.reload()
        return
      } catch {
        await new Promise((r) => setTimeout(r, 2000))
      }
    }
  }, [])

  useWebSocket(
    useCallback(
      (event) => {
        if (event.type !== 'system_update') return
        const p = (event.payload ?? {}) as { stage?: string; message?: string }
        const s = p.stage ?? ''
        if (p.message) {
          setLog((prev) => [...prev, p.message as string].slice(-80))
        }
        if (s === 'error') {
          setPhase('error')
          setUpdateError(p.message ?? 'Échec de la mise à jour')
          return
        }
        setStage(s)
        if (s === 'restarting') {
          setPhase('restarting')
          if (!restartingRef.current) {
            restartingRef.current = true
            void pollUntilBackThenReload()
          }
        } else {
          setPhase('running')
        }
      },
      [pollUntilBackThenReload],
    ),
  )

  const checkForUpdates = async () => {
    setPhase('checking')
    setUpdateError(null)
    try {
      setUpdateInfo(await fetchUpdateStatus(true)) // explicit check → bypass cache
    } catch (err) {
      setUpdateError(err instanceof Error ? err.message : String(err))
    } finally {
      setPhase((cur) => (cur === 'checking' ? 'idle' : cur))
    }
  }

  const launchUpdate = async () => {
    setPhase('running')
    setStage('checking')
    setLog([])
    setUpdateError(null)
    try {
      await startUpdate()
    } catch (err) {
      setPhase('error')
      setUpdateError(err instanceof Error ? err.message : String(err))
    }
  }

  const busy = phase === 'running' || phase === 'restarting'

  const patch = async (delta: Partial<Settings>) => {
    if (!settings) return
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const updated = await updateSettings(delta)
      setSettings(updated)
      setSaved(true)
      onChange()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  if (!settings) {
    return error ? (
      <p className="text-red-600 dark:text-red-400 text-sm">Erreur : {error}</p>
    ) : (
      <p className="text-neutral-500 text-sm">Chargement…</p>
    )
  }

  return (
    <div className="space-y-8 max-w-2xl">
      <section>
        <h2 className="text-xl font-semibold mb-1">Paramètres</h2>
        <p className="text-sm text-neutral-500">
          Les changements sont enregistrés automatiquement.
          {saving && <span className="ml-2 text-indigo-600 dark:text-indigo-400">Enregistrement…</span>}
          {!saving && saved && (
            <span className="ml-2 text-green-600 dark:text-green-400">✓ Enregistré</span>
          )}
        </p>
        {error && (
          <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>
        )}
      </section>

      <fieldset className="space-y-3">
        <legend className="text-sm font-medium mb-2">Mode couleur</legend>
        <div className="space-y-2">
          {COLOR_MODES.map((mode) => (
            <label
              key={mode.id}
              className={[
                'flex gap-3 rounded-lg border p-3 cursor-pointer transition',
                settings.color_mode === mode.id
                  ? 'border-indigo-600 bg-indigo-50 dark:bg-indigo-950/30'
                  : 'border-neutral-200 dark:border-neutral-800 hover:bg-neutral-50 dark:hover:bg-neutral-900',
              ].join(' ')}
            >
              <input
                type="radio"
                name="color_mode"
                value={mode.id}
                checked={settings.color_mode === mode.id}
                onChange={() => patch({ color_mode: mode.id })}
                className="mt-1"
              />
              <div>
                <p className="font-medium">{mode.label}</p>
                <p className="text-xs text-neutral-500">{mode.help}</p>
              </div>
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="text-sm font-medium mb-2">Fréquence de changement</legend>
        <div className="space-y-2">
          {CHANGE_MODES.map((mode) => (
            <label
              key={mode.id}
              className={[
                'flex gap-3 rounded-lg border p-3 cursor-pointer transition',
                settings.change_mode === mode.id
                  ? 'border-indigo-600 bg-indigo-50 dark:bg-indigo-950/30'
                  : 'border-neutral-200 dark:border-neutral-800 hover:bg-neutral-50 dark:hover:bg-neutral-900',
              ].join(' ')}
            >
              <input
                type="radio"
                name="change_mode"
                value={mode.id}
                checked={settings.change_mode === mode.id}
                onChange={() => patch({ change_mode: mode.id })}
                className="mt-1"
              />
              <div className="flex-1">
                <p className="font-medium">{mode.label}</p>
                <p className="text-xs text-neutral-500">{mode.help}</p>
                {settings.change_mode === mode.id && mode.id === 'daily' && (
                  <label className="block mt-2 text-sm">
                    Heure :{' '}
                    <input
                      type="number"
                      min={0}
                      max={23}
                      value={settings.change_hour}
                      onChange={(e) =>
                        patch({ change_hour: Math.max(0, Math.min(23, parseInt(e.target.value, 10) || 0)) })
                      }
                      className="ml-2 w-16 px-2 py-1 rounded border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900"
                    />
                    <span className="ml-1 text-neutral-500">h (0-23)</span>
                  </label>
                )}
                {settings.change_mode === mode.id && mode.id === 'interval' && (
                  <label className="block mt-2 text-sm">
                    Intervalle :{' '}
                    <input
                      type="number"
                      min={1}
                      max={1440}
                      value={settings.change_interval_minutes}
                      onChange={(e) =>
                        patch({
                          change_interval_minutes: Math.max(
                            1,
                            Math.min(1440, parseInt(e.target.value, 10) || 60),
                          ),
                        })
                      }
                      className="ml-2 w-20 px-2 py-1 rounded border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900"
                    />
                    <span className="ml-1 text-neutral-500">minutes (1-1440)</span>
                  </label>
                )}
              </div>
            </label>
          ))}
        </div>
      </fieldset>

      <section className="space-y-3 border-t border-neutral-200 dark:border-neutral-800 pt-6">
        <div>
          <h2 className="text-xl font-semibold mb-1">Mise à jour</h2>
          <p className="text-sm text-neutral-500">
            Version installée : <span className="font-mono">v{currentVersion}</span>
            {updateInfo && !updateInfo.update_available && updateInfo.latest && (
              <span className="ml-2 text-green-600 dark:text-green-400">✓ À jour</span>
            )}
            {updateInfo?.update_available && (
              <span className="ml-2 text-indigo-600 dark:text-indigo-400">
                Nouvelle version : v{updateInfo.latest}
              </span>
            )}
          </p>
        </div>

        {updateInfo?.update_available ? (
          <button
            type="button"
            onClick={launchUpdate}
            disabled={busy}
            className="px-4 py-2 rounded-lg text-white transition bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {busy ? 'Mise à jour en cours…' : `Mettre à jour vers v${updateInfo.latest}`}
          </button>
        ) : (
          <button
            type="button"
            onClick={checkForUpdates}
            disabled={busy || phase === 'checking'}
            className="px-4 py-2 rounded-lg border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-50 dark:hover:bg-neutral-900 transition disabled:opacity-50"
          >
            {phase === 'checking' ? 'Vérification…' : 'Vérifier les mises à jour'}
          </button>
        )}

        {busy && (
          <div className="space-y-2">
            <div className="h-2 w-full rounded bg-neutral-200 dark:bg-neutral-800 overflow-hidden">
              <div
                className="h-full bg-indigo-600 transition-all duration-500"
                style={{ width: `${STAGE_PCT[stage] ?? 10}%` }}
              />
            </div>
            <p className="text-sm text-neutral-500">
              {phase === 'restarting'
                ? 'Redémarrage… la page se rechargera automatiquement.'
                : STAGE_LABELS[stage] ?? 'Mise à jour…'}
            </p>
            {log.length > 0 && (
              <div className="max-h-40 overflow-y-auto rounded-lg bg-neutral-900 p-2 font-mono text-xs text-green-300">
                {log.map((line, i) => (
                  <div key={i} className="whitespace-pre-wrap break-all">
                    {line}
                  </div>
                ))}
                <div ref={logEndRef} />
              </div>
            )}
          </div>
        )}

        {phase === 'error' && updateError && (
          <p className="text-sm text-red-600 dark:text-red-400">Erreur : {updateError}</p>
        )}
      </section>
    </div>
  )
}
