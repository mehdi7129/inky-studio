import { useCallback, useEffect, useRef, useState } from 'react'
import type { ChangeModeApi, HealthResponse, Settings, UpdateStatus } from '../lib/api'
import {
  fetchHealth,
  fetchSettings,
  fetchUpdateStatus,
  startUpdate,
  updateSettings,
} from '../lib/api'
import { useWebSocket } from '../lib/useWebSocket'
import { Icon } from './Icon'

interface SettingsPanelProps {
  onChange: () => void
  health: HealthResponse | null
  revision?: number
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

const CHANGE_MODES: { id: ChangeModeApi; label: string; help: string }[] = [
  {
    id: 'daily',
    label: 'Quotidien',
    help: 'Une nouvelle photo chaque jour, à l’heure de votre choix.',
  },
  {
    id: 'interval',
    label: 'Intervalle',
    help: 'Faites défiler vos photos à intervalles réguliers.',
  },
  {
    id: 'manual',
    label: 'Manuel uniquement',
    help: 'Prenez le temps. Vous choisissez quand changer de photo.',
  },
]

export function SettingsPanel({ onChange, health, revision = 0 }: SettingsPanelProps) {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  // Local mirror of the saturation slider so dragging stays smooth; we only
  // POST the value when the user lets go (pointer/key up), not on every step.
  const [satLocal, setSatLocal] = useState<number | null>(null)
  const settingsRequestVersion = useRef(0)

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
    const version = ++settingsRequestVersion.current
    let cancelled = false
    fetchSettings()
      .then((s) => {
        if (!cancelled && version === settingsRequestVersion.current) {
          setSettings(s)
          setSatLocal(s.saturation)
        }
      })
      .catch((err) => {
        if (!cancelled && version === settingsRequestVersion.current) {
          setError(err instanceof Error ? err.message : String(err))
        }
      })
    return () => {
      cancelled = true
    }
  }, [revision])

  useEffect(() => {
    let cancelled = false
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
      setPhase('error')
      setUpdateError(err instanceof Error ? err.message : String(err))
    } finally {
      setPhase((cur) => (cur === 'checking' ? 'idle' : cur))
    }
  }

  const launchUpdate = async () => {
    restartingRef.current = false
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
    if (!settings || saving) return
    const version = ++settingsRequestVersion.current
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const updated = await updateSettings(delta)
      if (version === settingsRequestVersion.current) {
        setSettings(updated)
        setSatLocal(updated.saturation)
      }
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
      <p className="bento-alert" role="alert">Erreur : {error}</p>
    ) : (
      <p className="bento-card p-8 text-sm text-neutral-500" role="status">Chargement…</p>
    )
  }

  return (
    <div className="space-y-7">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="bento-eyebrow mb-3">À votre façon</p>
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Le bon rythme.</h1>
          <p className="mt-2 text-sm text-neutral-500 sm:text-base">
            Quelques réglages, un cadre qui vous ressemble.
          </p>
        </div>
        <p className="text-xs text-neutral-500" role="status">
          {saving ? (
            <span className="bento-badge">Enregistrement…</span>
          ) : saved ? (
            <span className="bento-badge bento-badge-success">✓ Enregistré</span>
          ) : 'Enregistrement automatique'}
        </p>
      </header>

      {error && <p className="bento-alert" role="alert">{error}</p>}

      <div className="grid items-start gap-5 lg:grid-cols-[1.1fr_1fr]">
        <section className="bento-card p-5 sm:p-7 lg:row-span-2">
          <div className="mb-7 flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-50 text-amber-600">
              <Icon name="clock" size={21} />
            </span>
            <h2 className="bento-panel-heading">Fréquence de changement</h2>
          </div>
          <fieldset disabled={saving} className="space-y-3">
            <legend className="sr-only">Fréquence de changement</legend>
            {CHANGE_MODES.map((mode) => (
              <div
                key={mode.id}
                className={[
                  'rounded-2xl border p-4 transition-colors sm:p-5',
                  settings.change_mode === mode.id
                    ? 'border-neutral-900 bg-neutral-50'
                    : 'border-neutral-200/80 hover:border-neutral-300',
                ].join(' ')}
              >
                <label className="flex cursor-pointer items-start gap-3">
                  <input
                    type="radio"
                    name="change_mode"
                    value={mode.id}
                    checked={settings.change_mode === mode.id}
                    onChange={() => patch({ change_mode: mode.id })}
                    className="mt-0.5 h-4 w-4 shrink-0 accent-neutral-950"
                  />
                  <span>
                    <span className="block text-sm font-semibold">{mode.label}</span>
                    <span className="mt-1.5 block text-xs leading-relaxed text-neutral-500">{mode.help}</span>
                  </span>
                </label>
                {settings.change_mode === mode.id && mode.id === 'daily' && (
                  <div className="ml-7 mt-5 border-t border-neutral-200/80 pt-4">
                    <label htmlFor="change-hour" className="mb-2 block text-xs font-medium text-neutral-600">
                      Chaque jour à
                    </label>
                    <div className="flex items-center gap-2">
                      <input
                        id="change-hour"
                        type="number"
                        min={0}
                        max={23}
                        value={settings.change_hour}
                        onChange={(e) =>
                          patch({ change_hour: Math.max(0, Math.min(23, parseInt(e.target.value, 10) || 0)) })
                        }
                        className="bento-field w-20 text-sm tabular-nums"
                      />
                      <span className="text-sm text-neutral-500">h <span className="ml-1 text-xs">(0–23)</span></span>
                    </div>
                  </div>
                )}
                {settings.change_mode === mode.id && mode.id === 'interval' && (
                  <div className="ml-7 mt-5 border-t border-neutral-200/80 pt-4">
                    <label htmlFor="change-interval" className="mb-2 block text-xs font-medium text-neutral-600">
                      Une nouvelle photo toutes les
                    </label>
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        id="change-interval"
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
                        className="bento-field w-24 text-sm tabular-nums"
                      />
                      <span className="text-sm text-neutral-500">minutes</span>
                    </div>
                    <p className="mt-2 text-xs text-neutral-400">De 1 à 1 440 minutes.</p>
                  </div>
                )}
              </div>
            ))}
          </fieldset>
          <p className="mt-6 text-xs leading-relaxed text-neutral-500">
            Le cadre affiche les photos dans l'ordre de votre file d'attente.
          </p>
        </section>

        <section className="bento-card p-5 sm:p-7">
          <div className="mb-6 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
                <Icon name="image" size={21} />
              </span>
              <h2 className="bento-panel-heading">Saturation des couleurs</h2>
            </div>
            <output htmlFor="saturation" className="bento-badge tabular-nums">
              {(satLocal ?? settings.saturation).toFixed(2)}
            </output>
          </div>
          <fieldset disabled={saving}>
            <legend className="sr-only">Saturation des couleurs</legend>
            <label htmlFor="saturation" className="sr-only">Saturation des couleurs</label>
            <input
              id="saturation"
              type="range"
              min={0}
              max={2}
              step={0.05}
              value={satLocal ?? settings.saturation}
              onChange={(e) => setSatLocal(parseFloat(e.target.value))}
              onPointerUp={() => satLocal !== null && patch({ saturation: satLocal })}
              onKeyUp={() => satLocal !== null && patch({ saturation: satLocal })}
              className="h-7 w-full cursor-pointer accent-neutral-950"
            />
            <div className="mt-1 flex justify-between text-xs text-neutral-500">
              <span>Doux</span>
              <span>Fidèle · 1.0</span>
              <span>Intense</span>
            </div>
          </fieldset>
          <p className="mt-5 text-xs leading-relaxed text-neutral-500">
            <strong className="font-medium text-neutral-700">1.0 est recommandé</strong> pour des couleurs fidèles.
            Le réglage s'applique à la prochaine photo affichée, dans les limites de l'écran.
          </p>
        </section>

        <section className="bento-card p-5 sm:p-7">
          <div className="mb-5 flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-neutral-100 text-neutral-600">
                <Icon name="refresh" size={20} />
              </span>
              <h2 className="bento-panel-heading">Mise à jour</h2>
            </div>
            {updateInfo && !updateInfo.update_available && updateInfo.latest && (
              <span className="bento-badge bento-badge-success">À jour</span>
            )}
          </div>
          <p className="text-sm text-neutral-500">
            Inky Studio <span className="font-medium text-neutral-900">v{currentVersion}</span>
          </p>
          {updateInfo?.update_available && (
            <p className="mt-2 text-sm text-blue-600">La version {updateInfo.latest} est disponible.</p>
          )}
          <div className="mt-5">
            {updateInfo?.update_available ? (
              <button
                type="button"
                onClick={launchUpdate}
                disabled={busy}
                className="bento-button bento-button-primary"
              >
                {busy ? 'Mise à jour en cours…' : `Mettre à jour vers v${updateInfo.latest}`}
              </button>
            ) : (
              <button
                type="button"
                onClick={checkForUpdates}
                disabled={busy || phase === 'checking'}
                className="bento-button bento-button-secondary"
              >
                {phase === 'checking' ? 'Vérification…' : 'Vérifier les mises à jour'}
              </button>
            )}
          </div>

          {busy && (
            <div className="mt-5 space-y-3">
              <div
                className="h-1.5 w-full overflow-hidden rounded-full bg-neutral-100"
                role="progressbar"
                aria-label="Progression de la mise à jour"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={STAGE_PCT[stage] ?? 10}
              >
                <div
                  className="h-full rounded-full bg-blue-600 transition-all duration-500"
                  style={{ width: `${STAGE_PCT[stage] ?? 10}%` }}
                />
              </div>
              <p className="text-xs leading-relaxed text-neutral-500" role="status">
                {phase === 'restarting'
                  ? 'Redémarrage… la page se rechargera automatiquement.'
                  : STAGE_LABELS[stage] ?? 'Mise à jour…'}
              </p>
              {log.length > 0 && (
                <div className="max-h-40 overflow-y-auto rounded-xl bg-neutral-950 p-3 font-mono text-xs text-neutral-300">
                  {log.map((line, i) => (
                    <div key={i} className="whitespace-pre-wrap break-all">{line}</div>
                  ))}
                  <div ref={logEndRef} />
                </div>
              )}
            </div>
          )}

          {phase === 'error' && updateError && (
            <p className="bento-alert mt-4" role="alert">Erreur : {updateError}</p>
          )}
        </section>
      </div>
    </div>
  )
}
