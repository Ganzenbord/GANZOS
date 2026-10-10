import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { Capability, Integration } from '../../api/types'
import { Panel } from '../ui/Panel'
import { StatusDot, toneFor } from '../ui/StatusDot'
import { ConfirmDialog } from '../ui/ConfirmDialog'

/** Je eigen sleutels van diensten die Ganz voor je gebruikt.
 *
 *  Dit scherm werkt vanaf de catalogus (`/integrations/catalog`) en niet vanaf een leeg
 *  formulier. Dat is geen opsmuk: het oude formulier stuurde álles als `{api_key: ...}`,
 *  en voor Slack (bot_token, signing_secret) of mail (client_id, client_secret,
 *  refresh_token) zijn dat de verkeerde veldnamen. De koppeling leek dan gelukt en werkte
 *  niet — precies de fout die je pas merkt als er iets stil niet gebeurt.
 *
 *  Een sleutel is in te vullen en te vervangen, maar niet uit te lezen: ook niet als jij
 *  hem er zelf in hebt gezet. Daarom staat er bij een gekoppelde dienst alleen hoe hij er
 *  voor staat, en bij een halve koppeling welk veld nog leeg is.
 */

const STAAT_TEKST: Record<Capability['state'], string> = {
  connected: 'ingevuld',
  incomplete: 'niet compleet',
  missing: 'nog niets ingevuld',
  elsewhere: 'hoort elders',
  no_key_needed: 'geen sleutel nodig',
}

function toonFor(plek: Capability) {
  if (plek.state === 'connected') return toneFor('connected')
  if (plek.state === 'incomplete') return toneFor('warning')
  return toneFor(null)
}

