import type { SocialOverview } from '../../api/types'
import { PLATFORM_LABEL, compactNumber, moneyIn, percent, relativeSince } from '../../lib/format'
import { Panel } from '../ui/Panel'
import { EmptyState } from '../ui/EmptyState'
import { StatusDot, toneFor } from '../ui/StatusDot'

/** Het totaal van álle gekoppelde kanalen samen.
 *
 *  Een streepje betekent dat het platform die metriek niet levert. Dat is iets anders
 *  dan nul, en dat verschil blijft zichtbaar in plaats van weggerekend te worden. */
export function SocialStatsPanel({
  social,
  onOpen,
}: {
  social: SocialOverview
  onOpen?: () => void
}) {
  if (social.channels_total === 0) {
    return (
      <Panel title="Social media stats" name="social">
        <EmptyState
          title="Nog geen social-kanalen gekoppeld"
          hint="Koppel YouTube, Instagram of TikTok om het totaal te zien."
          actionLabel="Kanaal koppelen"
          onAction={onOpen}
        />
      </Panel>
    )
  }

  return (
    <Panel
      title="Social media stats"
      name="social"
      meta={<StatusDot tone="ok" label={`${social.channels_counted} kanalen`} />}
      linkLabel="Alles bekijken"
      onLink={onOpen}
      footer={
        <span className="numlabel">Laatste update {relativeSince(social.last_updated)}</span>
      }
    >
      <div className="stats">
        <div className="stat">
          <div className="stat__value">{compactNumber(social.followers)}</div>
          <div className="stat__label">Totaal volgers</div>
          <div
            className={`delta ${
              social.growth_pct === null
                ? 'delta--none'
                : social.growth_pct >= 0
                  ? 'delta--up'
                  : 'delta--down'
            }`}
          >
            {social.growth_pct === null ? 'geen groeicijfer' : percent(social.growth_pct)}
          </div>
        </div>
        <div className="stat">
          <div className="stat__value">{compactNumber(social.views)}</div>
          <div className="stat__label">Views</div>
        </div>
        <div className="stat">
          <div className="stat__value">{compactNumber(social.likes)}</div>
          <div className="stat__label">Likes</div>
        </div>
      </div>

      <div style={{ marginTop: 14 }}>
        <div className="stat__label">Inkomsten deze maand</div>
        <div style={{ fontSize: 17, fontWeight: 600 }}>
          {social.revenue_available ? (
            moneyIn(social.revenue, social.revenue_currency ?? 'EUR')
          ) : (
            <span style={{ color: 'var(--text-dim)', fontSize: 13, fontWeight: 400 }}>
              Niet beschikbaar
            </span>
          )}
        </div>
      </div>

      <div className="legend">
        {social.platforms.map((row) => (
          <div className="legend__row" key={row.platform}>
            <span className="dot dot--ok" aria-hidden />
            <span className="legend__name">
              {PLATFORM_LABEL[row.platform] ?? row.platform}
              {row.channels > 1 ? ` (${row.channels})` : ''}
            </span>
            <span className="legend__value">{compactNumber(row.followers)}</span>
          </div>
        ))}
      </div>

      {social.attention.length > 0 ? (
        <div className="notice notice--warn" style={{ marginTop: 12 }}>
          <StatusDot tone={toneFor(social.attention[0].status)} />
          {social.attention.length === 1
            ? `${social.attention[0].channel_name}: opnieuw inloggen`
            : `${social.attention.length} kanalen vragen aandacht`}
        </div>
      ) : null}
    </Panel>
  )
}
