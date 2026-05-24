import { useEffect, useState } from 'react'
import type { ChangeModeApi, ColorModeApi, Settings } from '../lib/api'
import { fetchSettings, updateSettings } from '../lib/api'

interface SettingsPanelProps {
  onChange: () => void
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

export function SettingsPanel({ onChange }: SettingsPanelProps) {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savedAt, setSavedAt] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchSettings()
      .then((s) => {
        if (!cancelled) setSettings(s)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  const patch = async (delta: Partial<Settings>) => {
    if (!settings) return
    setSaving(true)
    setError(null)
    try {
      const updated = await updateSettings(delta)
      setSettings(updated)
      setSavedAt(Date.now())
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
          {!saving && savedAt && (
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
    </div>
  )
}
