import type { SystemStatus } from '../../api/types'
import { Panel } from '../ui/Panel'
import { StatusDot, toneFor } from '../ui/StatusDot'

/** Een lijngrafiekje van de laatste metingen. Geen bibliotheek: het is één pad. */
function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) {
    return <div className="numlabel" style={{ marginTop: 10 }}>Nog te weinig metingen</div>
  }
  const width = 220
  const height = 42
  const max = Math.max(...values, 100)
  const step = width / (values.length - 1)
  const points = values
    .map((value, index) => `${index * step},${height - (value / max) * height}`)
    .join(' ')

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} aria-hidden>
      <polyline points={points} fill="none" stroke="var(--amber)" strokeWidth="1.5" />
    </svg>
  )
}

function Meter({ label, value }: { label: string; value: number }) {
  const tone = value >= 90 ? 'var(--red)' : value >= 70 ? 'var(--amber)' : 'var(--green)'
  return (
    <div className="meter">
      <div className="meter__value" style={{ color: tone }}>
        {Math.round(value)}%
      </div>
      <div className="meter__label">{label}</div>
    </div>
  )
}

export function SystemMonitor({ system }: { system: SystemStatus }) {
  return (
    <Panel
      title="System monitor"
      name="system"
      meta={<StatusDot tone={toneFor(system.status)} label={system.status_detail} />}
    >
      <div className="meters">
        <Meter label="CPU" value={system.cpu_pct} />
        <Meter label="RAM" value={system.ram_pct} />
        <Meter label="DISK" value={system.disk_pct} />
      </div>
      <div style={{ marginTop: 12 }}>
        <Sparkline values={system.history.map((sample) => sample.cpu_pct)} />
      </div>
    </Panel>
  )
}
