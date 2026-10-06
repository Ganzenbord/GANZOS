"""De tabellen van het Quant Lab.

Vijf tabellen, en ze horen bij elkaar in twee groepen:

- **risico** — `quant_risk_bookings` (wat een gesloten papieren trade opleverde in R),
  `quant_risk_events` (elke beslissing van de Risk Officer, ook de geweigerde),
  `quant_risk_controls` (de noodstop en de handmatige resets) en `quant_heartbeats`
  (de dead-man switch);
- **kosten** — `quant_llm_calls`, het kostenboek: elke aanroep van een model met tokens,
  dollars, euro's en de koers waarmee is gerekend.

Fase 2 en 3 hebben er zeven bij gezet, in twee groepen:

- **data** — `quant_raw_events` (de ruwe feed, append-only, met een hashketting),
  `quant_market_ticks` (dezelfde events genormaliseerd, volledig herbouwbaar uit de ruwe
  tabel) en `quant_ingest_runs` (wat de Scout wanneer heeft opgenomen).

Twee dingen die afwijken van de rest van Ganz, en waarom:

1. **Geen `user_id`.** Dit is één lab, niet een lab per gebruiker. De equity, de risicolaag
   en het budget zijn van het lab als geheel; wie er naar mag kijken regelt het
   rechtenregister. Alleen bij `quant_risk_controls` staat wél een gebruiker: daar gaat het
   erom wie op de knop heeft gedrukt.
2. **Alleen `created_at`, geen `updated_at`.** Deze rijen worden nooit gewijzigd. Een
   logboek dat je kunt bijwerken is geen logboek, en bij risico en geld is "wat stond er
   gisteren" de belangrijkste vraag die je kunt stellen. `quant_heartbeats` is de enige
   uitzondering: daar is juist alleen de laatste stand interessant.

Er wordt in dit lab niet live gehandeld. Elke rij hieronder gaat over papier.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, NullableJSON, TimestampMixin, UtcDateTime, utcnow

# R-veelvouden met vier decimalen: genoeg om een halve R nauwkeurig op te tellen zonder
# dat afrondingsfouten de dagstand verschuiven.
R_MULTIPLE = Numeric(12, 4)
# Geld in het kostenboek met zes decimalen. Centen zouden niet werken: één aanroep van de
# Classifier kost een fractie van een cent, en duizend daarvan is geen nul euro.
COST = Numeric(14, 6)


class QuantControl(StrEnum):
    """Welke rem het is."""

    KILL_SWITCH = "kill_switch"
    WEEK_STOP = "week_stop"


class QuantControlAction(StrEnum):
    ENGAGE = "engage"
    RELEASE = "release"


class QuantControlSource(StrEnum):
    USER = "user"
    AUTO = "auto"
    HEARTBEAT = "heartbeat"


class QuantRiskBooking(Base, TimestampMixin):
    """Wat een gesloten papieren trade opleverde, in R.

    De dagstand en de weekstand worden hieruit opgeteld en nergens bewaard. Een opgetelde
    stand die ook ergens los staat, loopt vroeg of laat uiteen — en dan weet je niet meer
    welke van de twee de waarheid is.
    """

    __tablename__ = "quant_risk_bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hypothesis: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    r_multiple: Mapped[Decimal] = mapped_column(R_MULTIPLE, nullable=False)
    closed_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True, nullable=False)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class QuantRiskEvent(Base):
    """Elke beslissing van de Risk Officer, ook — vooral — de geweigerde.

    Bewijs boven verhaal: zonder deze rijen kun je achteraf niet laten zien dát een grens
    heeft gewerkt, alleen dat er geen trade was.
    """

    __tablename__ = "quant_risk_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hypothesis: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    veto: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    reason: Mapped[str] = mapped_column(String(300), nullable=False, default="")

    equity: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    risk_eur: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    position_units: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    open_risk_r: Mapped[Decimal] = mapped_column(R_MULTIPLE, nullable=False)
    realized_day_r: Mapped[Decimal] = mapped_column(R_MULTIPLE, nullable=False)
    realized_week_r: Mapped[Decimal] = mapped_column(R_MULTIPLE, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, server_default=func.now(), index=True, nullable=False
    )


class QuantRiskControl(Base):
    """De noodstop en de handmatige resets, als logboek.

    De huidige stand is de laatste rij per rem. Dat is met opzet geen kolom die je
    overschrijft: nu kun je zien hoe vaak de noodstop aan heeft gestaan en waarom, en dat
    is precies wat je na een slechte week wil nalezen.
    """

    __tablename__ = "quant_risk_controls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    control: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # Bij een weekreset staat hier de stand waarop is gereset, zodat de nieuwe grens
    # narekenbaar is in plaats van een getal dat ergens vandaan komt.
    detail: Mapped[dict[str, Any] | None] = mapped_column(NullableJSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, server_default=func.now(), index=True, nullable=False
    )


class QuantHeartbeat(Base):
    """De dead-man switch: één rij per onderdeel, met wanneer het voor het laatst leefde."""

    __tablename__ = "quant_heartbeats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class QuantLlmCall(Base):
    """Het kostenboek: één rij per aanroep van een taalmodel of classifier.

    De koers staat erbij omdat een bedrag in euro's zonder de koers niet na te rekenen is.
    En de tokens staan erbij omdat een bedrag zonder tokens niet te verklaren is: "waarom
    werd dit duurder" is altijd een vraag over context, niet over de prijs.
    """

    __tablename__ = "quant_llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    model: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(COST, nullable=False)
    cost_eur: Mapped[Decimal] = mapped_column(COST, nullable=False)
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    purpose: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, server_default=func.now(), index=True, nullable=False
    )


# --- De datalaag (fase 2) ----------------------------------------------------

# Prijzen met twaalf decimalen: een memecoin kost soms 0,000000123456 dollar, en afronden
# op centen zou elke beweging wegpoetsen.
PRICE = Numeric(30, 12)


class QuantRawEvent(Base):
    """De feed zoals hij binnenkwam. Append-only, nooit gewijzigd, nooit herschreven.

    `payload_raw` is de tekst en niet een geparste structuur. Dat is het verschil tussen
    "herhaalbaar" en "bit-voor-bit herhaalbaar": twee JSON-documenten met dezelfde
    betekenis kunnen andere bytes zijn, en een feed die morgen zijn sleutelvolgorde
    wijzigt, zou anders stil een ander corpus opleveren.

    `chain_hash` hangt elke rij aan de vorige. Verandert er één byte in een oude rij, dan
    sluit alles erna niet meer aan en zegt `verify_chain()` precies waar het misgaat.

    Een dubbel event wordt wél opgeslagen (de tabel is append-only) en alleen gemarkeerd
    met `duplicate_of_id`. Weggooien zou betekenen dat de ruwe opslag niet meer ruw is.
    """

    __tablename__ = "quant_raw_events"
    __table_args__ = (
        Index("ix_quant_raw_events_stream_hash", "source", "stream", "payload_hash"),
        Index("ix_quant_raw_events_source_received", "source", "received_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Een eigen teller naast `id`, zodat de volgorde van de ketting expliciet is en niet
    # afhangt van hoe de database zijn primaire sleutel uitdeelt.
    seq: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    stream: Mapped[str] = mapped_column(String(40), nullable=False)
    payload_raw: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chain_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True, nullable=False)
    duplicate_of_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ingest_run_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)


class QuantMarketTick(Base):
    """De genormaliseerde vorm van een ruw event: dit is waar de Screener naar kijkt.

    Volledig afgeleid en dus volledig weggooibaar. Dat is met opzet: de enige manier om te
    bewijzen dat een replay hetzelfde resultaat geeft, is deze tabel weggooien, opnieuw
    opbouwen uit de ruwe tabel en de afdruk vergelijken.
    """

    __tablename__ = "quant_market_ticks"
    __table_args__ = (
        Index("ix_quant_market_ticks_pool_observed", "pool_address", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_event_id: Mapped[int] = mapped_column(
        ForeignKey("quant_raw_events.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    venue: Mapped[str] = mapped_column(String(40), nullable=False)
    chain: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    pool_address: Mapped[str] = mapped_column(String(80), nullable=False)
    token_address: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    observed_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True, nullable=False)
    received_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    price_usd: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    liquidity_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    volume_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    volume_window_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pool_created_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class QuantIngestRun(Base):
    """Wat de Scout wanneer heeft opgenomen.

    Zonder deze rijen is "hoeveel data hebben we en van wanneer" een vraag die je niet kunt
    beantwoorden, en "hoeveel groeit de schijf per dag" een schatting in plaats van een
    meting. `stop_reason` staat erbij omdat een run die stilletjes ophoudt een gat in het
    corpus achterlaat dat je nooit meer kunt vullen.
    """

    __tablename__ = "quant_ingest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True, nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ticks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parse_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bytes_stored: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


# --- De papieren handel (fase 3) ---------------------------------------------


class QuantHypothesis(Base):
    """Een hypothese, vastgelegd en gehasht vóór de eerste run (sectie 8).

    De brontekst staat er volledig in, niet alleen de hash. Een hash zonder de tekst zegt
    alleen dát er iets veranderd is; met de tekst kun je over een half jaar nalezen waarom
    een waarde zo stond. Het commentaar in het bestand hoort daar expliciet bij.

    Wijzigen betekent een nieuwe versie: `(name, version)` is uniek, en een registratie met
    dezelfde versie maar andere inhoud wordt geweigerd.
    """

    __tablename__ = "quant_hypotheses"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_quant_hypothesis_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    paper_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    source_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, server_default=func.now(), nullable=False
    )


class QuantStrategyRun(Base):
    """Eén run van één hypothese in één stressvariant.

    `corpus_digest` is de afdruk van de ruwe opslag op het moment van de run. Daarmee hangt
    een resultaat aan een exact corpus: zonder dat is "expectancy 0,3R" een getal zonder
    vraag waar het over ging.
    """

    __tablename__ = "quant_strategy_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hypothesis_id: Mapped[int] = mapped_column(
        ForeignKey("quant_hypotheses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    variant: Mapped[str] = mapped_column(String(20), nullable=False, default="base")
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    corpus_digest: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    ticks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    signals_proposed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trades_opened: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trades_closed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Posities die aan het eind van het corpus nog openstonden en op de laatst bekende
    # prijs zijn gesloten. Geen uitstap volgens een regel, dus apart geteld: anders zou
    # je ze voor echte exits aanzien.
    trades_force_closed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    equity_quote: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    one_r_quote: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    usd_eur_rate: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    realized_r: Mapped[Decimal] = mapped_column(R_MULTIPLE, nullable=False, default=0)
    max_drawdown_r: Mapped[Decimal] = mapped_column(R_MULTIPLE, nullable=False, default=0)
    max_open_risk_r: Mapped[Decimal] = mapped_column(R_MULTIPLE, nullable=False, default=0)
    total_fees_usd: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    total_slippage_usd: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    safety_oracle: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    skipped_by_reason: Mapped[dict[str, Any] | None] = mapped_column(
        NullableJSON, nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)


class QuantSignal(Base):
    """Elk signaal, genomen én overgeslagen, met de reden erbij.

    Sectie 10 vraagt dit expliciet: zonder de overgeslagen signalen kun je achteraf elke
    uitkomst mooi praten door te vergeten wat je hebt laten lopen. En je kunt niet meten of
    een filter geld heeft bespaard of kansen heeft gekost.
    """

    __tablename__ = "quant_signals"
    __table_args__ = (Index("ix_quant_signals_run_taken", "run_id", "taken"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("quant_strategy_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    pool_address: Mapped[str] = mapped_column(String(80), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    price_usd: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    taken: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(300), nullable=True)


class QuantPaperTrade(Base):
    """Eén papieren positie, van instap tot sluiting.

    Er wordt in dit project niet live gehandeld: elke rij hier is een simulatie.
    """

    __tablename__ = "quant_paper_trades"
    __table_args__ = (Index("ix_quant_paper_trades_run_pool", "run_id", "pool_address"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("quant_strategy_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    pool_address: Mapped[str] = mapped_column(String(80), nullable=False)
    token_address: Mapped[str] = mapped_column(String(80), nullable=False, default="")

    opened_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    entry_reason: Mapped[str] = mapped_column(String(60), nullable=False)
    exit_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # Waar de stop van deze trade vandaan kwam. Dat staat per trade in de tabel en niet
    # alleen in de hypothese, omdat de stop per trade anders is: hij volgt uit wat dit
    # token zelf deed. Zonder deze drie kolommen kun je achteraf niet nagaan waarom een
    # positie zo groot was.
    stop_basis: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    stop_distance_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=0
    )
    stop_clamped: Mapped[str | None] = mapped_column(String(10), nullable=True)

    risk_r: Mapped[Decimal] = mapped_column(R_MULTIPLE, nullable=False)
    risk_quote: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    units: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    entry_expected_price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    entry_fill_price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    stop_price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    exit_quote_usd: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    fees_usd: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    slippage_usd: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    latency_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    pnl_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    r_multiple: Mapped[Decimal | None] = mapped_column(R_MULTIPLE, nullable=True)


class QuantPaperFill(Base):
    """Eén order binnen een trade: verwacht, gesimuleerd, en wat ertussen zat.

    De vier prijzen staan er allemaal, want "de fill was slechter" is een nutteloze
    mededeling als je niet weet of dat door de klok, de pooldiepte of de fee kwam.
    """

    __tablename__ = "quant_paper_fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(
        ForeignKey("quant_paper_trades.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    requested_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    filled_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    filled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)

    expected_price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    market_price: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    fill_price: Mapped[Decimal] = mapped_column(PRICE, nullable=False, default=0)
    units: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False, default=0)
    quote_usd: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    slippage_usd: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    latency_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    fee_usd: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    exit_haircut_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


# --- De agents (fase 4) ------------------------------------------------------


class QuantDecisionLog(Base):
    """Elke beslissing van een beslismodel, inclusief die van een model in de schaduw.

    Een model dat in de schaduw loopt, bepaalt niets (`used=False`) maar wordt wel
    vastgelegd. Zonder deze rijen kun je de vraag "was het beter geweest" achteraf niet
    beantwoorden, en dan blijft het bij een claim van de leverancier.

    `outcome` is pas later bekend — als de trade is gesloten. Daarom staat hij apart en mag
    hij NULL zijn: een lege uitkomst betekent "weten we nog niet", niet "nee".
    """

    __tablename__ = "quant_decision_log"
    __table_args__ = (
        Index("ix_quant_decision_log_model_shadow", "model_name", "shadow"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hypothesis: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    pool_address: Mapped[str] = mapped_column(String(80), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, nullable=False)
    shadow: Mapped[bool] = mapped_column(Boolean, nullable=False)
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    outcome: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, server_default=func.now(), index=True, nullable=False
    )


class QuantProposal(Base):
    """De inbox van de Reviewer (sectie 6).

    De Reviewer mag nooit config of een hypothese wijzigen. Zijn voorstellen komen hier
    terecht en blijven hier tot Stef ze goedkeurt of afwijst. Goedkeuren verandert niets
    rechtstreeks: het levert een nieuwe hypothese-versie op, en dan begint de trade-teller
    opnieuw.

    Een afgewezen voorstel blijft staan. Weggooien zou betekenen dat je niet meer kunt zien
    wat je hebt afgewezen en waarom — en dat is precies wat je een half jaar later wil
    nalezen.
    """

    __tablename__ = "quant_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    argument: Mapped[str] = mapped_column(Text, nullable=False)
    changes_nl: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Welke hypothese-versie eruit is gekomen, als het voorstel is goedgekeurd.
    applied_hypothesis_id: Mapped[int | None] = mapped_column(
        ForeignKey("quant_hypotheses.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, server_default=func.now(), index=True, nullable=False
    )
