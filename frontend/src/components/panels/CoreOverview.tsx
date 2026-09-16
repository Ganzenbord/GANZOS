import type { CoreStatus } from '../../api/types'
import { Panel } from '../ui/Panel'
import { StatusDot, toneFor } from '../ui/StatusDot'
import { IconCore, IconLink, IconMic, IconSettings, IconSkills } from '../ui/Icons'

const VOICE_LABEL: Record<string, string> = {
  listening: 'Luistert naar omgeving',
  unavailable: 'Niet bereikbaar',
  not_configured: 'Geen stem gekoppeld',
}

export function CoreOverview({ core }: { core: CoreStatus }) {
  const rows = [
    {
      icon: <IconCore />,
      label: 'Core',
      sub: core.core_detail,
      right: <StatusDot tone={toneFor(core.core_status)} label="Actief" />,
    },
    {
      icon: <IconMic />,
      label: 'Stem',
      sub: VOICE_LABEL[core.voice_status] ?? 'Onbekend',
      right: (
        <StatusDot
          tone={toneFor(core.voice_status)}
          label={core.voice_status === 'listening' ? 'Luistert' : 'Uit'}
        />
      ),
    },
    {
      icon: <IconSkills />,
      label: 'Skills',
      sub: `${core.skills_count} geleerd`,
      right: <strong>{core.skills_count}</strong>,
    },
    {
      icon: <IconLink />,
      label: 'Integraties',
      sub: `${core.integrations_connected} van ${core.integrations_total} gekoppeld`,
      right: <strong>{core.integrations_total}</strong>,
    },
    {
      icon: <IconSettings />,
      label: 'Systeem',
      sub: core.system_detail,
      right: (
        <StatusDot
          tone={toneFor(core.system_status)}
          label={core.system_status === 'optimal' ? 'Optimaal' : 'Let op'}
        />
      ),
    },
  ]

  return (
    <Panel title="Core overzicht" tight>
      <div className="rows">
        {rows.map((row) => (
          <div className="rowitem" key={row.label}>
            <span className="icon-badge">{row.icon}</span>
            <span>
              <span className="rowitem__label">{row.label}</span>
              <br />
              <span className="rowitem__sub">{row.sub}</span>
            </span>
            <span className="rowitem__right">{row.right}</span>
          </div>
        ))}
      </div>
    </Panel>
  )
}
