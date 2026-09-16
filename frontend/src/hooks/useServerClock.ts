import { useEffect, useMemo, useState } from 'react'

/** Het verschil tussen de klok van de server en die van deze computer.
 *
 *  Alles wat met tijd te maken heeft rekent hiermee. Staat de pc een paar minuten
 *  verkeerd, dan klopt de aftelling nog steeds. */
export function useServerOffset(serverTime: string | null | undefined): number {
  return useMemo(() => {
    if (!serverTime) return 0
    const server = new Date(serverTime).getTime()
    if (Number.isNaN(server)) return 0
    return server - Date.now()
  }, [serverTime])
}

/** Een klok die elke seconde bijwerkt, gebaseerd op de servertijd. */
export function useServerNow(offset: number): Date {
  const [now, setNow] = useState(() => new Date(Date.now() + offset))

  useEffect(() => {
    setNow(new Date(Date.now() + offset))
    const timer = window.setInterval(() => setNow(new Date(Date.now() + offset)), 1000)
    return () => window.clearInterval(timer)
  }, [offset])

  return now
}
