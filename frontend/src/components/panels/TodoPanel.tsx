import { useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { TodoDay, TodoDayTask } from '../../api/types'
import { Panel } from '../ui/Panel'
import { EmptyState } from '../ui/EmptyState'
import { IconPlus } from '../ui/Icons'

interface TodoPanelProps {
  todo: TodoDay
  canWrite: boolean
  onChanged: () => void
  onOpenAll?: () => void
}

/** De dagelijkse lijst.
 *
 *  Afvinken kan alleen hier, door de gebruiker zelf. Er is met opzet geen enkele weg
 *  waarlangs een integratie een taak afvinkt: dat is precies de afspraak die deze
 *  lijst betrouwbaar maakt. */
export function TodoPanel({ todo, canWrite, onChanged, onOpenAll }: TodoPanelProps) {
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [newTitle, setNewTitle] = useState('')

  async function toggleTask(task: TodoDayTask) {
    if (!canWrite) return
    setBusy(task.id)
    setError(null)
    try {
      await api(`/todos/${task.id}/complete`, {
        method: 'POST',
        body: { completed: !task.completed, date: todo.date },
      })
      onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Afvinken lukte niet')
    } finally {
      setBusy(null)
    }
  }

  async function toggleSubtask(subtaskId: number, completed: boolean) {
    if (!canWrite) return
    setBusy(subtaskId)
    setError(null)
    try {
      await api(`/todos/subtasks/${subtaskId}?day=${todo.date}`, {
        method: 'PATCH',
        body: { completed: !completed },
      })
      onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Afvinken lukte niet')
    } finally {
      setBusy(null)
    }
  }

  async function addTask(event: React.FormEvent) {
    event.preventDefault()
    const title = newTitle.trim()
    if (!title) return
    setAdding(true)
    try {
      await api('/todos', { method: 'POST', body: { title, recurrence: 'daily' } })
      setNewTitle('')
      onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Toevoegen lukte niet')
    } finally {
      setAdding(false)
    }
  }

  const pct = todo.total === 0 ? 0 : Math.round((todo.completed / todo.total) * 100)

  return (
    <Panel
      title="To do list"
      meta={`${todo.completed} / ${todo.total} voltooid`}
      linkLabel="Alles bekijken"
      onLink={onOpenAll}
      tight
      footer={
        canWrite ? (
          <form onSubmit={addTask} style={{ display: 'flex', gap: 8, width: '100%' }}>
            <input
              className="input"
              placeholder="Nieuwe taak toevoegen"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              aria-label="Nieuwe taak"
            />
            <button className="btn" type="submit" disabled={adding || !newTitle.trim()}>
              <IconPlus size={14} />
            </button>
          </form>
        ) : null
      }
    >
      <div style={{ padding: '0 7px 10px' }}>
        <div className="progress">
          <div className="progress__bar" style={{ width: `${pct}%` }} />
        </div>
      </div>

      {error ? <div className="notice notice--error">{error}</div> : null}

      {todo.tasks.length === 0 ? (
        <EmptyState
          title="Geen taken voor vandaag"
          hint="Voeg hieronder je eerste dagelijkse taak toe."
        />
      ) : (
        <div className="todo">
          {todo.tasks.map((task) => (
            <div className="todo__item" key={task.id}>
              <button
                type="button"
                className={task.completed ? 'check check--done' : 'check'}
                onClick={() => void toggleTask(task)}
                disabled={!canWrite || busy === task.id}
                aria-pressed={task.completed}
                aria-label={`${task.title} ${task.completed ? 'afgevinkt' : 'nog te doen'}`}
              >
                ✓
              </button>
              <div className="todo__text">
                <div style={{ display: 'flex', alignItems: 'baseline' }}>
                  <span className={task.completed ? 'todo__title todo__title--done' : 'todo__title'}>
                    {task.title}
                  </span>
                  {task.scheduled_time ? (
                    <span className="todo__time">{task.scheduled_time}</span>
                  ) : null}
                </div>
                {task.category ? <div className="todo__sub">{task.category}</div> : null}

                {task.subtasks.length > 0 ? (
                  <div className="subtasks">
                    {task.subtasks.map((sub) => (
                      <div className={sub.completed ? 'subtask subtask--done' : 'subtask'} key={sub.id}>
                        <button
                          type="button"
                          className={sub.completed ? 'check check--sub check--done' : 'check check--sub'}
                          onClick={() => void toggleSubtask(sub.id, sub.completed)}
                          disabled={!canWrite || busy === sub.id}
                          aria-pressed={sub.completed}
                          aria-label={`${sub.title} ${sub.completed ? 'afgevinkt' : 'nog te doen'}`}
                        >
                          ✓
                        </button>
                        <span>{sub.title}</span>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}
