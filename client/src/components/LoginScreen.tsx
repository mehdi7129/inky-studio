import { useState } from 'react'
import { login } from '../lib/api'
import { Icon } from './Icon'

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
    <main className="flex min-h-screen flex-col px-5 py-7 sm:px-10 sm:py-9">
      <div className="flex items-center gap-3 text-xl font-semibold tracking-tight">
        <span className="h-6 w-6 rounded-[3px] border-[2.5px] border-neutral-950" aria-hidden="true" />
        Inky Studio
      </div>
      <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center py-14">
        <header className="mb-9 text-center">
          <p className="bento-eyebrow mb-4">Bienvenue chez vous</p>
          <h1 className="text-4xl font-semibold leading-tight tracking-tight sm:text-[2.75rem]">
            Vos photos.<br />À votre rythme.
          </h1>
          <p className="mx-auto mt-4 max-w-xs text-sm leading-relaxed text-neutral-500">
            Connectez-vous à votre cadre pour lui offrir une nouvelle vue.
          </p>
        </header>
        <form onSubmit={handleSubmit} className="bento-card space-y-6 p-6 sm:p-8">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
              <Icon name="lock" size={20} />
            </span>
            <p className="text-sm font-medium">Votre studio vous attend</p>
          </div>
          <div className="space-y-2.5">
            <label htmlFor="password" className="block text-sm font-medium">Mot de passe</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoFocus
              autoComplete="current-password"
              aria-describedby={error ? 'login-error login-help' : 'login-help'}
              aria-invalid={error ? true : undefined}
              className="bento-field w-full"
              placeholder="Votre mot de passe"
            />
            {error && <p id="login-error" className="bento-alert" role="alert">{error}</p>}
          </div>
          <button
            type="submit"
            disabled={busy || !password}
            className="bento-button bento-button-primary w-full"
          >
            {busy ? 'Connexion…' : 'Se connecter'}
            {!busy && <Icon name="arrowRight" size={17} />}
          </button>
          <p id="login-help" className="text-center text-xs leading-relaxed text-neutral-500">
            Le mot de passe se trouve sur l'écran d'accueil de votre Inky.
          </p>
        </form>
      </div>
      <p className="text-center text-xs text-neutral-400">Un cadre. Mille souvenirs.</p>
    </main>
  )
}
