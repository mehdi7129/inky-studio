import { useState } from 'react'
import { login } from '../lib/api'

interface LoginScreenProps {
  onSuccess: () => void
}

export function LoginScreen({ onSuccess }: LoginScreenProps) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!password) return
    setBusy(true)
    setError(null)
    try {
      await login(password)
      onSuccess()
    } catch (err) {
      setError(err instanceof Error ? err.message.replace(/^POST.*?:\s*/, '') : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-2xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-8 space-y-6 shadow-xl"
      >
        <header className="text-center">
          <h1 className="text-2xl font-semibold tracking-tight">Inky Studio</h1>
          <p className="text-sm text-neutral-500 mt-1">
            Entre le mot de passe affiché sur l'écran Inky.
          </p>
        </header>
        <div className="space-y-2">
          <label htmlFor="password" className="block text-sm font-medium">
            Mot de passe
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
            autoComplete="current-password"
            className="w-full px-3 py-2 rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-950 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            placeholder="10 caractères alphanumériques"
          />
          {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
        </div>
        <button
          type="submit"
          disabled={busy || !password}
          className={[
            'w-full px-4 py-2 rounded-md font-medium transition',
            busy || !password
              ? 'bg-neutral-300 text-neutral-500 dark:bg-neutral-700 cursor-not-allowed'
              : 'bg-indigo-600 text-white hover:bg-indigo-700',
          ].join(' ')}
        >
          {busy ? 'Connexion…' : 'Se connecter'}
        </button>
        <p className="text-xs text-neutral-500 text-center">
          Tu trouveras le mot de passe sur l'écran d'accueil de l'Inky.
        </p>
      </form>
    </main>
  )
}
