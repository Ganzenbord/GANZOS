import type { Mission } from '../../api/types'
import { STATUS_LABEL, clockTime } from '../../lib/format'
import { Panel } from '../ui/Panel'
import { EmptyState } from '../ui/EmptyState'
import { StatusDot, toneFor } from '../ui/StatusDot'

/** Wat Ganz zelf uitvoert.
 *
 *  De oude tijdlijn stond groot in het midden; die plek is nu voor de to-do lijst.
 *  De gegevens en de API zijn ongewijzigd — alleen de plaats op het scherm is anders. */
export function MissionPanel({ missions }: { missions: Mission[] }) {
  return (
    <Panel title="Mission / tasks" meta="Vandaag" tight>
      {missions.length === 0 ? (
        <EmptyState title="Geen missies gepland" hint="Ganz heeft vandaag niets in de planning." />
      ) : (
        <div className="rows">
          {missions.map((mission) => (
            <div className="rowitem" key={mission.id}>
              <span className="rowitem__sub" style={{ fontFamily: 'var(--mono)', minWidth: 44 }}>
                {mission.scheduled_for ? clockTime(mission.scheduled_for).slice(0, 5) : '--:--'}
              </span>
              <StatusDot tone={toneFor(mission.status)} />
              <span className="rowitem__label">{mission.title}</span>
              <span className="rowitem__right">
                {STATUS_LABEL[mission.status] ?? mission.status}
              </span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}
