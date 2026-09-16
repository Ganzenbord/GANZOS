import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Dashboard } from '../api/types'

/** Haalt het dashboard op en ververst het periodiek.
 *
 *  Eén aanroep voor alle panelen. De backend leest wat de scheduler al heeft
 *  opgehaald, dus dit belast geen enkele externe partij. */
export function useDashboard(intervalMs = 30_000) {
  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const abortRef = useRef<AbortController | null>(null)

  const refresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const result = await api<Dashboard>('/dashboard', { signal: controller.signal })
      setData(result)
      setError(null)
    } catch (err) {
      if (controller.signal.aborted) return
      setError(err instanceof ApiError ? err.message : 'Ganz is niet bereikbaar')
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), intervalMs)

    // Terug op het scherm? Meteen verversen; anders kijk je naar cijfers van een
    // uur geleden.
    const onVisible = () => {
      if (document.visibilityState === 'visible') void refresh()
    }
    document.addEventListener('visibilitychange', onVisible)

    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
      abortRef.current?.abort()
    }
  }, [refresh, intervalMs])

  return { data, error, loading, refresh }
}
