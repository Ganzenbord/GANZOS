import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { Integration } from '../../api/types'
import { Panel } from '../ui/Panel'
import { EmptyState } from '../ui/EmptyState'
import { StatusDot, toneFor } from '../ui/StatusDot'
import { ConfirmDialog } from '../ui/ConfirmDialog'

/** Je eigen sleutels van diensten die Ganz voor je gebruikt.
 *
 *  Je kunt een sleutel invullen en vervangen, maar niet uitlezen — ook niet als jij hem er
 *  zelf in hebt gezet. Hij gaat versleuteld de database in en er is geen weg terug naar het
 *  scherm. Daarom staat er bij een gekoppelde dienst alleen "ingevuld".
 */
export function IntegrationsCard() {
  const [rijen, setRijen] = useState<Integration[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ key: '', name: '', api_key: '' })
  // Welke handeling nog een bevestiging mist.
  const [wacht, setWacht] = useState<null | { soort: 'nieuw' } | { soort: 'weg'; id: number }>(null)

  const laden = useCallback(async () => {
    try {
      setRijen(await api<Integration[]>('/integrations'))
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'De lijst is niet op te halen')
    }
  }, [])

  useEffect(() => {
    void laden()
  }, [laden])

  async function toevoegen(confirm = false) {
    setBusy(true)
    try {
      await api('/integrations', {
        method: 'POST',
        confirm,
        body: {
          key: form.key.trim(),
          name: form.name.trim(),
          credentials: form.api_key ? { api_key: form.api_key } : null,
        },
      })
      setForm({ key: '', name: '', api_key: '' })
      setError(null)
      await laden()
    } catch (err) {
      if (err instanceof ApiError && err.needsConfirmation) {
        setWacht({ soort: 'nieuw' })
        return
      }
      setError(err instanceof ApiError ? err.message : 'Koppelen lukte niet')
    } finally {
      setBusy(false)
    }
  }

  async function weghalen(id: number, confirm = false) {
    setBusy(true)
    try {
      await api(`/integrations/${id}`, { method: 'DELETE', confirm })
      await laden()
    } catch (err) {
      if (err instanceof ApiError && err.needsConfirmation) {
        setWacht({ soort: 'weg', id })
        return
      }
      setError(err instanceof ApiError ? err.message : 'Loskoppelen lukte niet')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel title="Gekoppelde diensten" meta={rijen ? `${rijen.length} gekoppeld` : 'laden…'}>
      <p className="modal__intro">
        Sleutels van diensten die Ganz voor je gebruikt — bijvoorbeeld Higgsfield. Ze gaan
        versleuteld de server in en komen nooit meer terug op dit scherm. Kwijt? Vul een
        nieuwe in; vervangen kan altijd.
      </p>

      {error ? <div className="notice notice--error">{error}</div> : null}

      {rijen && rijen.length === 0 ? (
        <EmptyState title="Nog niets gekoppeld" hint="Vul hieronder je eerste sleutel in." />
      ) : null}

      <div className="stack">
        {(rijen ?? []).map((rij) => (
          <article key={rij.id} className="listrow">
            <div className="listrow__main">
              <div className="listrow__title">
                <StatusDot tone={toneFor(rij.status)} label={rij.status} />
                <strong>{rij.name}</strong>
                {rij.has_credentials ? <span className="tag">sleutel ingevuld</span> : null}
              </div>
              <p className="listrow__sub">{rij.status_detail ?? rij.key}</p>
            </div>
            <div className="listrow__side">
              <div className="listrow__buttons">
                <button
                  type="button"
                  className="btn btn--small btn--danger"
                  disabled={busy}
                  onClick={() => void weghalen(rij.id)}
                >
                  Loskoppelen
                </button>
              </div>
            </div>
          </article>
        ))}
      </div>

      <form
        className="formgrid"
        style={{ marginTop: 12 }}
        onSubmit={(event) => {
          event.preventDefault()
          void toevoegen()
        }}
      >
        <label className="field">
          <span className="field__label">Korte sleutel</span>
          <input
            className="input"
            value={form.key}
            onChange={(e) => setForm({ ...form, key: e.target.value })}
            placeholder="higgsfield"
            required
          />
        </label>
        <label className="field">
          <span className="field__label">Naam in het scherm</span>
          <input
            className="input"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Higgsfield"
            required
          />
        </label>
        <label className="field">
          <span className="field__label">API-sleutel</span>
          <input
            className="input"
            type="password"
            autoComplete="off"
            value={form.api_key}
            onChange={(e) => setForm({ ...form, api_key: e.target.value })}
          />
        </label>
        <div className="field">
          <span className="field__label">&nbsp;</span>
          <button className="btn btn--primary" type="submit" disabled={busy}>
            Koppelen
          </button>
        </div>
      </form>

      {wacht ? (
        <ConfirmDialog
          action={wacht.soort === 'nieuw' ? 'een dienst koppelen' : 'een dienst loskoppelen'}
          onCancel={() => setWacht(null)}
          onConfirmed={() => {
            const wat = wacht
            setWacht(null)
            if (wat.soort === 'nieuw') void toevoegen(true)
            else void weghalen(wat.id, true)
          }}
        />
      ) : null}
    </Panel>
  )
}
