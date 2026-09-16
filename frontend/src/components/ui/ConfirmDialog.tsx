import { useState } from 'react'
import { ApiError, confirmWithPassword } from '../../api/client'

/** De tweede bevestiging voor gevoelige handelingen.
 *
 *  Het inlogtoken alleen is niet genoeg voor geld of het koppelen van accounts. Wie
 *  even een openstaande laptop tegenkomt, kan daarmee dus niets aanrichten. */
export function ConfirmDialog({
  action,
  onConfirmed,
  onCancel,
}: {
  action: string
  onConfirmed: () => void
  onCancel: () => void
}) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await confirmWithPassword(password)
      setPassword('')
      onConfirmed()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Bevestigen lukte niet')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(4, 7, 12, 0.72)',
        display: 'grid',
        placeItems: 'center',
        zIndex: 60,
        padding: 16,
      }}
      role="dialog"
      aria-modal="true"
    >
      <section className="panel" style={{ width: '100%', maxWidth: 360 }}>
        <header className="panel__head">
          <h2 className="panel__title">Bevestigen</h2>
        </header>
        <form className="panel__body" onSubmit={submit} style={{ display: 'grid', gap: 12 }}>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>
            {action} vraagt om je wachtwoord.
          </p>
          <label className="field">
            <span className="field__label">Wachtwoord</span>
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoFocus
              required
            />
          </label>
          {error ? <div className="notice notice--error">{error}</div> : null}
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn--ghost" type="button" onClick={onCancel}>
              Annuleren
            </button>
            <button className="btn btn--primary" type="submit" disabled={busy} style={{ flex: 1 }}>
              {busy ? 'Bezig…' : 'Bevestigen'}
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}
