import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import { Panel } from '../components/ui/Panel'
import { EmptyState } from '../components/ui/EmptyState'
import { StatusDot } from '../components/ui/StatusDot'
import { shortDateTime } from '../lib/format'
import type { Skill, Tool } from '../api/types'

/** Wat Ganz kan.
 *
 *  Per skill: waar hij op aanslaat, uit welke stappen hij bestaat, en hoe vaak het lukte.
 *  Die laatste twee getallen zijn het nuttigst — een skill die vaker faalt dan slaagt is
 *  meestal een skill met een verkeerde stap erin. */
export function SkillsPage({ canWrite }: { canWrite: boolean }) {
  const [skills, setSkills] = useState<Skill[]>([])
  const [tools, setTools] = useState<Tool[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<number | null>(null)

  const load = useCallback(async () => {
    try {
      const [gevonden, gereedschap] = await Promise.all([
        api<Skill[]>('/skills'),
        api<Tool[]>('/skills/tools'),
      ])
      setSkills(gevonden)
      setTools(gereedschap)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Skills konden niet worden geladen')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function toggle(skill: Skill) {
    setBusy(skill.id)
    try {
      await api(`/skills/${skill.id}`, { method: 'PATCH', body: { enabled: !skill.enabled } })
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Wijzigen lukte niet')
    } finally {
      setBusy(null)
    }
  }

  const gevoelig = new Set(tools.filter((tool) => tool.sensitive).map((tool) => tool.name))
  const gesimuleerd = tools.length > 0 && tools.every((tool) => tool.simulated)

  return (
    <div className="page">
      <Panel
        title="Skills"
        meta={loading ? 'laden…' : `${skills.filter((s) => s.enabled).length} van ${skills.length} aan`}
      >
        {error ? <div className="notice notice--error">{error}</div> : null}

        {gesimuleerd ? (
          <div className="notice">
            Ganz loopt de stappen na en schrijft ze in het logboek, maar doet nog niets in de
            buitenwereld.
          </div>
        ) : null}

        {!loading && skills.length === 0 ? (
          <EmptyState
            title="Nog geen skills"
            hint="Een skill is een naam, een omschrijving waarop gematcht wordt, en een rijtje stappen."
          />
        ) : null}

        <div className="stack">
          {skills.map((skill) => (
            <article key={skill.id} className="listrow">
              <div className="listrow__main">
                <div className="listrow__title">
                  <StatusDot tone={skill.enabled ? 'ok' : 'idle'} />
                  <strong>{skill.name}</strong>
                  <span className="tag">v{skill.version}</span>
                </div>
                {skill.description ? <p className="listrow__sub">{skill.description}</p> : null}

                <p className="listrow__sub">
                  {skill.steps.length === 0 ? (
                    <em>geen stappen</em>
                  ) : (
                    skill.steps.map((stap, index) => (
                      <span key={index} className="tag">
                        {String(stap.tool)}
                        {gevoelig.has(String(stap.tool)) ? ' ⚠' : ''}
                      </span>
                    ))
                  )}
                </p>

                {skill.trigger_pattern ? (
                  <p className="listrow__sub">Slaat aan op: {skill.trigger_pattern.split('|').join(', ')}</p>
                ) : null}
              </div>

              <div className="listrow__side">
                <span title="gelukt / mislukt">
                  {skill.success_count} gelukt · {skill.failure_count} mislukt
                </span>
                <span className="listrow__muted">
                  {skill.last_used_at ? shortDateTime(skill.last_used_at) : 'nooit gebruikt'}
                </span>
                {canWrite ? (
                  <button
                    type="button"
                    className="btn btn--small"
                    disabled={busy === skill.id}
                    onClick={() => void toggle(skill)}
                  >
                    {skill.enabled ? 'Uitzetten' : 'Aanzetten'}
                  </button>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      </Panel>

      <Panel title="Waar een skill uit kan bestaan" meta={`${tools.length} stuks gereedschap`}>
        <div className="stack">
          {tools.map((tool) => (
            <div key={tool.name} className="listrow listrow--compact">
              <div className="listrow__main">
                <div className="listrow__title">
                  <code>{tool.name}</code>
                  {tool.sensitive ? <span className="tag tag--warn">vraagt bevestiging</span> : null}
                </div>
                <p className="listrow__sub">{tool.description}</p>
              </div>
              <div className="listrow__side">
                <span className="listrow__muted">{tool.simulated ? 'gesimuleerd' : 'echt'}</span>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  )
}
