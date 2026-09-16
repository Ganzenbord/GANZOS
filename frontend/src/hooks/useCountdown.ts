import { useEffect, useRef, useState } from 'react'

/** Telt af naar een exact moment.
 *
 *  Elke tik wordt het verschil opnieuw uit de twee tijdstempels gehaald in plaats van
 *  er een seconde af te trekken. Aftrekken loopt scheef zodra een tik iets te laat
 *  komt, en na een uur ben je merkbaar de weg kwijt. Dit blijft altijd kloppen — ook
 *  nadat de laptop dicht is geweest. */
export function useCountdown(
  targetIso: string | null | undefined,
  offsetMs: number,
  onReachedZero?: () => void,
): number | null {
  const compute = () => {
    if (!targetIso) return null
    const target = new Date(targetIso).getTime()
    if (Number.isNaN(target)) return null
    return Math.round((target - (Date.now() + offsetMs)) / 1000)
  }

  const [seconds, setSeconds] = useState<number | null>(compute)
  const firedRef = useRef(false)
  const callbackRef = useRef(onReachedZero)
  callbackRef.current = onReachedZero

  useEffect(() => {
    firedRef.current = false
    setSeconds(compute())

    const timer = window.setInterval(() => {
      const remaining = compute()
      setSeconds(remaining)
      if (remaining !== null && remaining <= 0 && !firedRef.current) {
        // Eén keer melden dat het moment daar is; daarna haalt het scherm zelf de
        // nieuwe status op.
        firedRef.current = true
        callbackRef.current?.()
      }
    }, 1000)

    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetIso, offsetMs])

  return seconds
}
