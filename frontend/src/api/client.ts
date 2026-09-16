/* Alle verkeer met de backend loopt hierlangs.

   Het inlogtoken staat in localStorage; het bevestigingstoken bewust niet, want dat
   is kort geldig en hoort niet op schijf te blijven staan na het sluiten. */

const TOKEN_KEY = 'ganz.token'
const BASE = (import.meta.env.VITE_API_URL ?? '/api').replace(/\/$/, '')

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
}

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (options.confirm && confirmationToken) headers['X-Ganz-Confirmation'] = confirmationToken

  const response = await fetch(`${BASE}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  })

  if (response.status === 401) {
    setToken(null)
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
  const result = await api<{ access_token: string }>('/auth/login', {
    method: 'POST',
    body: { email, password },
  })
  setToken(result.access_token)
  return result
}

export async function confirmWithPassword(password: string) {
  const result = await api<{ confirmation_token: string }>('/auth/confirm', {
    method: 'POST',
    body: { password },
  })
  setConfirmationToken(result.confirmation_token)
  return result.confirmation_token
}

export function logout() {
  setToken(null)
  setConfirmationToken(null)
}
