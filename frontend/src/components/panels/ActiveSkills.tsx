import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { Panel } from '../ui/Panel'
import { EmptyState } from '../ui/EmptyState'
import { StatusDot } from '../ui/StatusDot'
import type { Skill } from '../../api/types'

/** Welke skills aanstaan, de meest gebruikte eerst.
 *
 *  Haalt zijn eigen gegevens op in plaats van mee te liften op /dashboard: dit paneel wil
 *  weten hoe vaak iets lukte, en dat hoort niet in het grote dashboardantwoord thuis voor
 *  wie het paneel niet eens ziet. */
export function ActiveSkills({ onOpenAll }: { onOpenAll: () => void }) {
  const [skills, setSkills] = useState<Skill[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let levend = true
    api<Skill[]>('/skills/active')
      .then((gevonden) => levend && setSkills(gevonden))
      .catch(() => levend && setError('Skills konden niet worden geladen'))
    return () => {
      levend = false
    }
  }, [])

  return (
    <Panel title="Actieve skills" name="skills" linkLabel="Alle skills" onLink={onOpenAll}>
      {error ? <div className="notice notice--error">{error}</div> : null}
      {skills === null && !error ? <p className="listrow__muted">Laden…</p> : null}
      {skills !== null && skills.length === 0 ? (
        <EmptyState title="Nog geen skills" hint="Wat Ganz kan, leg je vast als skill." />
      ) : null}

      <div className="stack">
        {(skills ?? []).slice(0, 5).map((skill) => (
          <div key={skill.id} className="listrow listrow--compact">
            <div className="listrow__main">
              <div className="listrow__title">
                <StatusDot tone="ok" />
                <strong>{skill.name}</strong>
              </div>
            </div>
            <div className="listrow__side">
              <span className="listrow__muted">
                {skill.run_count === 0 ? 'nog niet gebruikt' : `${skill.run_count}× gedraaid`}
              </span>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  )
}
