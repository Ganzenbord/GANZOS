import type { FeedItem } from '../../api/types'
import { clockTime } from '../../lib/format'
import { Panel } from '../ui/Panel'
import { EmptyState } from '../ui/EmptyState'

/** Welke soort melding het is, bepaalt het labeltje. Fouten zijn rood, de rest niet. */
function kindOf(action: string): { tag: string; tone: 'ok' | 'warn' | 'error' | 'idle' } {
  if (action.endsWith('_FAILED')) return { tag: 'FOUT', tone: 'error' }
  if (action.includes('REAUTH')) return { tag: 'LET OP', tone: 'warn' }
  if (action.startsWith('UPLOAD')) return { tag: 'UPLOAD', tone: 'ok' }
  if (action.startsWith('TODO')) return { tag: 'TAAK', tone: 'idle' }
  return { tag: 'LIVE', tone: 'ok' }
}

export function LiveFeed({ items, onOpen }: { items: FeedItem[]; onOpen?: () => void }) {
  return (
    <Panel title="Live intelligence feed" linkLabel="Alles bekijken" onLink={onOpen} tight>
      {items.length === 0 ? (
        <EmptyState title="Nog niets gebeurd" hint="Zodra Ganz iets doet, staat het hier." />
      ) : (
        <div className="rows">
          {items.map((item) => {
            const kind = kindOf(item.action)
            return (
              <div className="rowitem" key={item.id}>
                <span className={`dot dot--${kind.tone}`} aria-hidden />
                <span style={{ minWidth: 0 }}>
                  <span className="rowitem__label">{kind.tag}</span>
                  <br />
                  <span className="rowitem__sub">{item.message}</span>
                </span>
                <span className="rowitem__right">{clockTime(item.created_at)}</span>
              </div>
            )
          })}
        </div>
      )}
    </Panel>
  )
}
