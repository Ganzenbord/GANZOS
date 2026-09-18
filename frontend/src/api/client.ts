/* Alle verkeer met de backend loopt hierlangs.

   Twee tokens, met een verschillende taak. Het inlogtoken gaat mee bij elk verzoek en is
   maar een kwartier geldig — raakt het weg, dan is de schade klein. Het vernieuwingstoken
   blijft twee maanden geldig en wordt alleen gebruikt om een nieuw inlogtoken te halen; hij
   hoort bij één apparaat en is op de server in te trekken.

   Allebei in localStorage, want ze moeten een herstart overleven. Het bevestigingstoken
   bewust niet: dat is vijf minuten geldig en hoort niet op schijf achter te blijven. */

import type { Device } from './types'

const TOKEN_KEY = 'ganz.token'
const REFRESH_KEY = 'ganz.refresh'

/** Waar de backend draait.
 *
 *  In de browser is dat `/api` op dezelfde host — dat werkt met de proxy van Vite en achter
 *  een webserver. In de desktopschil kan dat niet: die laadt de pagina van schijf (file://),
 *  en dan wijst een relatief pad nergens heen. Electron geeft het adres daarom mee via
 *  `window.ganz`, en dat wordt hier eenmalig opgehaald.
 */
declare global {
  interface Window {
    ganz?: { apiUrl: () => Promise<string>; platform?: string }
  }
}

const WEB_BASE = (import.meta.env.VITE_API_URL ?? '/api').replace(/\/$/, '')
let base = WEB_BASE

/** Haalt het adres op bij de schil. Roep dit één keer aan vóór het eerste verzoek. */
export async function resolveApiBase(): Promise<string> {
  if (!window.ganz) return base
  try {
    const url = await window.ganz.apiUrl()
    // De backend zet zijn endpoints onder /api; de schil kent alleen de host.
    base = `${url.replace(/\/+$/, '')}/api`
  } catch {
    /* Lukt het niet, dan blijft het relatieve pad staan; dat faalt met een nette melding. */
  }
  return base
}

export function apiBase(): string {
  return base
}

let confirmationToken: string | null = null

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* Privémodus: dan werkt de sessie alleen tot je het tabblad sluit. */
  }
}

export function getRefreshToken(): string | null {
  try {
    return localStorage.getItem(REFRESH_KEY)
  } catch {
    return null
  }
}

export function setRefreshToken(token: string | null) {
  try {
    if (token) localStorage.setItem(REFRESH_KEY, token)
    else localStorage.removeItem(REFRESH_KEY)
  } catch {
    /* Privémodus: dan ben je na het sluiten van het tabblad weer uitgelogd. */
  }
}

/** Zo heet dit apparaat in je lijst met apparaten. Een geheugensteuntje, verder niets. */
function apparaatnaam(): string {
  if (window.ganz?.platform) return `Ganz-app op ${window.ganz.platform}`
  try {
    if (window.matchMedia('(max-width: 768px)').matches) return 'Telefoon (browser)'
  } catch {
    /* matchMedia ontbreekt in een enkele omgeving; dan de algemene naam. */
  }
  return 'Browser'
}

/* Eén vernieuwing tegelijk. Vraagt het scherm tien panelen op en verlopen ze allemaal
   tegelijk, dan zouden tien verzoeken tegelijk gaan vernieuwen — en negen daarvan komen
   aan met een token dat net vervangen is. De server ziet dat als hergebruik en sluit de
   sessie. Dus: wie merkt dat het moet, zet het in gang; de rest wacht op diezelfde belofte. */
let bezigMetVernieuwen: Promise<boolean> | null = null

