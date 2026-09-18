import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { YouTubeStatus } from '../../api/types'
import { Panel } from '../ui/Panel'
import { StatusDot } from '../ui/StatusDot'
import { ConfirmDialog } from '../ui/ConfirmDialog'

/** De koppeling met YouTube: aanzetten, zien of hij staat, en weer losmaken.
 *
 *  Het toestemming geven gebeurt bij Google en dus in een eigen tabblad — je logt daar in
 *  met je Google-wachtwoord, en dat hoort niet in een venster van Ganz thuis. Daarom kan
 *  deze kaart niet zelf merken dat het gelukt is: na afloop druk je op "Controleer".
 */
export function YouTubeCard() {
  const [stand, setStand] = useState<YouTubeStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [wacht, setWacht] = useState(false)
  // Welke handeling er nog een bevestiging mist.
  const [bevestigen, setBevestigen] = useState<'koppelen' | 'losmaken' | null>(null)

  const laden = useCallback(async () => {
    try {
      setStand(await api<YouTubeStatus>('/youtube/status'))
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'De stand is niet op te halen')
    }
  }, [])

  useEffect(() => {
    void laden()
  }, [laden])

  async function koppelen(confirm = false) {
    setBusy(true)
    try {
      const uitslag = await api<{ authorization_url: string }>('/youtube/connect', {
        method: 'POST',
        confirm,
      })
      setError(null)
      setWacht(true)
      // noopener: het nieuwe tabblad hoort niet bij dit venster te kunnen.
      window.open(uitslag.authorization_url, '_blank', 'noopener')
    } catch (err) {
      if (err instanceof ApiError && err.needsConfirmation) {
        setBevestigen('koppelen')
        return
      }
      setError(err instanceof ApiError ? err.message : 'Koppelen lukte niet')
    } finally {
      setBusy(false)
    }
  }

  async function losmaken(confirm = false) {
    setBusy(true)
    try {
      await api('/youtube/disconnect', { method: 'POST', confirm })
      setError(null)
      setWacht(false)
      await laden()
    } catch (err) {
      if (err instanceof ApiError && err.needsConfirmation) {
        setBevestigen('losmaken')
        return
      }
      setError(err instanceof ApiError ? err.message : 'Losmaken lukte niet')
    } finally {
      setBusy(false)
    }
  }

  const kleur = !stand?.configured ? 'idle' : stand.connected ? 'ok' : 'warn'
  const label = !stand?.configured
    ? 'niet ingesteld'
    : stand.connected
      ? 'gekoppeld'
      : 'nog niet gekoppeld'

  return (
    <Panel
      title="YouTube-koppeling"
      meta={stand ? <StatusDot tone={kleur} label={label} /> : 'laden…'}
    >
      {error ? <div className="notice notice--error">{error}</div> : null}

      {stand ? (
        <div className="stack">
          <p className="modal__intro">{stand.explanation}</p>

          {stand.connected ? (
            <dl className="keyvals">
              <div>
                <dt>Kanaal</dt>
                <dd>{stand.channel_name ?? '—'}</dd>
              </div>
              <div>
                <dt>Uploads komen op</dt>
                <dd>{PRIVACY[stand.upload_privacy] ?? stand.upload_privacy}</dd>
              </div>
              <div>
                <dt>Video's uit</dt>
                <dd>{stand.video_dir ?? 'nog niet ingesteld'}</dd>
              </div>
            </dl>
          ) : null}

          {wacht ? (
            <div className="notice notice--warn">
              Geef in het andere tabblad toestemming en klik daarna op Controleer.
            </div>
          ) : null}

          <div className="modal__buttons">
            {stand.connected ? (
              <button
                className="btn btn--danger"
                type="button"
                disabled={busy}
                onClick={() => void losmaken()}
              >
                Koppeling losmaken
              </button>
            ) : (
              <button
                className="btn btn--primary"
                type="button"
                disabled={busy || !stand.configured}
                onClick={() => void koppelen()}
              >
                Koppel met YouTube
              </button>
            )}
            <button className="btn" type="button" disabled={busy} onClick={() => void laden()}>
              Controleer
            </button>
          </div>
        </div>
      ) : null}

      {bevestigen ? (
        <ConfirmDialog
          action={bevestigen === 'koppelen' ? 'YouTube koppelen' : 'de koppeling losmaken'}
          onCancel={() => setBevestigen(null)}
          onConfirmed={() => {
            const wat = bevestigen
            setBevestigen(null)
            if (wat === 'koppelen') void koppelen(true)
            else void losmaken(true)
          }}
        />
      ) : null}
    </Panel>
  )
}

const PRIVACY: Record<string, string> = {
  private: 'privé (alleen jij)',
  unlisted: 'verborgen (alleen met de link)',
  public: 'openbaar',
}
