/* Opmaak in Nederlands formaat: punt voor duizendtallen, komma voor decimalen. */

const nlNumber = new Intl.NumberFormat('nl-NL')
const nlMoney = new Intl.NumberFormat('nl-NL', {
  style: 'currency',
  currency: 'EUR',
  minimumFractionDigits: 2,
})
const nlTime = new Intl.DateTimeFormat('nl-NL', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})
const nlDate = new Intl.DateTimeFormat('nl-NL', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
})

/** Bedragen komen als tekst binnen; hier pas worden het getallen om te tonen. */
export function money(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const amount = typeof value === 'string' ? Number.parseFloat(value) : value
  if (!Number.isFinite(amount)) return '—'
  return nlMoney.format(amount)
}

export function moneyIn(value: string | number | null | undefined, currency: string): string {
  if (value === null || value === undefined) return '—'
  const amount = typeof value === 'string' ? Number.parseFloat(value) : value
  if (!Number.isFinite(amount)) return '—'
  return new Intl.NumberFormat('nl-NL', { style: 'currency', currency }).format(amount)
}

/** Grote getallen korter: 2.840.000 wordt 2,84M. Onder de 10.000 blijft het voluit. */
export function compactNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (Math.abs(value) >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(2).replace('.', ',').replace(/,00$/, '')}M`
  }
  if (Math.abs(value) >= 100_000) {
    return `${Math.round(value / 1000)}K`
  }
  return nlNumber.format(value)
}

export function plainNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : nlNumber.format(value)
}

export function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const rounded = Math.round(value * 10) / 10
  const text = rounded.toFixed(1).replace('.', ',')
  return `${rounded > 0 ? '+' : ''}${text}%`
}

export function clockTime(value: string | Date | null | undefined): string {
  if (!value) return '—'
  const date = typeof value === 'string' ? new Date(value) : value
  return Number.isNaN(date.getTime()) ? '—' : nlTime.format(date)
}

export function longDate(value: string | Date): string {
  const date = typeof value === 'string' ? new Date(value) : value
  return nlDate.format(date)
}

export function shortDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('nl-NL', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

/** "18 min geleden" — voor het melden van verouderde gegevens. */
export function relativeSince(value: string | null | undefined, now: number = Date.now()): string {
  if (!value) return 'nooit'
  const then = new Date(value).getTime()
  if (Number.isNaN(then)) return 'onbekend'
  const minutes = Math.floor((now - then) / 60000)
  if (minutes < 1) return 'zojuist'
  if (minutes < 60) return `${minutes} min geleden`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} uur geleden`
  const days = Math.floor(hours / 24)
  return `${days} dag${days === 1 ? '' : 'en'} geleden`
}

/** "1d 13u 42m" — leesbaar, terwijl de berekening op exacte seconden blijft. */
export function humanCountdown(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—'
  const total = Math.max(0, Math.floor(seconds))
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = total % 60
  if (days > 0) return `${days}d ${hours}u ${minutes}m`
  if (hours > 0) return `${hours}u ${minutes}m`
  if (minutes > 0) return `${minutes}m ${String(secs).padStart(2, '0')}s`
  return `${secs}s`
}

export const PLATFORM_LABEL: Record<string, string> = {
  youtube: 'YouTube',
  instagram: 'Instagram',
  tiktok: 'TikTok',
}

export const ACCOUNT_TYPE_LABEL: Record<string, string> = {
  bank: 'Bank',
  savings: 'Spaargeld',
  crypto_wallet: 'Crypto',
  exchange: 'Exchange',
  broker: 'Broker',
  investment: 'Beleggingen',
  other: 'Overig',
}

export const STATUS_LABEL: Record<string, string> = {
  connected: 'Gekoppeld',
  syncing: 'Bezig',
  sync_failed: 'Synchronisatie mislukt',
  reauth_required: 'Opnieuw inloggen',
  not_configured: 'Niet gekoppeld',
  disabled: 'Uitgezet',
  scheduled: 'Gepland',
  uploading: 'Bezig',
  completed: 'Klaar',
  failed: 'Mislukt',
  cancelled: 'Geannuleerd',
  waiting_confirmation: 'Wacht op OK',
}
