export type DotTone = 'ok' | 'warn' | 'error' | 'idle'

/** Vertaalt een status van de backend naar een kleur.
 *  Rood is voorbehouden aan echte problemen; "nog niet gekoppeld" is grijs. */
export function toneFor(status: string | null | undefined): DotTone {
  switch (status) {
    case 'connected':
    case 'active':
    case 'completed':
    case 'done':
    case 'optimal':
    case 'listening':
      return 'ok'
    case 'sync_failed':
    case 'failed':
    case 'error':
      return 'error'
    case 'reauth_required':
    case 'warning':
    case 'waiting':
    case 'waiting_confirmation':
    case 'uploading':
    case 'running':
      return 'warn'
    default:
      return 'idle'
  }
}

export function StatusDot({ tone, label }: { tone: DotTone; label?: string }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span className={`dot dot--${tone}`} aria-hidden />
      {label ? <span>{label}</span> : null}
    </span>
  )
}
