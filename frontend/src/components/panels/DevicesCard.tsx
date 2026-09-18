import { useCallback, useEffect, useState } from 'react'
import { ApiError, listSessions, revokeSession } from '../../api/client'
import type { Device } from '../../api/types'
import { relativeSince, shortDateTime } from '../../lib/format'
import { Panel } from '../ui/Panel'
import { EmptyState } from '../ui/EmptyState'

/** Welke apparaten op dit moment bij jouw Ganz kunnen, en hoe je er een uit gooit.
 *
 *  Dit is het scherm dat je nodig hebt op het moment dat je je telefoon kwijt bent. Daarom
 *  vraagt uitloggen hier niet om je wachtwoord: je moet het kunnen doen zodra je het merkt,
 *  niet nadat je een pincode hebt opgezocht. Het ergste dat iemand anders ermee kan, is jou
 *  uitloggen.
 */
export function DevicesCard() {
  const [devices, setDevices] = useState<Device[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<number | null>(null)

  const laden = useCallback(async () => {
    try {
      setDevices(await listSessions())
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'De lijst is niet op te halen')
    }
  }, [])

  useEffect(() => {
    void laden()
  }, [laden])

  async function eruit(device: Device) {
    setBusy(device.id)
    try {
      await revokeSession(device.id)
      await laden()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Uitloggen lukte niet')
    } finally {
      setBusy(null)
    }
  }

  return (
    <Panel
      title="Apparaten"
      meta={devices ? `${devices.length} ingelogd` : 'laden…'}
    >
      <p className="modal__intro">
        Hier staat elk apparaat waarop je bent ingelogd. Raak je er een kwijt, log hem dan
        uit — dan komt hij er niet meer in, ook niet met een token dat hij al had.
      </p>

      {error ? <div className="notice notice--error">{error}</div> : null}

      {devices && devices.length === 0 ? (
        <EmptyState title="Geen apparaten" hint="Dat kan eigenlijk niet: je kijkt nu ergens." />
      ) : null}

      <div className="stack">
        {(devices ?? []).map((device) => (
          <article key={device.id} className="listrow">
            <div className="listrow__main">
              <div className="listrow__title">
                <strong>{device.device_name ?? 'Naamloos apparaat'}</strong>
                {device.current ? <span className="tag">dit apparaat</span> : null}
              </div>
              <p className="listrow__sub">
                {device.ip_address ?? 'onbekend adres'} · voor het laatst gebruikt{' '}
                {device.last_used_at ? relativeSince(device.last_used_at) : 'nooit'}
              </p>
            </div>
            <div className="listrow__side">
              <span className="listrow__muted">sinds {shortDateTime(device.created_at)}</span>
              <div className="listrow__buttons">
                <button
                  type="button"
                  className="btn btn--small btn--danger"
                  disabled={busy === device.id}
                  onClick={() => void eruit(device)}
                >
                  {device.current ? 'Hier uitloggen' : 'Uitloggen'}
                </button>
              </div>
            </div>
          </article>
        ))}
      </div>
    </Panel>
  )
}
