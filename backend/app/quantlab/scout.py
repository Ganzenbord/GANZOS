"""De Scout: data binnenhalen, ruw wegzetten, kloppen.

Eén taak, geen beslissingen (sectie 6). De Scout kijkt niet naar prijzen, filtert niets en
weet niet wat een hypothese is. Hij haalt op, zet weg en laat weten dat hij nog leeft.

**Hij draait in zijn eigen proces**, niet in de scheduler van de API. Dat is het advies uit
fase 0 en er zijn drie redenen voor: de scheduler draait in hetzelfde proces als de
verzoeken (en concurreert dus met het bedienen van de app), zijn jobstore zit in het
geheugen (dus na een herstart is er niets), en een gat in een append-only corpus kun je
nooit meer vullen. Er is een test die faalt als de scheduler ooit iets uit `quantlab`
importeert.

De hartslag hieronder is dezelfde die de risicolaag uit fase 1 gebruikt: hoort het lab niets
meer van de Scout, dan gaan er geen nieuwe posities open. Dat is de dead-man switch, en hij
werkt alleen als de Scout hem ook echt zet.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.database import Database
from app.models.quantlab import QuantIngestRun
from app.quantlab.feed import FeedSource, RawEvent
from app.services import quant_data_service, quant_risk_service

logger = logging.getLogger("ganz.quantlab.scout")

# Hoe vaak de Scout laat weten dat hij leeft. Ruim onder de 120 seconden die de risicolaag
# aanhoudt, zodat een enkele trage ronde niet meteen de dead-man switch trekt.
DEFAULT_HEARTBEAT_SECONDS = 15

# Hoeveel events er in één keer worden weggeschreven. Groter is sneller maar verliest meer
# bij een klapper; 200 is bij tien events per seconde twintig seconden werk.
DEFAULT_BATCH_SIZE = 200


@dataclass(frozen=True)
class ScoutResult:
    run_id: int
    events: int
    ticks: int
    duplicates: int
    parse_failures: int
    bytes_stored: int
    started_at: datetime
    stopped_at: datetime
    stop_reason: str


class Scout:
    """De opnamelus.

    Krijgt een `Database` mee en niet een sessie: dit is een eigen proces en beheert zijn
    eigen transacties. Elke batch is een eigen commit, zodat een klapper hoogstens de
    laatste batch kost.
    """

    def __init__(
        self,
        database: Database,
        *,
        source: FeedSource,
        component: str = "scout",
        heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._database = database
        self._source = source
        self._component = component
        self._heartbeat_seconds = heartbeat_seconds
        self._batch_size = batch_size
        self.events_stored = 0

    async def run(
        self, *, stop: asyncio.Event | None = None, max_events: int | None = None
    ) -> ScoutResult:
        gestart = datetime.now(timezone.utc)
        run_id = await self._open_run(gestart)
        batch: list[RawEvent] = []
        events = ticks = mislukt = 0
        bytes_totaal = 0
        laatste_hartslag = 0.0
        reden = "source_exhausted"

        async def wegschrijven() -> None:
            nonlocal batch, ticks, mislukt, bytes_totaal
            if not batch:
                return
            async with self._database.session() as session:
                bytes_totaal += await quant_data_service.store_events(
                    session, batch, ingest_run_id=run_id
                )
                nieuw, fout = await quant_data_service.normalize_pending(session)
                await session.commit()
            ticks += nieuw
            mislukt += fout
            batch = []

        try:
            async for event in self._source.events():
                batch.append(event)
                events += 1
                self.events_stored = events

                if len(batch) >= self._batch_size:
                    await wegschrijven()

                nu = asyncio.get_running_loop().time()
                if nu - laatste_hartslag >= self._heartbeat_seconds:
                    await self._klop()
                    laatste_hartslag = nu

                if stop is not None and stop.is_set():
                    reden = "asked_to_stop"
                    break
                if max_events is not None and events >= max_events:
                    reden = "max_events"
                    break
                # Eén keer de lus teruggeven aan de rest van het proces, zodat een
                # stopverzoek ook aankomt bij een bron die zonder wachten blijft leveren.
                await asyncio.sleep(0)

            await wegschrijven()
        except asyncio.CancelledError:
            await wegschrijven()
            await self._sluit_run(run_id, events, ticks, mislukt, bytes_totaal, "cancelled")
            raise
        except Exception:
            # Een run die openblijft, is een gat in de boekhouding van het corpus. Dus
            # eerst afsluiten met de reden, dan de fout doorlaten.
            await wegschrijven()
            await self._sluit_run(
                run_id, events, ticks, mislukt, bytes_totaal, "source_failed"
            )
            raise

        await self._klop()
        gestopt = await self._sluit_run(
            run_id, events, ticks, mislukt, bytes_totaal, reden
        )
        dubbel = await self._dubbele(run_id)
        logger.info(
            "Scout stopte na %s events (%s ticks, %s onleesbaar): %s",
            events,
            ticks,
            mislukt,
            reden,
        )
        return ScoutResult(
            run_id=run_id,
            events=events,
            ticks=ticks,
            duplicates=dubbel,
            parse_failures=mislukt,
            bytes_stored=bytes_totaal,
            started_at=gestart,
            stopped_at=gestopt,
            stop_reason=reden,
        )

    async def _open_run(self, gestart: datetime) -> int:
        async with self._database.session() as session:
            run = QuantIngestRun(source=self._source.name, started_at=gestart)
            session.add(run)
            await session.commit()
            return run.id

    async def _sluit_run(
        self,
        run_id: int,
        events: int,
        ticks: int,
        mislukt: int,
        bytes_totaal: int,
        reden: str,
    ) -> datetime:
        gestopt = datetime.now(timezone.utc)
        async with self._database.session() as session:
            run = await session.get(QuantIngestRun, run_id)
            if run is not None:
                run.events = events
                run.ticks = ticks
                run.parse_failures = mislukt
                run.bytes_stored = bytes_totaal
                run.stopped_at = gestopt
                run.stop_reason = reden
            await session.commit()
        return gestopt

    async def _dubbele(self, run_id: int) -> int:
        from sqlalchemy import func, select

        from app.models.quantlab import QuantRawEvent

        async with self._database.session() as session:
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(QuantRawEvent)
                    .where(
                        QuantRawEvent.ingest_run_id == run_id,
                        QuantRawEvent.duplicate_of_id.is_not(None),
                    )
                )
                or 0
            )

    async def _klop(self) -> None:
        """"Ik leef nog." Dit is de dead-man switch van de risicolaag."""
        async with self._database.session() as session:
            await quant_risk_service.heartbeat(session, component=self._component)
            await session.commit()
