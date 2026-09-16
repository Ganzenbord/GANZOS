import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { TodoDay, TodoTask } from '../api/types'
import { Panel } from '../components/ui/Panel'
import { EmptyState } from '../components/ui/EmptyState'
import { IconPlus, IconTrash } from '../components/ui/Icons'

const RECURRENCE_LABEL: Record<string, string> = {
  once: 'Eenmalig',
  daily: 'Elke dag',
  weekdays: 'Doordeweeks',
  weekends: 'In het weekend',
  weekly: 'Wekelijks',
}

const PRIORITY_LABEL: Record<string, string> = {
  low: 'Laag',
  normal: 'Normaal',
  high: 'Hoog',
  critical: 'Kritiek',
}

const EMPTY_FORM = {
  title: '',
  category: '',
  scheduled_time: '',
  recurrence: 'daily',
  priority: 'normal',
}

/** Het volledige to-do scherm: toevoegen, wijzigen, verwijderen, subtaken, volgorde. */
export function TodosPage({ canWrite }: { canWrite: boolean }) {
  const [day, setDay] = useState<TodoDay | null>(null)
  const [all, setAll] = useState<TodoTask[]>([])
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [subtaskTitle, setSubtaskTitle] = useState<Record<number, string>>({})

  const load = useCallback(async () => {
    try {
      const [today, tasks] = await Promise.all([
        api<TodoDay>('/todos/today'),
        api<TodoTask[]>('/todos'),
      ])
      setDay(today)
      setAll(tasks)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Taken ophalen lukte niet')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function run(work: () => Promise<unknown>) {
    try {
      await work()
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Bewerking mislukt')
    }
  }

  async function createTask(event: React.FormEvent) {
    event.preventDefault()
    if (!form.title.trim()) return
    await run(async () => {
      await api('/todos', {
        method: 'POST',
        body: {
          title: form.title.trim(),
          category: form.category.trim() || null,
          scheduled_time: form.scheduled_time || null,
          recurrence: form.recurrence,
          priority: form.priority,
        },
      })
      setForm(EMPTY_FORM)
    })
  }

  function move(taskId: number, direction: -1 | 1) {
    const order = all.map((task) => task.id)
    const index = order.indexOf(taskId)
    const target = index + direction
    if (index < 0 || target < 0 || target >= order.length) return
    ;[order[index], order[target]] = [order[target], order[index]]
    void run(() => api('/todos/reorder', { method: 'POST', body: { order } }))
  }

  const completedToday = new Set(
    (day?.tasks ?? []).filter((task) => task.completed).map((task) => task.id),
  )

  return (
    <div className="page">
      {error ? <div className="notice notice--error">{error}</div> : null}

      {canWrite ? (
        <Panel title="Nieuwe taak">
          <form onSubmit={createTask} style={{ display: 'grid', gap: 12 }}>
            <div className="formgrid">
              <label className="field">
                <span className="field__label">Naam</span>
                <input
                  className="input"
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  placeholder="Katten eten geven"
                  required
                />
              </label>
              <label className="field">
                <span className="field__label">Categorie</span>
                <input
                  className="input"
                  value={form.category}
                  onChange={(e) => setForm({ ...form, category: e.target.value })}
                  placeholder="Huis"
                />
              </label>
              <label className="field">
                <span className="field__label">Tijdstip</span>
                <input
                  className="input"
                  type="time"
                  value={form.scheduled_time}
                  onChange={(e) => setForm({ ...form, scheduled_time: e.target.value })}
                />
              </label>
              <label className="field">
                <span className="field__label">Herhaling</span>
                <select
                  className="select"
                  value={form.recurrence}
                  onChange={(e) => setForm({ ...form, recurrence: e.target.value })}
                >
                  {Object.entries(RECURRENCE_LABEL).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field__label">Prioriteit</span>
                <select
                  className="select"
                  value={form.priority}
                  onChange={(e) => setForm({ ...form, priority: e.target.value })}
                >
                  {Object.entries(PRIORITY_LABEL).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div>
              <button className="btn btn--primary" type="submit">
                <IconPlus size={14} /> Taak toevoegen
              </button>
            </div>
          </form>
        </Panel>
      ) : null}

      <Panel
        title="Alle taken"
        meta={day ? `${day.completed} van ${day.total} vandaag voltooid` : undefined}
      >
        {all.length === 0 ? (
          <EmptyState title="Nog geen taken" hint="Voeg hierboven je eerste taak toe." />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Taak</th>
                <th>Categorie</th>
                <th>Tijd</th>
                <th>Herhaling</th>
                <th>Vandaag</th>
                <th aria-label="Acties" />
              </tr>
            </thead>
            <tbody>
              {all.map((task) => (
                <tr key={task.id}>
                  <td>
                    <div>{task.title}</div>
                    {task.subtasks.length > 0 ? (
                      <div className="todo__sub">
                        {task.subtasks.map((sub) => sub.title).join(' · ')}
                      </div>
                    ) : null}
                    {canWrite ? (
                      <form
                        style={{ display: 'flex', gap: 6, marginTop: 6 }}
                        onSubmit={(event) => {
                          event.preventDefault()
                          const title = (subtaskTitle[task.id] ?? '').trim()
                          if (!title) return
                          void run(async () => {
                            await api(`/todos/${task.id}/subtasks`, {
                              method: 'POST',
                              body: { title },
                            })
                            setSubtaskTitle({ ...subtaskTitle, [task.id]: '' })
                          })
                        }}
                      >
                        <input
                          className="input"
                          style={{ maxWidth: 190, padding: '4px 8px' }}
                          placeholder="Subtaak toevoegen"
                          value={subtaskTitle[task.id] ?? ''}
                          onChange={(e) =>
                            setSubtaskTitle({ ...subtaskTitle, [task.id]: e.target.value })
                          }
                        />
                        <button className="btn" type="submit" style={{ padding: '4px 9px' }}>
                          <IconPlus size={13} />
                        </button>
                      </form>
                    ) : null}
                  </td>
                  <td>{task.category ?? '—'}</td>
                  <td>{task.scheduled_time ?? '—'}</td>
                  <td>{RECURRENCE_LABEL[task.recurrence] ?? task.recurrence}</td>
                  <td>{completedToday.has(task.id) ? 'Voltooid' : 'Open'}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {canWrite ? (
                      <>
                        <button
                          className="btn btn--ghost"
                          style={{ padding: '3px 8px' }}
                          onClick={() => move(task.id, -1)}
                          type="button"
                          aria-label="Omhoog"
                        >
                          ↑
                        </button>{' '}
                        <button
                          className="btn btn--ghost"
                          style={{ padding: '3px 8px' }}
                          onClick={() => move(task.id, 1)}
                          type="button"
                          aria-label="Omlaag"
                        >
                          ↓
                        </button>{' '}
                        <button
                          className="btn btn--danger"
                          style={{ padding: '3px 8px' }}
                          type="button"
                          onClick={() => {
                            if (!window.confirm(`"${task.title}" verwijderen?`)) return
                            void run(() => api(`/todos/${task.id}`, { method: 'DELETE' }))
                          }}
                          aria-label="Verwijderen"
                        >
                          <IconTrash size={13} />
                        </button>
                      </>
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  )
}
