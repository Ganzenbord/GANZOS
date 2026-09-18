import { useEffect, useState } from 'react'
import { api, ApiError, confirmWithPassword, confirmWithPin } from '../../api/client'
import type { Me } from '../../api/types'

type Manier = 'wachtwoord' | 'pincode'

/** Is dit een telefoonscherm? Dezelfde grens als de onderbalk in theme.css. */
function opTelefoon() {
  return window.matchMedia('(max-width: 768px)').matches
}

/** De tweede bevestiging voor gevoelige handelingen.
 *
 *  Het inlogtoken alleen is niet genoeg voor geld of het koppelen van accounts. Wie even
 *  een openstaande laptop tegenkomt, kan daarmee dus niets aanrichten.
 *
 *  Twee manieren, en dat is geen keuzestress maar een kwestie van toetsenbord: op een
 *  telefoon is een heel wachtwoord intikken zo omslachtig dat je geneigd bent een korter
 *  wachtwoord te kiezen — precies het tegenovergestelde van wat je wilt. De pincode staat
 *  daar los van: hij werkt alleen als je al ingelogd bent, en hij is na drie mispogingen
 *  op. Op een telefoon staat hij daarom vooraan, mits hij is ingesteld.
 */
export function ConfirmDialog({
  action,
  onConfirmed,
  onCancel,
}: {
  action: string
  onConfirmed: () => void
  onCancel: () => void
}) {
  // Eerst vragen of er überhaupt een pincode is; een tabblad dat gegarandeerd mislukt is
  // erger dan geen tabblad.
  const [heeftPin, setHeeftPin] = useState<boolean | null>(null)
  const [manier, setManier] = useState<Manier>('wachtwoord')
  const [geheim, setGeheim] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let levend = true
    void api<Me>('/auth/me')
      .then((me) => {
        if (!levend) return
        setHeeftPin(me.has_pin)
        if (me.has_pin && opTelefoon()) setManier('pincode')
      })
      .catch(() => {
        // Lukt dit niet, dan is het wachtwoord altijd nog goed.
        if (levend) setHeeftPin(false)
      })
    return () => {
      levend = false
    }
  }, [])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (manier === 'pincode') await confirmWithPin(geheim)
      else await confirmWithPassword(geheim)
      setGeheim('')
      onConfirmed()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Bevestigen lukte niet')
    } finally {
      setBusy(false)
    }
  }

  function wissel(naar: Manier) {
    setManier(naar)
    setGeheim('')
    setError(null)
  }

  const isPin = manier === 'pincode'

  return (
    <div className="modal" role="dialog" aria-modal="true">
      <section className="panel modal__panel">
        <header className="panel__head">
          <h2 className="panel__title">Bevestigen</h2>
        </header>
        <div className="panel__body">
          <p className="modal__intro">{action} vraagt om een tweede bevestiging.</p>

          {heeftPin === null ? (
            <p className="modal__intro">Even kijken…</p>
          ) : (
            <form className="stack" onSubmit={submit}>
              {heeftPin ? (
                <div className="switch" role="tablist" aria-label="Manier van bevestigen">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={isPin}
                    className={isPin ? 'switch__item switch__item--active' : 'switch__item'}
                    onClick={() => wissel('pincode')}
                  >
                    Pincode
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={!isPin}
                    className={!isPin ? 'switch__item switch__item--active' : 'switch__item'}
                    onClick={() => wissel('wachtwoord')}
                  >
                    Wachtwoord
                  </button>
                </div>
              ) : null}

              <label className="field">
                <span className="field__label">{isPin ? 'Pincode' : 'Wachtwoord'}</span>
                <input
                  className="input"
                  type="password"
                  // Numeriek geeft op een telefoon het cijfertoetsenbord.
                  inputMode={isPin ? 'numeric' : 'text'}
                  autoComplete={isPin ? 'one-time-code' : 'current-password'}
                  value={geheim}
                  onChange={(e) => setGeheim(e.target.value)}
                  autoFocus
                  required
                />
              </label>

              {error ? <div className="notice notice--error">{error}</div> : null}

              <div className="modal__buttons">
                <button className="btn btn--ghost" type="button" onClick={onCancel}>
                  Annuleren
                </button>
                <button className="btn btn--primary modal__go" type="submit" disabled={busy}>
                  {busy ? 'Bezig…' : 'Bevestigen'}
                </button>
              </div>
            </form>
          )}
        </div>
      </section>
    </div>
  )
}