async function haalNieuwToken(): Promise<boolean> {
  const refresh = getRefreshToken()
  if (!refresh) return false
  try {
    const response = await fetch(`${base}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    })
    if (!response.ok) {
      // De sessie is ingetrokken of verlopen. Alles weg, en terug naar het inlogscherm.
      setToken(null)
      setRefreshToken(null)
      return false
    }
    const body = await response.json()
    setToken(body.access_token)
    setRefreshToken(body.refresh_token ?? null)
    return true
  } catch {
    // Netwerk weg. Het token weggooien zou je uitloggen omdat de wifi hapert.
    return false
  }
}

function vernieuw(): Promise<boolean> {
  if (!bezigMetVernieuwen) {
    bezigMetVernieuwen = haalNieuwToken().finally(() => {
      bezigMetVernieuwen = null
    })
  }
  return bezigMetVernieuwen
}

export function setConfirmationToken(token: string | null) {
  confirmationToken = token
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }

  /** De backend vraagt om een tweede bevestiging met het wachtwoord. */
  get needsConfirmation() {
    return this.status === 428
  }
}

interface Options {
  method?: string
  body?: unknown
  confirm?: boolean
  signal?: AbortSignal
  /** Houd de sessie in stand bij een 401.
   *
   *  Normaal betekent 401 dat het inlogtoken op is, en dan hoor je terug naar het
   *  inlogscherm. Bij het bevestigen en bij het instellen van een pincode betekent
   *  hetzelfde nummer iets heel anders: het getikte geheim klopt niet. Zonder dit
   *  onderscheid word je uitgelogd omdat je je pincode verkeerd intikt — en op een
   *  telefoon tik je die geheid een keer mis. */
  keepSession?: boolean
}

export async function api<T>(
  path: string,
  options: Options = {},
  alGeprobeerd = false,
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (options.confirm && confirmationToken) headers['X-Ganz-Confirmation'] = confirmationToken

  const response = await fetch(`${base}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  })

  if (response.status === 401 && !options.keepSession) {
    // Eerst proberen te vernieuwen. Een inlogtoken van een kwartier verloopt nu eenmaal
    // midden in het gebruik, en daar hoort de gebruiker niets van te merken.
    if (!alGeprobeerd && (await vernieuw())) {
      return api<T>(path, options, true)
    }
    setToken(null)
    setRefreshToken(null)
    throw new ApiError(401, 'Je sessie is verlopen. Log opnieuw in.')
  }
  if (!response.ok) {
    let detail = `Er ging iets mis (${response.status})`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* Geen JSON terug; dan blijft de algemene melding staan. */
    }
    throw new ApiError(response.status, detail)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export async function login(email: string, password: string) {
  const result = await api<{ access_token: string; refresh_token?: string }>('/auth/login', {
    method: 'POST',
    body: { email, password, device_name: apparaatnaam() },
  })
  setToken(result.access_token)
  setRefreshToken(result.refresh_token ?? null)
  return result
}

/** De apparaten die op dit moment toegang hebben. */
export async function listSessions() {
  return api<Device[]>('/auth/sessions')
}

/** Gooit één apparaat eruit. Is het dit apparaat, dan ben je meteen uitgelogd. */
export async function revokeSession(id: number) {
  return api<{ revoked: number; message: string }>(`/auth/sessions/${id}`, { method: 'DELETE' })
}

export async function confirmWithPassword(password: string) {
  return confirmWith({ password })
}

/** Bevestigen met de pincode in plaats van het wachtwoord.
 *
 *  Bedoeld voor de telefoon: een heel wachtwoord intikken op een klein toetsenbord nodigt
 *  uit tot een korter wachtwoord, en dat is het tegenovergestelde van wat je wilt. De
 *  pincode is een tweede stap boven op het inloggen, geen vervanging ervan. */
export async function confirmWithPin(pin: string) {
  return confirmWith({ pin })
}

async function confirmWith(body: { password?: string; pin?: string }) {
  const result = await api<{ confirmation_token: string }>('/auth/confirm', {
    method: 'POST',
    body,
    keepSession: true,
  })
  setConfirmationToken(result.confirmation_token)
  return result.confirmation_token
}

/** Stel een pincode in, of wijzig hem. Je huidige wachtwoord is nodig. */
export async function setPin(password: string, pin: string) {
  await api('/auth/pin', { method: 'POST', body: { password, pin }, keepSession: true })
}

export async function logout() {
  // Eerst de server, dan pas de tokens weggooien: anders blijft de sessie daar openstaan
  // en zie je op je andere apparaten een telefoon in de lijst die allang is uitgelogd.
  try {
    await api('/auth/logout', { method: 'POST' })
  } catch {
    /* Lukt dat niet, dan is uitloggen op dít apparaat belangrijker dan netjes afmelden. */
  }
  setToken(null)
  setRefreshToken(null)
  setConfirmationToken(null)
}
