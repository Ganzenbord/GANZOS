import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import { relativeSince, shortDateTime } from '../lib/format'
import { Panel } from '../components/ui/Panel'
import { EmptyState } from '../components/ui/EmptyState'
import { StatusDot, toneFor } from '../components/ui/StatusDot'

interface Column {
  key: string
  label: string
  kind?: 'status' | 'datetime' | 'since'
}

interface ModulePageProps {
  title: string
  endpoint: string
  columns: Column[]
  emptyTitle: string
  emptyHint?: string
  /** Sommige eindpunten leveren een object met de lijst erin. */
  pick?: (payload: unknown) => Record<string, unknown>[]
}

function render(value: unknown, kind?: Column['kind']) {
  if (value === null || value === undefined || value === '') return '—'
  if (kind === 'status') {
    const status = String(value)
    return <StatusDot tone={toneFor(status)} label={status} />
  }
  if (kind === 'datetime') return shortDateTime(String(value))
  if (kind === 'since') return relativeSince(String(value))
  if (typeof value === 'boolean') return value ? 'Ja' : 'Nee'
  return String(value)
}

/** Een eenvoudig overzicht voor de modules die alleen gelezen worden.
 *  Eén component in plaats van zeven bijna identieke pagina's. */
export function ModulePage({
  title,
  endpoint,
  columns,
  emptyTitle,
  emptyHint,
  pick,
}: ModulePageProps) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const payload = await api<unknown>(endpoint)
      setRows(pick ? pick(payload) : (payload as Record<string, unknown>[]))
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ophalen lukte niet')
    } finally {
      setLoading(false)
    }
  }, [endpoint, pick])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="page">
      <Panel title={title} meta={loading ? 'Laden…' : `${rows.length} regels`}>
        {error ? <div className="notice notice--error">{error}</div> : null}
        {!error && rows.length === 0 && !loading ? (
          <EmptyState title={emptyTitle} hint={emptyHint} />
        ) : null}
        {rows.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column.key}>{column.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={String(row.id ?? index)}>
                  {columns.map((column) => (
                    <td key={column.key}>{render(row[column.key], column.kind)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </Panel>
    </div>
  )
}
