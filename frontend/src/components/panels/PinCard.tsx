import { useEffect, useState } from 'react'
import { api, ApiError, setPin } from '../../api/client'
import type { Me } from '../../api/types'
import { Panel } from '../ui/Panel'

/** Hier stel je de pincode in waarmee je op je telefoon bevestigt.
 *
 *  Vier cijfers zijn maar tienduizend mogelijkheden; wat dat veilig houdt is dat je hem
 *  alleen kunt gebruiken als je al ingelogd bent, en dat je na drie mispogingen opnieuw
 *  moet beginnen. Je huidige wachtwoord blijft nodig om hem te wijzigen — anders zou een
 *  openstaande telefoon genoeg zijn om er zelf een te kiezen. */
export function PinCard() {
  const [heeftPin, setHeeftPin] = useState<boolean | null>(null)
  const [wachtwoord, setWachtwoord] = useState('')
  const [pin, setPinWaarde] = useState('')
  const [melding, setMelding] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function laden() {
    try {
      const me = await api<Me>('/auth/me')
      setHeeftPin(me.has_pin)
    } catch {
      setHeeftPin(null)
    }
  }

  useEffect(() => {
    void laden()
  }, [])

  async function opslaan(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setMelding(null)
    try {
      await setPin(wachtwoord, pin)
      setWachtwoord('')
      setPinWaarde('')
      setMelding('Pincode opgeslagen.')
      await laden()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Opslaan lukte niet')
    } finally {
      setBusy(false)
    }
  }

  const stand =
    heeftPin === null ? 'onbekend' : heeftPin ? 'er staat er een' : 'nog geen pincode'

  return (
    <Panel title="Pincode" meta={stand}>
      <p className="modal__intro">
        Met een pincode bevestig je gevoelige handelingen op je telefoon zonder je hele
        wachtwoord in te tikken. Inloggen doe je nog steeds met je wachtwoord.
      </p>
      <form className="stack" onSubmit={opslaan}>
        <label className="field">
          <span className="field__label">Je huidige wachtwoord</span>
          <input
            className="input"
            type="password"
            autoComplete="current-password"
            value={wachtwoord}
            onChange={(event) => setWachtwoord(event.target.value)}
            required
          />
        </label>
        <label className="field">
          <span className="field__label">
            {heeftPin ? 'Nieuwe pincode (4 tot 12 cijfers)' : 'Pincode (4 tot 12 cijfers)'}
          </span>
          <input
            className="input"
            type="password"
            inputMode="numeric"
            autoComplete="one-time-code"
            value={pin}
            onChange={(event) => setPinWaarde(event.target.value)}
            required
          />
        </label>
        {error ? <div className="notice notice--error">{error}</div> : null}
        {melding ? <div className="notice">{melding}</div> : null}
        <div>
          <button className="btn btn--primary" type="submit" disabled={busy}>
            {busy ? 'Bezig…' : heeftPin ? 'Pincode wijzigen' : 'Pincode instellen'}
          </button>
        </div>
      </form>
    </Panel>
  )
}
