import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import { Panel } from '../components/ui/Panel'
import { EmptyState } from '../components/ui/EmptyState'
import { StatusDot, toneFor } from '../components/ui/StatusDot'
import { ConfirmDialog } from '../components/ui/ConfirmDialog'
import { shortDateTime } from '../lib/format'
import type { MatchResult, Task } from '../api/types'

/** Wat je Ganz gevraagd hebt, en hoe het afliep.
 *
 *  De twee stappen staan bewust los: eerst zoeken welke skill erbij hoort, dan pas
 *  uitvoeren. Zolang het uitvoeren nog gesimuleerd is, is een knop per stap duidelijker dan
 *  een ketting die vanzelf doorloopt — je ziet dan ook wáárom er een skill gekozen is. */
export function TasksPage({ canWrite }: { canWrite: boolean }) {
  const [tasks, setTasks] = useState<Task[]>([])
  const [titel, setTitel] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<number | null>(null)
  const [confirmFor, setConfirmFor] = useState<number | null>(null)

  const load = useCallback(async () => {
    try {
      setTasks(await api<Task[]>('/tasks'))
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Taken konden niet worden geladen')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function aanmaken(event: React.FormEvent) {
    event.preventDefault()
    if (!titel.trim()) return
    setBusy(-1)
    try {
      await api('/tasks', { method: 'POST', body: { title: titel.trim() } })
      setTitel('')
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Aanmaken lukte niet')
    } finally {
      setBusy(null)
    }
  }

  async function matchen(task: Task) {
    setBusy(task.id)
    try {
      const uitslag = await api<MatchResult>(`/tasks/${task.id}/match`, { method: 'POST' })
      setError(
        uitslag.matched
          ? null
          : `Geen skill gevonden: ${uitslag.reason}`,
      )
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Matchen lukte niet')
    } finally {
      setBusy(null)
    }
  }

  async function uitvoeren(task: Task, confirm = false) {
    setBusy(task.id)
    try {
      await api(`/tasks/${task.id}/execute`, { method: 'POST', confirm })
      setError(null)
      await load()
    } catch (err) {
      // 428: deze skill doet iets onomkeerbaars en vraagt eerst om je wachtwoord.
      if (err instanceof ApiError && err.needsConfirmation) {
        setConfirmFor(task.id)
        return
      }
      setError(err instanceof ApiError ? err.message : 'Uitvoeren lukte niet')
    } finally {
      setBusy(null)
    }
  }

  async function annuleren(task: Task) {
    setBusy(task.id)
    try {
      await api(`/tasks/${task.id}/cancel`, { method: 'POST' })
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Annuleren lukte niet')
    } finally {
      setBusy(null)
    }
  }

  const klaar = (status: string) => ['done', 'failed', 'cancelled'].includes(status)

  return (
    <div className="page">
      <Panel title="Taken" meta={loading ? 'laden…' : `${tasks.length} in totaal`}>
        {error ? <div className="notice notice--error">{error}</div> : null}

        {canWrite ? (
          <form className="inlineform" onSubmit={aanmaken}>
            <input
              value={titel}
              onChange={(event) => setTitel(event.target.value)}
              placeholder="Wat moet Ganz doen?"
              aria-label="Nieuwe taak"
            />
            <button className="btn btn--primary" type="submit" disabled={busy === -1 || !titel.trim()}>
              Toevoegen
            </button>
          </form>
        ) : null}

        {!loading && tasks.length === 0 ? (
          <EmptyState
            title="Nog geen taken"
            hint="Typ hierboven wat Ganz moet doen. Daarna zoekt hij er een skill bij."
          />
        ) : null}

        <div className="stack">
          {tasks.map((task) => (
            <article key={task.id} className="listrow">
              <div className="listrow__main">
                <div className="listrow__title">
                  <StatusDot tone={toneFor(task.status)} label={task.status} />
                  <strong>{task.title}</strong>
                </div>
                {task.match_reason ? (
                  <p className="listrow__sub">{task.match_reason}</p>
                ) : (
                  <p className="listrow__sub"><em>nog niet gematcht</em></p>
                )}
                {task.error ? <p className="listrow__sub listrow__sub--error">{task.error}</p> : null}
              </div>

              <div className="listrow__side">
                <span className="listrow__muted">{shortDateTime(task.created_at)}</span>
                {canWrite && !klaar(task.status) ? (
                  <div className="listrow__buttons">
                    <button
                      type="button"
                      className="btn btn--small"
                      disabled={busy === task.id}
                      onClick={() => void matchen(task)}
                    >
                      Zoek skill
                    </button>
                    <button
                      type="button"
                      className="btn btn--small btn--primary"
                      disabled={busy === task.id || task.skill_id === null}
                      onClick={() => void uitvoeren(task)}
                    >
                      Uitvoeren
                    </button>
                    <button
                      type="button"
                      className="btn btn--small"
                      disabled={busy === task.id}
                      onClick={() => void annuleren(task)}
                    >
                      Annuleren
                    </button>
                  </div>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      </Panel>

      {confirmFor !== null ? (
        <ConfirmDialog
          action="deze taak uit te voeren"
          onCancel={() => setConfirmFor(null)}
          onConfirmed={() => {
            const task = tasks.find((item) => item.id === confirmFor)
            setConfirmFor(null)
            if (task) void uitvoeren(task, true)
          }}
        />
      ) : null}
    </div>
  )
}
