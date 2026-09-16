import type { CoreStatus } from '../../api/types'

/** De centrale cirkel.
 *
 *  Hier staat uitsluitend het woord GANZ. Geen versienummer, geen CPU, geen status —
 *  dat staat allemaal in de panelen eromheen. De ring beweegt alleen als Ganz
 *  daadwerkelijk luistert of iets uitvoert; staat hij stil, dan staat de ring stil. */
export function GanzCircle({ core, busy }: { core: CoreStatus; busy: boolean }) {
  const caption =
    core.voice_status === 'listening'
      ? 'Luistert naar de omgeving'
      : busy
        ? 'Bezig met uitvoeren'
        : core.core_detail

  return (
    <section className="panel" data-panel="circle">
      <div className="circle-panel">
        <div>
          <div className={busy ? 'circle circle--busy' : 'circle'}>
            <span className="circle__ring" />
            <span className="circle__ring circle__ring--inner" />
            <span className="circle__word">GANZ</span>
          </div>
          <p className="circle-caption">{caption}</p>
        </div>
      </div>
    </section>
  )
}
