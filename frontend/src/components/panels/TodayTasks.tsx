import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { Panel } from '../ui/Panel'
import { EmptyState } from '../ui/EmptyState'
import { StatusDot, toneFor } from '../ui/StatusDot'
import type { ScheduleToday } from '../../api/types'

/** Wat er vandaag op de rol staat.
 *
 *  Uploads en taken door elkaar, op tijd gesorteerd. De vraag "wat staat er vandaag te
 *  gebeuren" kent het verschil tussen die twee tabellen niet. */
export function TodayTasks({ onOpenAll }: { onOpenAll: () => void }) {
  const [schedule, setSchedule] = useState<ScheduleToday | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let levend = true
    api<ScheduleToday>('/schedule/today')
      .then((gevonden) => levend && setSchedule(gevonden))
      .catch(() => levend && setError('De planning kon niet worden geladen'))
    return () => {
      levend = false
    }
  }, [])

  const tijd = (moment: string) => new Date(moment).toLocaleTimeString('nl-NL', {
    hour: '2-digit',
    minute: '2-digit',
  })

  return (
    <Panel
      title="Vandaag"
      name="vandaag"
      meta={schedule ? `${schedule.open} van ${schedule.total} open` : undefined}
      linkLabel="Alle taken"
      onLink={onOpenAll}
    >
      {error ? <div className="notice notice--error">{error}</div> : null}
      {schedule === null && !error ? <p className="listrow__muted">Laden…</p> : null}
      {schedule !== null && schedule.items.length === 0 ? (
        <EmptyState title="Niets gepland vandaag" />
      ) : null}

      <div className="stack">
        {(schedule?.items ?? []).map((regel) => (
          <div key={`${regel.kind}-${regel.id}`} className="listrow listrow--compact">
            <div className="listrow__main">
              <div className="listrow__title">
                <StatusDot tone={regel.done ? 'ok' : toneFor(regel.status)} />
                <strong>{regel.title}</strong>
                <span className="tag">{regel.kind === 'upload' ? 'upload' : 'taak'}</span>
              </div>
            </div>
            <div className="listrow__side">
              <span className="listrow__muted">{tijd(regel.at)}</span>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  )
}
