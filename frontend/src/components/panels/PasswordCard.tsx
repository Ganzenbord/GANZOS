import { useState } from 'react'
import { api, ApiError } from '../../api/client'
import { Panel } from '../ui/Panel'

/** Je wachtwoord wijzigen, vanaf welk apparaat dan ook.
 *
 *  Twee dingen die hier bij elkaar horen: je huidige wachtwoord is nodig (ingelogd zijn is
 *  niet genoeg — een openstaande laptop mag geen accountovername zijn), en alle ándere
 *  apparaten worden uitgelogd. Dat laatste is precies waarom je je wachtwoord wijzigt als je
 *  vermoedt dat iemand meekijkt.
 */
export function PasswordCard() {
  const [huidig, setHuidig] = useState('')
  const [nieuw, setNieuw] = useState('')
  const [herhaal, setHerhaal] = useState('')
  const [melding, setMelding] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function opslaan(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setMelding(null)
    if (nieuw !== herhaal) {
      setError('De twee nieuwe wachtwoorden zijn niet hetzelfde.')
      return
    }
    setBusy(true)
    try {
      const uitslag = await api<{ message: string }>('/auth/password', {
        method: 'POST',
        body: { current_password: huidig, new_password: nieuw },
        // 401 betekent hier "je oude wachtwoord klopt niet", niet "je sessie is voorbij".
        keepSession: true,
      })
      setHuidig('')
      setNieuw('')
      setHerhaal('')
      setMelding(uitslag.message)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Wijzigen lukte niet')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel title="Wachtwoord">
      <p className="modal__intro">
        Hiermee log je overal in: op je laptop, je pc en je telefoon. Wijzig je hem, dan
        moeten je andere apparaten opnieuw inloggen — dit apparaat blijft ingelogd.
      </p>
      <form className="stack" onSubmit={opslaan}>
        <label className="field">
          <span className="field__label">Je huidige wachtwoord</span>
          <input
            className="input"
            type="password"
            autoComplete="current-password"
            value={huidig}
            onChange={(e) => setHuidig(e.target.value)}
            required
          />
        </label>
        <label className="field">
          <span className="field__label">Nieuw wachtwoord (minstens 12 tekens)</span>
          <input
            className="input"
            type="password"
            autoComplete="new-password"
            minLength={12}
            value={nieuw}
            onChange={(e) => setNieuw(e.target.value)}
            required
          />
        </label>
        <label className="field">
          <span className="field__label">Nog een keer</span>
          <input
            className="input"
            type="password"
            autoComplete="new-password"
            value={herhaal}
            onChange={(e) => setHerhaal(e.target.value)}
            required
          />
        </label>
        {error ? <div className="notice notice--error">{error}</div> : null}
        {melding ? <div className="notice">{melding}</div> : null}
        <div>
          <button className="btn btn--primary" type="submit" disabled={busy}>
            {busy ? 'Bezig…' : 'Wachtwoord wijzigen'}
          </button>
        </div>
      </form>
    </Panel>
  )
}