export function IntegrationsCard() {
  const [catalogus, setCatalogus] = useState<Capability[] | null>(null)
  const [rijen, setRijen] = useState<Integration[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  /** Welke functie op dit moment open staat om in te vullen. */
  const [open, setOpen] = useState<string | null>(null)
  const [waardes, setWaardes] = useState<Record<string, string>>({})
  const [wacht, setWacht] = useState<
    null | { soort: 'opslaan'; key: string } | { soort: 'weg'; id: number }
  >(null)

  const laden = useCallback(async () => {
    try {
      const [lijst, cat] = await Promise.all([
        api<Integration[]>('/integrations'),
        api<Capability[]>('/integrations/catalog'),
      ])
      setRijen(lijst)
      setCatalogus(cat)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'De lijst is niet op te halen')
    }
  }, [])

  useEffect(() => {
    void laden()
  }, [laden])

  /** De koppeling die bij een functie hoort, als die er al is. Bepaalt nieuw of wijzigen. */
  const perKey = useMemo(() => {
    const kaart = new Map<string, Integration>()
    for (const rij of rijen) kaart.set(rij.key, rij)
    return kaart
  }, [rijen])

  /** Wat er wél gekoppeld is maar niet in de catalogus staat: zelf toegevoegd. */
  const buitenCatalogus = useMemo(() => {
    const bekend = new Set((catalogus ?? []).map((plek) => plek.key))
    return rijen.filter((rij) => !bekend.has(rij.key))
  }, [catalogus, rijen])

  async function opslaan(plek: Capability, confirm = false) {
    setBusy(true)
    try {
      // Alleen de velden die zijn ingevuld. Een leeg veld meesturen zou een bestaande
      // waarde overschrijven met niets.
      const credentials: Record<string, string> = {}
      for (const veld of plek.fields) {
        const waarde = (waardes[`${plek.key}.${veld.name}`] ?? '').trim()
        if (waarde) credentials[veld.name] = waarde
      }
      const bestaand = perKey.get(plek.key)
      if (bestaand) {
        // Samenvoegen met wat er al staat kan hier niet: de server geeft een sleutel nooit
        // terug. Daarom gaat een wijziging met de velden die je nu invult, en laat je een
        // veld leeg, dan blijft de hele oude set staan.
        await api(`/integrations/${bestaand.id}`, {
          method: 'PATCH',
          confirm,
          body: Object.keys(credentials).length ? { credentials } : {},
        })
      } else {
        await api('/integrations', {
          method: 'POST',
          confirm,
          body: {
            key: plek.key,
            name: plek.name,
            category: plek.category,
            credentials: Object.keys(credentials).length ? credentials : null,
          },
        })
      }
      setWaardes({})
      setOpen(null)
      setError(null)
      await laden()
    } catch (err) {
      if (err instanceof ApiError && err.needsConfirmation) {
        setWacht({ soort: 'opslaan', key: plek.key })
        return
      }
      setError(err instanceof ApiError ? err.message : 'Opslaan lukte niet')
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

  // Alleen de koppelingen die je hier invult. Een sleutel die op de server hoort of bij
  // een kanaal, meetellen zou een teller geven die je op dit scherm niet kunt kloppen.
  const invulbaar = (catalogus ?? []).filter((plek) => plek.store === 'integration')
  const klaar = invulbaar.filter((plek) => plek.state === 'connected').length

  return (
    <Panel
      title="Koppelingen"
      meta={catalogus ? `${klaar} van ${invulbaar.length} ingevuld` : 'laden…'}
    >
      <p className="modal__intro">
        Elke functie van Ganz met de sleutels die hij nodig heeft. Wat je invult gaat
        versleuteld de server in en komt nooit meer terug op dit scherm — kwijt? Vul een
        nieuwe in. Staat er <em>nog niet aangesloten</em>, dan is de plek er wel maar doet
        invullen nog niets.
      </p>

      {error ? <div className="notice notice--error">{error}</div> : null}

      <div className="stack">
        {(catalogus ?? []).map((plek, index) => {
          const vorige = (catalogus ?? [])[index - 1]
          const nieuweKop = !vorige || vorige.category !== plek.category
          const hier = plek.store === 'integration'
          // Alleen voor koppelingen die hier thuishoren naar een rij in de kluis kijken.
          // Zonder deze grens kreeg YouTube een knop "Loskoppelen" terwijl zijn sleutels bij
          // het kanaal staan — die knop zou dan iets anders weghalen dan wat eronder staat.
          const bestaand = hier ? perKey.get(plek.key) : undefined
          return (
            <div key={plek.key}>
              {nieuweKop ? (
                <h4 className="listrow__sub" style={{ margin: '12px 0 4px' }}>
                  {plek.category}
                </h4>
              ) : null}
              <article className="listrow">
                <div className="listrow__main">
                  <div className="listrow__title">
                    <StatusDot tone={toonFor(plek)} label={STAAT_TEKST[plek.state]} />
                    <strong>{plek.name}</strong>
                    {plek.wired ? null : <span className="tag">nog niet aangesloten</span>}
                  </div>
                  <p className="listrow__sub">{plek.purpose}</p>
                  {plek.state === 'incomplete' ? (
                    <p className="listrow__sub">
                      Nog invullen:{' '}
                      {plek.fields
                        .filter((veld) => plek.missing_fields.includes(veld.name))
                        .map((veld) => veld.label)
                        .join(', ')}
                    </p>
                  ) : null}
                  {hier ? null : <p className="listrow__sub">{plek.where}</p>}
                  {plek.note ? <p className="listrow__sub">{plek.note}</p> : null}
                  {plek.docs_url ? (
                    <p className="listrow__sub">
                      <a href={plek.docs_url} target="_blank" rel="noreferrer">
                        Waar je deze sleutel haalt
                      </a>
                    </p>
                  ) : null}
                </div>
                <div className="listrow__side">
                  <div className="listrow__buttons">
                    {hier ? (
                      <button
                        type="button"
                        className="btn btn--small"
                        disabled={busy}
                        onClick={() => setOpen(open === plek.key ? null : plek.key)}
                      >
                        {open === plek.key
                          ? 'Sluiten'
                          : bestaand?.has_credentials
                            ? 'Vervangen'
                            : 'Invullen'}
                      </button>
                    ) : null}
                    {bestaand ? (
                      <button
                        type="button"
                        className="btn btn--small btn--danger"
                        disabled={busy}
                        onClick={() => void weghalen(bestaand.id)}
                      >
                        Loskoppelen
                      </button>
                    ) : null}
                  </div>
                </div>
              </article>

              {open === plek.key ? (
                <form
                  className="formgrid"
                  style={{ marginTop: 8 }}
                  onSubmit={(event) => {
                    event.preventDefault()
                    void opslaan(plek)
                  }}
                >
                  {plek.fields.map((veld) => (
                    <label className="field" key={veld.name}>
                      <span className="field__label">{veld.label}</span>
                      <input
                        className="input"
                        type={veld.masked ? 'password' : 'text'}
                        autoComplete="off"
                        value={waardes[`${plek.key}.${veld.name}`] ?? ''}
                        onChange={(e) =>
                          setWaardes({
                            ...waardes,
                            [`${plek.key}.${veld.name}`]: e.target.value,
                          })
                        }
                      />
                      {veld.hint ? <span className="field__hint">{veld.hint}</span> : null}
                    </label>
                  ))}
                  <div className="field">
                    <span className="field__label">&nbsp;</span>
                    <button className="btn btn--primary" type="submit" disabled={busy}>
                      Opslaan
                    </button>
                  </div>
                </form>
              ) : null}
            </div>
          )
        })}
      </div>

      {buitenCatalogus.length ? (
        <>
          <h4 className="listrow__sub" style={{ margin: '16px 0 4px' }}>
            zelf toegevoegd
          </h4>
          <div className="stack">
            {buitenCatalogus.map((rij) => (
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
        </>
      ) : null}

      {wacht ? (
        <ConfirmDialog
          action={wacht.soort === 'opslaan' ? 'een dienst koppelen' : 'een dienst loskoppelen'}
          onCancel={() => setWacht(null)}
          onConfirmed={() => {
            const wat = wacht
            setWacht(null)
            if (wat.soort === 'weg') {
              void weghalen(wat.id, true)
              return
            }
            const plek = (catalogus ?? []).find((regel) => regel.key === wat.key)
            if (plek) void opslaan(plek, true)
          }}
        />
      ) : null}
    </Panel>
  )
}
