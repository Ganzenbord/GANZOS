"""De datalaag met de database eronder (sectie 11).

Vier dingen: opslaan, narekenen, normaliseren en replayen. Plus twee rapporten die
daarop leunen — datakwaliteit en opslaggroei.

De afspraak die alles bij elkaar houdt: **`quant_raw_events` is de waarheid en wordt nooit
gewijzigd.** `quant_market_ticks` is er volledig uit herbouwbaar, en dat is niet alleen
netjes maar de enige manier om te bewijzen dat een replay hetzelfde oplevert: gooi het
afgeleide deel weg, bouw het opnieuw op, vergelijk de afdruk.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.quantlab import QuantIngestRun, QuantMarketTick, QuantRawEvent
from app.quantlab.dataquality import DataQualityReport, quality_report
from app.quantlab.feed import FeedSource, RawEvent, canonical_hash, chain_step
from app.quantlab.normalize import MarketTick, Normalizer, normalizer_for, tick_digest

logger = logging.getLogger("ganz.quantlab.data")

# Hoe ver terug er naar een identiek event wordt gekeken om een dubbele te markeren. Een
# feed die hetzelfde event na een herverbinding opnieuw stuurt, doet dat binnen seconden;
# een identieke payload van een uur later is gewoon een nieuw event.
# Hoeveel waarden er in één IN-clausule gaan. PostgreSQL staat hoogstens 32767 parameters
# per query toe; 5000 is ruim onder die grens en nog steeds één query per vijfduizend.
IN_CHUNK = 5000

# Hoeveel events `record()` in één keer wegzet. Niet alles in één transactie: bij drie dagen
# data zijn dat 150.000 rijen in het geheugen van de sessie, en dan wordt de identity map
# van SQLAlchemy zelf het probleem.
RECORD_BATCH = 2000


class CorpusBroken(RuntimeError):
    """De ruwe opslag klopt niet meer. Replayen heeft dan geen zin."""


@dataclass(frozen=True)
class ChainCheck:
    ok: bool
    events: int
    digest: str | None
    first_bad_seq: int | None
    explanation: str


@dataclass(frozen=True)
class IngestResult:
    events: int
    ticks: int
    duplicates: int
    parse_failures: int
    bytes_stored: int


@dataclass(frozen=True)
class ReplayResult:
    events: int
    ticks: int
    parse_failures: int
    digest: str
    since: datetime | None
    until: datetime | None


@dataclass(frozen=True)
class StorageReport:
    events: int
    ticks: int
    bytes_stored: int
    bytes_per_event: int
    measured_seconds: float
    first_received_at: datetime | None
    last_received_at: datetime | None
    projected_bytes_per_day: int
    projected_bytes_per_month: int
    explanation: str


async def _volgende_seq(session: AsyncSession) -> int:
    hoogste = await session.scalar(select(func.max(QuantRawEvent.seq)))
    return int(hoogste or 0) + 1


async def _laatste_chain(session: AsyncSession) -> str | None:
    return await session.scalar(
        select(QuantRawEvent.chain_hash)
        .order_by(QuantRawEvent.seq.desc())
        .limit(1)
    )


async def store_events(
    session: AsyncSession,
    events: Iterable[RawEvent],
    *,
    ingest_run_id: int | None = None,
) -> int:
    """Zet ruwe events weg, in de volgorde waarin ze binnenkwamen.

    Geeft het aantal bytes terug dat erin ging, zodat de Scout de groei kan bijhouden
    zonder er een aparte query voor te doen.
    """
    lijst = list(events)
    if not lijst:
        return 0

    seq = await _volgende_seq(session)
    vorige = await _laatste_chain(session)
    bytes_totaal = 0

    # De dubbele events in een query opzoeken en niet een per event. Dat laatste stond er
    # eerst, en het was geen detail: bij een corpus van 150.000 events waren dat 150.000
    # losse SELECTs, en dan duurt het opnemen van drie dagen data langer dan die drie
    # dagen zelf. Nu een query voor de hele batch, plus de hashes binnen de batch zelf.
    afdrukken = {canonical_hash(event.payload_raw) for event in lijst}
    bekend = await _bestaande_hashes(session, lijst[0].source, afdrukken)

    # Pas na het flushen hebben de nieuwe rijen een id, dus de eerste van een dubbel paar
    # binnen deze batch wordt per hash onthouden en achteraf gekoppeld.
    eerste_in_batch: dict[str, QuantRawEvent] = {}
    te_koppelen: list[tuple[QuantRawEvent, str]] = []

    for event in lijst:
        payload_hash = canonical_hash(event.payload_raw)
        vorige = chain_step(vorige, payload_hash)
        rij = QuantRawEvent(
            seq=seq,
            source=event.source,
            stream=event.stream,
            payload_raw=event.payload_raw,
            payload_hash=payload_hash,
            chain_hash=vorige,
            received_at=event.received_at,
            duplicate_of_id=bekend.get((event.stream, payload_hash)),
            ingest_run_id=ingest_run_id,
        )
        sleutel = f"{event.stream}:{payload_hash}"
        if rij.duplicate_of_id is None:
            eerder = eerste_in_batch.get(sleutel)
            if eerder is None:
                eerste_in_batch[sleutel] = rij
            else:
                te_koppelen.append((rij, sleutel))
        session.add(rij)
        bytes_totaal += len(event.payload_raw.encode("utf-8"))
        seq += 1

    await session.flush()
    for rij, sleutel in te_koppelen:
        rij.duplicate_of_id = eerste_in_batch[sleutel].id
    if te_koppelen:
        await session.flush()
    return bytes_totaal


async def _bestaande_hashes(
    session: AsyncSession, source: str, afdrukken: set[str]
) -> dict[tuple[str, str], int]:
    """Welke van deze afdrukken staan er al, en onder welk id.

    Alleen de eerste exemplaren (`duplicate_of_id IS NULL`), want daar wijst een dubbele
    naar. Niets wordt weggegooid: de ruwe opslag is append-only en een dubbele wordt
    alleen gemarkeerd.
    """
    uit: dict[tuple[str, str], int] = {}
    if not afdrukken:
        return uit
    # In stukken, want PostgreSQL staat hoogstens 32767 parameters per query toe. Dat
    # liep bij een corpus van drie dagen stuk, en SQLite had het nooit laten zien — een
    # argument om dit soort dingen tegen de echte database te proberen.
    lijst = list(afdrukken)
    for begin in range(0, len(lijst), IN_CHUNK):
        rijen = await session.execute(
            select(QuantRawEvent.stream, QuantRawEvent.payload_hash, QuantRawEvent.id)
            .where(
                QuantRawEvent.source == source,
                QuantRawEvent.payload_hash.in_(lijst[begin : begin + IN_CHUNK]),
                QuantRawEvent.duplicate_of_id.is_(None),
            )
            .order_by(QuantRawEvent.seq)
        )
        for stream, afdruk, rij_id in rijen.all():
            uit.setdefault((stream, afdruk), rij_id)
    return uit


async def verify_chain(session: AsyncSession) -> ChainCheck:
    """Rekent de hele ketting opnieuw na en zegt waar hij voor het eerst niet aansluit."""
    vorige: str | None = None
    aantal = 0
    rijen = await session.stream_scalars(
        select(QuantRawEvent).order_by(QuantRawEvent.seq)
    )
    async for rij in rijen:
        aantal += 1
        verwacht = chain_step(vorige, canonical_hash(rij.payload_raw))
        if verwacht != rij.chain_hash:
            return ChainCheck(
                ok=False,
                events=aantal,
                digest=None,
                first_bad_seq=rij.seq,
                explanation=(
                    f"De ketting sluit niet aan bij event {rij.seq}. De tekst van dit "
                    "event is veranderd nadat het was opgeslagen, of er is een event "
                    "tussenuit gehaald."
                ),
            )
        vorige = rij.chain_hash

    return ChainCheck(
        ok=True,
        events=aantal,
        digest=vorige,
        first_bad_seq=None,
        explanation=(
            f"De ketting sluit aan over alle {aantal} events."
            if aantal
            else "Er is nog geen data opgenomen."
        ),
    )


def _tick_rij(tick: MarketTick, *, raw_event_id: int, received_at: datetime) -> QuantMarketTick:
    rij = tick.as_row()
    kind = rij.pop("kind")
    return QuantMarketTick(
        raw_event_id=raw_event_id, kind=kind, received_at=received_at, **rij
    )


async def _normaliseer_rij(
    session: AsyncSession, rij: QuantRawEvent, normalizer: Normalizer
) -> tuple[int, int]:
    """Zet één ruw event om. Geeft (ticks, mislukt) terug.

    Een onleesbaar event wordt geteld en verder met rust gelaten. Nooit repareren: een
    gerepareerd event is een verzonnen event, en dat is erger dan een gat dat je kunt zien.
    """
    try:
        ticks = normalizer.normalize(
            RawEvent(
                source=rij.source,
                stream=rij.stream,
                payload_raw=rij.payload_raw,
                received_at=rij.received_at,
            )
        )
    except Exception as fout:  # noqa: BLE001 - elke onleesbare vorm telt hetzelfde
        logger.info("Event %s is niet te normaliseren: %s", rij.seq, fout)
        return 0, 1

    for tick in ticks:
        session.add(_tick_rij(tick, raw_event_id=rij.id, received_at=rij.received_at))
    return len(ticks), 0


async def normalize_pending(session: AsyncSession) -> tuple[int, int]:
    """Normaliseer alles wat nog geen tick heeft. Geeft (ticks, mislukt) terug."""
    # Alles vanaf het hoogste ruwe event dat al een tick heeft. Dat werkt omdat er altijd
    # in volgorde wordt genormaliseerd. De NOT IN-subquery die hier eerst stond, las bij
    # elke batch de hele tickstabel opnieuw.
    gedaan_tot = await session.scalar(select(func.max(QuantMarketTick.raw_event_id)))
    query = select(QuantRawEvent).order_by(QuantRawEvent.seq)
    if gedaan_tot is not None:
        query = query.where(QuantRawEvent.id > gedaan_tot)
    rijen = (await session.execute(query)).scalars().all()
    ticks = mislukt = 0
    for rij in rijen:
        gemaakt, fout = await _normaliseer_rij(session, rij, normalizer_for(rij.source))
        ticks += gemaakt
        mislukt += fout
    await session.flush()
    return ticks, mislukt


async def record(
    session: AsyncSession, *, source: FeedSource, note: str | None = None
) -> IngestResult:
    """Lees een bron helemaal uit, sla alles op en normaliseer het.

    Dit is de eenvoudige vorm, voor een opname van een vast stuk (een bestand, of de
    synthetische bron). De Scout gebruikt een lus met batches en een hartslag; zie
    `app/quantlab/scout.py`.

    Ook deze vorm boekt een run. Dat is niet voor de netheid: het aantal onleesbare events
    staat nergens anders, want een event dat niet te lezen was, laat geen tick achter en
    de ruwe rij wordt niet aangepast. Zonder run zou "hoeveel ging er mis" een vraag zijn
    zonder antwoord.
    """
    gestart = datetime.now(timezone.utc)
    # `note` is de herkomst: bij een bestand van buiten de naam en de SHA-256 ervan. Zonder
    # dat is "we hebben dit gemeten op dit bestand" niet meer na te gaan, en een aanbieder
    # die een archiefbestand later vervangt (Binance doet dat) blijft dan onzichtbaar.
    run = QuantIngestRun(source=source.name, started_at=gestart, note=note)
    session.add(run)
    await session.flush()

    aantal = ticks = mislukt = 0
    bytes_totaal = 0
    batch: list[RawEvent] = []

    async def wegschrijven() -> None:
        nonlocal batch, bytes_totaal, ticks, mislukt
        if not batch:
            return
        bytes_totaal += await store_events(session, batch, ingest_run_id=run.id)
        nieuwe, fout = await normalize_pending(session)
        ticks += nieuwe
        mislukt += fout
        batch = []

    async for event in source.events():
        batch.append(event)
        aantal += 1
        if len(batch) >= RECORD_BATCH:
            await wegschrijven()
    await wegschrijven()

    dubbel = int(
        await session.scalar(
            select(func.count())
            .select_from(QuantRawEvent)
            .where(
                QuantRawEvent.ingest_run_id == run.id,
                QuantRawEvent.duplicate_of_id.is_not(None),
            )
        )
        or 0
    )

    run.events = aantal
    run.ticks = ticks
    run.duplicates = dubbel
    run.parse_failures = mislukt
    run.bytes_stored = bytes_totaal
    run.stopped_at = datetime.now(timezone.utc)
    run.stop_reason = "source_exhausted"
    await session.flush()

    return IngestResult(
        events=aantal,
        ticks=ticks,
        duplicates=dubbel,
        parse_failures=mislukt,
        bytes_stored=bytes_totaal,
    )


async def normalized_digest(
    session: AsyncSession, *, since: datetime | None = None, until: datetime | None = None
) -> str:
    """Eén afdruk over alle ticks, in een vaste volgorde.

    De volgorde is expliciet (pool, tijd, id) en niet "zoals de database hem teruggeeft".
    Zonder die vaste volgorde zou dezelfde data na een herbouw een andere afdruk geven,
    puur omdat de rijen in een andere orde uit de tabel komen.
    """
    query = select(QuantMarketTick).order_by(
        QuantMarketTick.pool_address, QuantMarketTick.observed_at, QuantMarketTick.id
    )
    if since is not None:
        query = query.where(QuantMarketTick.observed_at >= since)
    if until is not None:
        query = query.where(QuantMarketTick.observed_at < until)
    rijen = (await session.execute(query)).scalars().all()
    return tick_digest(
        [
            {
                "kind": rij.kind,
                "venue": rij.venue,
                "chain": rij.chain,
                "pool_address": rij.pool_address,
                "token_address": rij.token_address,
                "observed_at": rij.observed_at,
                "price_usd": rij.price_usd,
                "liquidity_usd": rij.liquidity_usd,
                "volume_usd": rij.volume_usd,
                "volume_window_seconds": rij.volume_window_seconds,
                "pool_created_at": rij.pool_created_at,
            }
            for rij in rijen
        ]
    )


async def replay(
    session: AsyncSession,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> ReplayResult:
    """Bouw het genormaliseerde deel opnieuw op uit de ruwe opslag.

    Eerst de ketting narekenen. Replayen van data waarvan je niet weet of hij nog klopt,
    levert een getal op waar je niets aan hebt — dus bij een gebroken ketting stopt dit
    met `CorpusBroken` in plaats van met een uitkomst.

    De ruwe tabel wordt niet aangeraakt. Wat weg gaat en opnieuw komt, is uitsluitend
    `quant_market_ticks` voor het gevraagde venster.
    """
    controle = await verify_chain(session)
    if not controle.ok:
        raise CorpusBroken(controle.explanation)

    query = select(QuantRawEvent).order_by(QuantRawEvent.seq)
    if since is not None:
        query = query.where(QuantRawEvent.received_at >= since)
    if until is not None:
        query = query.where(QuantRawEvent.received_at < until)
    rijen = (await session.execute(query)).scalars().all()

    ids = [rij.id for rij in rijen]
    if ids:
        await session.execute(
            delete(QuantMarketTick).where(QuantMarketTick.raw_event_id.in_(ids))
        )

    ticks = mislukt = 0
    for rij in rijen:
        gemaakt, fout = await _normaliseer_rij(session, rij, normalizer_for(rij.source))
        ticks += gemaakt
        mislukt += fout
    await session.flush()

    return ReplayResult(
        events=len(rijen),
        ticks=ticks,
        parse_failures=mislukt,
        digest=await normalized_digest(session, since=since, until=until),
        since=since,
        until=until,
    )


async def quality(
    session: AsyncSession, *, now: datetime | None = None
) -> DataQualityReport:
    """Het datakwaliteitsrapport over alles wat is opgenomen."""
    nu = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rijen = (
        (
            await session.execute(
                # Aankomstvolgorde (`id`), niet chronologisch: de controle op volgorde
                # kijkt juist of een event een tijdstip had dat vóór zijn voorganger lag,
                # en die bevinding verdwijnt als je hier al sorteert op de klok.
                select(QuantMarketTick).order_by(
                    QuantMarketTick.pool_address, QuantMarketTick.id
                )
            )
        )
        .scalars()
        .all()
    )
    ticks: list[dict[str, Any]] = [
        {
            "pool_address": rij.pool_address,
            "observed_at": rij.observed_at,
            "received_at": rij.received_at,
            "price_usd": rij.price_usd,
        }
        for rij in rijen
    ]
    rauw = int(
        await session.scalar(select(func.count()).select_from(QuantRawEvent)) or 0
    )
    dubbel = int(
        await session.scalar(
            select(func.count())
            .select_from(QuantRawEvent)
            .where(QuantRawEvent.duplicate_of_id.is_not(None))
        )
        or 0
    )
    synthetisch = int(
        await session.scalar(
            select(func.count())
            .select_from(QuantRawEvent)
            .where(QuantRawEvent.source == "synthetic")
        )
        or 0
    )
    # Onleesbare events zijn de ruwe events waar geen tick bij staat én die ook geen
    # geldige "niets te normaliseren"-vorm hebben. Het aantal komt uit de runs, want daar
    # is het bij het opnemen geteld; dat is goedkoper dan alles opnieuw parsen.
    mislukt = int(
        await session.scalar(select(func.coalesce(func.sum(QuantIngestRun.parse_failures), 0)))
        or 0
    )
    return quality_report(
        ticks=ticks,
        raw_count=rauw,
        duplicates=dubbel,
        parse_failures=mislukt,
        synthetic_events=synthetisch,
        now=nu,
    )


async def storage_report(
    session: AsyncSession, *, now: datetime | None = None
) -> StorageReport:
    """Hoeveel er staat, en hoeveel het per dag wordt.

    De projectie is een meting en geen schatting: het aantal bytes gedeeld door de tijd die
    werkelijk is opgenomen. Is er minder dan een minuut opgenomen, dan staat er geen
    projectie — dan zegt het getal niets.
    """
    nu = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    events = int(
        await session.scalar(select(func.count()).select_from(QuantRawEvent)) or 0
    )
    ticks = int(
        await session.scalar(select(func.count()).select_from(QuantMarketTick)) or 0
    )
    bytes_totaal = int(
        await session.scalar(
            select(func.coalesce(func.sum(func.length(QuantRawEvent.payload_raw)), 0))
        )
        or 0
    )
    eerste = await session.scalar(select(func.min(QuantRawEvent.received_at)))
    laatste = await session.scalar(select(func.max(QuantRawEvent.received_at)))
    if eerste is not None and eerste.tzinfo is None:
        eerste = eerste.replace(tzinfo=timezone.utc)
    if laatste is not None and laatste.tzinfo is None:
        laatste = laatste.replace(tzinfo=timezone.utc)

    seconden = (laatste - eerste).total_seconds() if eerste and laatste else 0.0
    per_dag = int(bytes_totaal / seconden * 86_400) if seconden >= 60 else 0
    uitleg = (
        f"{events} events, {_leesbaar(bytes_totaal)} aan ruwe tekst. "
        + (
            f"Over {seconden / 3600:.1f} uur gemeten, dus ongeveer "
            f"{_leesbaar(per_dag)} per dag en {_leesbaar(per_dag * 30)} per maand."
            if per_dag
            else "Er is te weinig tijd opgenomen om iets over de groei te zeggen."
        )
    )
    return StorageReport(
        events=events,
        ticks=ticks,
        bytes_stored=bytes_totaal,
        bytes_per_event=int(bytes_totaal / events) if events else 0,
        measured_seconds=seconden,
        first_received_at=eerste,
        last_received_at=laatste,
        projected_bytes_per_day=per_dag,
        projected_bytes_per_month=per_dag * 30,
        explanation=uitleg,
    )


def _leesbaar(bytes_aantal: int) -> str:
    """Bytes in een eenheid die een mens leest. KiB en niet kB, want er wordt door 1024
    gedeeld — anders staat er een getal dat 2,4% naast de werkelijkheid zit."""
    waarde = Decimal(bytes_aantal)
    for eenheid in ("B", "KiB", "MiB", "GiB", "TiB"):
        if waarde < 1024 or eenheid == "TiB":
            return f"{waarde.quantize(Decimal('0.1'))} {eenheid}"
        waarde /= 1024
    return f"{bytes_aantal} B"


async def prune_raw_events(session: AsyncSession, *, older_than: datetime | None) -> int:
    """Ruim ruwe events op die ouder zijn dan `older_than`.

    Met opzet zonder standaardwaarde en zonder achtergrondtaak die dit zelf doet: een
    replay-corpus dat zichzelf opruimt, is een corpus dat je niet kunt replayen. Wie dit
    aanroept, kiest bewust dat dat stuk geschiedenis weg mag.
    """
    if older_than is None:
        raise ValueError(
            "Opruimen vraagt een expliciete grens: zonder datum zou dit het hele "
            "replay-corpus weggooien."
        )
    aantal = int(
        await session.scalar(
            select(func.count())
            .select_from(QuantRawEvent)
            .where(QuantRawEvent.received_at < older_than)
        )
        or 0
    )
    if not aantal:
        return 0
    # Een subquery en geen lijst met ids: bij een maand data zijn dat miljoenen parameters,
    # en PostgreSQL staat er 32767 toe. De ticks hangen met ON DELETE CASCADE aan de ruwe
    # rijen, maar SQLite doet dat alleen met foreign keys aan; expliciet weghalen werkt op
    # beide databases hetzelfde.
    oud = select(QuantRawEvent.id).where(QuantRawEvent.received_at < older_than)
    await session.execute(
        delete(QuantMarketTick).where(QuantMarketTick.raw_event_id.in_(oud))
    )
    await session.execute(
        delete(QuantRawEvent).where(QuantRawEvent.received_at < older_than)
    )
    await session.flush()
    return aantal


async def recent_runs(
    session: AsyncSession, *, limit: int = 20
) -> Sequence[QuantIngestRun]:
    rijen = await session.execute(
        select(QuantIngestRun).order_by(QuantIngestRun.id.desc()).limit(limit)
    )
    return list(rijen.scalars().all())
