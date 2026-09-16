import type { Integration, LlmStatus } from '../../api/types'
import { PLATFORM_LABEL, clockTime } from '../../lib/format'
import { Panel } from '../ui/Panel'
import { EmptyState } from '../ui/EmptyState'
import { StatusDot, toneFor } from '../ui/StatusDot'

export function MemoryInsights({ memory }: { memory: { memories: number; sessions: number } }) {
  return (
    <Panel title="Memory insights">
      <div className="stats">
        <div className="stat">
          <div className="stat__value">{memory.memories}</div>
          <div className="stat__label">Herinneringen</div>
        </div>
        <div className="stat">
          <div className="stat__value">{memory.sessions}</div>
          <div className="stat__label">Sessies</div>
        </div>
      </div>
    </Panel>
  )
}

export function LlmStatusPanel({ providers }: { providers: LlmStatus[] }) {
  return (
    <Panel title="LLM status" tight>
      {providers.length === 0 ? (
        <EmptyState
          title="Geen taalmodel gekoppeld"
          hint="Stel een provider in bij Instellingen."
        />
      ) : (
        <div className="rows">
          {providers.map((provider) => (
            <div className="rowitem" key={provider.provider}>
              <StatusDot tone={toneFor(provider.status)} />
              <span style={{ minWidth: 0 }}>
                <span className="rowitem__label">{provider.provider}</span>
                <br />
                <span className="rowitem__sub">{provider.model ?? provider.detail ?? '—'}</span>
              </span>
              <span className="rowitem__right">
                {provider.latency_ms !== null ? `${provider.latency_ms} ms` : clockTime(provider.checked_at)}
              </span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

export function IntegrationsPanel({
  integrations,
  onOpen,
}: {
  integrations: Integration[]
  onOpen?: () => void
}) {
  return (
    <Panel title="Integraties" linkLabel="Alles bekijken" onLink={onOpen} tight>
      {integrations.length === 0 ? (
        <EmptyState title="Nog niets gekoppeld" actionLabel="Integratie koppelen" onAction={onOpen} />
      ) : (
        <div className="rows">
          {integrations.map((integration) => (
            <div className="rowitem" key={integration.id}>
              <StatusDot tone={toneFor(integration.status)} />
              <span className="rowitem__label">
                {PLATFORM_LABEL[integration.key] ?? integration.name}
              </span>
              <span className="rowitem__right">
                {integration.status === 'connected'
                  ? 'Gekoppeld'
                  : integration.status === 'reauth_required'
                    ? 'Opnieuw inloggen'
                    : 'Niet gekoppeld'}
              </span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}
