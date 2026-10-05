"""De tabellen van het Quant Lab.

Vijf tabellen, en ze horen bij elkaar in twee groepen:

- **risico** — `quant_risk_bookings` (wat een gesloten papieren trade opleverde in R),
  `quant_risk_events` (elke beslissing van de Risk Officer, ook de geweigerde),
  `quant_risk_controls` (de noodstop en de handmatige resets) en `quant_heartbeats`
  (de dead-man switch);
- **kosten** — `quant_llm_calls`, het kostenboek: elke aanroep van een model met tokens,
  dollars, euro's en de koers waarmee is gerekend.

Fase 2 heeft er drie bij gezet, en die horen bij elkaar in een derde groep:

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
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
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
