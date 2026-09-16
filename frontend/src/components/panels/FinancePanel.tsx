import type { FinanceOverview } from '../../api/types'
import { ACCOUNT_TYPE_LABEL, money, percent, relativeSince, clockTime } from '../../lib/format'
import { Panel } from '../ui/Panel'
import { EmptyState } from '../ui/EmptyState'
import { StatusDot } from '../ui/StatusDot'

/** Het totaal in euro's.
 *
 *  Staat er niets gekoppeld, dan staat er € 0,00 met de reden erbij — het paneel doet
 *  nooit alsof er een rekening hangt die er niet is. */
export function FinancePanel({
  finance,
  onOpen,
}: {
  finance: FinanceOverview
  onOpen?: () => void
}) {
  if (finance.connected_accounts === 0) {
    return (
      <Panel title="Finance">
        <div className="bignum">{money('0')}</div>
        <div className="numlabel">Totaal vermogen</div>
        <EmptyState
          title="Nog geen financiële accounts gekoppeld"
          actionLabel="Accounts koppelen"
          onAction={onOpen}
        />
      </Panel>
    )
  }

  const trend = finance.trend_pct
  const trendClass = trend === null ? 'delta--none' : trend >= 0 ? 'delta--up' : 'delta--down'

  return (
    <Panel
      title="Finance"
      meta={
        finance.stale ? (
          <StatusDot tone="warn" label="Verouderd" />
        ) : (
          <StatusDot tone="ok" label="Live" />
        )
      }
      linkLabel="Alles bekijken"
      onLink={onOpen}
      footer={
        <span className="numlabel">
          {finance.stale
            ? `Laatste update ${relativeSince(finance.last_updated)}`
            : `Laatste update ${clockTime(finance.last_updated)}`}
        </span>
      }
    >
      <div className="bignum bignum--amber">{money(finance.total_eur)}</div>
      <div className="numlabel">
        Totaal vermogen{' '}
        <span className={`delta ${trendClass}`}>
          {trend === null ? '· nog geen trend' : `· ${percent(trend)} t.o.v. vorige week`}
        </span>
      </div>

      <div className="legend">
        {finance.breakdown.map((row) => (
          <div className="legend__row" key={row.account_type}>
            <span className="dot dot--idle" aria-hidden />
            <span className="legend__name">
              {ACCOUNT_TYPE_LABEL[row.account_type] ?? row.account_type}
            </span>
            <span className="legend__value">{money(row.total_eur)}</span>
          </div>
        ))}
      </div>

      {finance.excluded_accounts.length > 0 ? (
        <div className="notice notice--warn" style={{ marginTop: 12 }}>
          {finance.excluded_accounts.length} account(s) tellen niet mee:{' '}
          {finance.excluded_accounts.map((row) => row.name).join(', ')}
        </div>
      ) : null}
    </Panel>
  )
}
