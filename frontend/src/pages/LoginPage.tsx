import { useState } from 'react'
import { ApiError, login } from '../api/client'

export function LoginPage({ onSuccess }: { onSuccess: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email.trim().toLowerCase(), password)
      onSuccess()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Inloggen lukte niet')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <section className="panel login__card">
        <header className="panel__head">
          <h1 className="panel__title">Ganz — inloggen</h1>
        </header>
        <form className="panel__body" onSubmit={submit} style={{ display: 'grid', gap: 12 }}>
          <label className="field">
            <span className="field__label">E-mailadres</span>
            <input
              className="input"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
          <label className="field">
            <span className="field__label">Wachtwoord</span>
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {error ? <div className="notice notice--error">{error}</div> : null}
          <button className="btn btn--primary btn--wide" type="submit" disabled={busy}>
            {busy ? 'Bezig…' : 'Inloggen'}
          </button>
        </form>
      </section>
    </div>
  )
}
