"""De papieren handel met de database eronder (secties 8 en 10).

Drie dingen: hypotheses registreren, een run uitvoeren en wegschrijven, en de stresstest in
vier varianten draaien.

De pre-registratie is de strengste regel hier: dezelfde `(naam, versie)` met andere inhoud
wordt geweigerd. Dat is geen pesterij maar het enige dat voorkomt dat er achteraf aan de
regels wordt gedraaid tot de curve bevalt.

Er wordt in dit project niet live gehandeld. Elke rij die hier ontstaat is een simulatie.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.quantlab import (
    QuantHypothesis,
    QuantMarketTick,
    QuantPaperFill,
    QuantPaperTrade,
    QuantSignal,
    QuantStrategyRun,
)
from app.quantlab.engine import EngineResult, run_engine
from app.quantlab.fills import STRESS_PROFILES
from app.quantlab.hypothesis import HypothesisFile, PreRegistrationError
from app.quantlab.metrics import ExpectancyResult, expectancy
from app.quantlab.safety import SafetyOracle
from app.quantlab.strategy import Candidate, RandomEntryStrategy
from app.services import quant_data_service

logger = logging.getLogger("ganz.quantlab.paper")


async def register_hypothesis(
    session: AsyncSession, hypothesis: HypothesisFile
) -> QuantHypothesis:
    """Leg een hypothese vast, of geef de bestaande terug als hij ongewijzigd is.

    Is hij gewijzigd onder dezelfde versie, dan is dit een fout en geen update. Zo blijft
    elke run te herleiden tot precies de regels waaronder hij draaide.
    """
    bestaand = await session.scalar(
        select(QuantHypothesis).where(
            QuantHypothesis.name == hypothesis.name,
            QuantHypothesis.version == hypothesis.version,
        )
    )
    if bestaand is not None:
        if bestaand.content_hash != hypothesis.content_hash:
            raise PreRegistrationError(
                f"{hypothesis.label} is al geregistreerd met een andere inhoud. Een "
                "hypothese wijzigen betekent een nieuwe versie (bijvoorbeeld "
                f"{hypothesis.name}_v2); dan begint de trade-teller opnieuw. Dat is met "
                "opzet: anders is achteraf niet te zeggen onder welke regels de oude "
                "trades zijn gemeten."
            )
        return bestaand

    rij = QuantHypothesis(
        name=hypothesis.name,
        version=hypothesis.version,
        content_hash=hypothesis.content_hash,
        statement=hypothesis.statement,
        paper_only=hypothesis.paper_only,
        source_yaml=hypothesis.source_yaml,
        source_path=hypothesis.path,
    )
    session.add(rij)
    await session.flush()
    return rij


async def load_ticks(
    session: AsyncSession,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[Candidate]:
    """Het corpus als kandidaten, op tijd gesorteerd.

    Alles in één keer in het geheugen. Bij een uur is dat een paar duizend rijen; bij een
    maand draaien moet dit in stukken, en dan hoort hier een generator te staan die per dag
    leest. Zie het fase 3-rapport.
    """
    query = select(QuantMarketTick).order_by(
        QuantMarketTick.observed_at, QuantMarketTick.id
    )
    if since is not None:
        query = query.where(QuantMarketTick.observed_at >= since)
    if until is not None:
        query = query.where(QuantMarketTick.observed_at < until)
    rijen = (await session.execute(query)).scalars().all()
    return [
        Candidate(
            pool_address=rij.pool_address,
            token_address=rij.token_address,
            venue=rij.venue,
            chain=rij.chain,
            observed_at=rij.observed_at,
            price_usd=rij.price_usd,
            liquidity_usd=rij.liquidity_usd,
            volume_usd=rij.volume_usd,
            pool_created_at=rij.pool_created_at,
        )
        for rij in rijen
    ]


async def run_hypothesis(
    session: AsyncSession,
    *,
    hypothesis: HypothesisFile,
    seed: int,
    safety: SafetyOracle,
    variant: str = "base",
    since: datetime | None = None,
    until: datetime | None = None,
    equity_usd: Decimal | None = None,
    attempts_per_hour_override: float | None = None,
    ticks: Sequence[Candidate] | None = None,
) -> EngineResult:
    """Draai één hypothese één keer en schrijf alles weg."""
    instellingen = get_settings()
    # De papieren rekening staat in dollars, net als de venues. Er wordt in het hele
    # handelspad niets omgerekend: elke omrekening is een plek waar een koers de verkeerde
    # kant op kan gaan, en dat is één keer gebeurd. De koers hieronder gaat alleen mee in
    # de run als context, want het kostenboek van de modellen rekent wél in euro's.
    equity_quote = (
        equity_usd if equity_usd is not None else instellingen.quant_paper_equity_usd
    ).quantize(Decimal("0.01"))
    koers = instellingen.quant_usd_eur_rate

    hypothese = await register_hypothesis(session, hypothesis)
    corpus = list(ticks) if ticks is not None else await load_ticks(
        session, since=since, until=until
    )
    afdruk = (await quant_data_service.verify_chain(session)).digest or ""

    strategie = RandomEntryStrategy(
        seed=seed,
        attempts_per_hour=(
            attempts_per_hour_override
            if attempts_per_hour_override is not None
            else float(hypothesis.entry.get("attempts_per_hour", 6))
        ),
        min_age_minutes=float(hypothesis.entry.get("min_token_age_minutes", 0)),
        max_age_minutes=float(hypothesis.entry.get("max_token_age_minutes", 10**6)),
    )

    gestart = datetime.now(timezone.utc)
    uitslag = run_engine(
        hypothesis=hypothesis,
        strategy=strategie,
        ticks=corpus,
        fill_model=hypothesis.fill_model(STRESS_PROFILES[variant]),
        safety=safety,
        equity_quote=equity_quote,
        seed=seed,
        variant=variant,
    )

    run = QuantStrategyRun(
        hypothesis_id=hypothese.id,
        variant=variant,
        seed=seed,
        corpus_digest=afdruk,
        started_at=gestart,
        finished_at=datetime.now(timezone.utc),
        ticks=uitslag.ticks,
        signals_proposed=uitslag.signals_proposed,
        trades_opened=uitslag.trades_opened,
        trades_closed=uitslag.trades_closed,
        trades_force_closed=uitslag.trades_force_closed + uitslag.trades_closed_stale,
        equity_quote=equity_quote,
        one_r_quote=uitslag.one_r_quote,
        usd_eur_rate=koers,
        realized_r=uitslag.realized_r,
        max_drawdown_r=uitslag.max_drawdown_r,
        max_open_risk_r=uitslag.max_open_risk_r,
        total_fees_usd=uitslag.total_fees_usd,
        total_slippage_usd=uitslag.total_slippage_usd,
        safety_oracle=safety.name,
        skipped_by_reason=dict(uitslag.skipped_by_reason),
    )
    session.add(run)
    await session.flush()

    for signaal in uitslag.signals:
        session.add(
            QuantSignal(
                run_id=run.id,
                pool_address=signaal.pool_address,
                observed_at=signaal.observed_at,
                price_usd=signaal.price_usd,
                taken=signaal.taken,
                reason=signaal.reason,
                detail=signaal.detail or None,
            )
        )

    for trade in uitslag.trades:
        rij = QuantPaperTrade(
            run_id=run.id,
            pool_address=trade.pool_address,
            token_address=trade.token_address,
            opened_at=trade.opened_at,
            closed_at=trade.closed_at,
            entry_reason=trade.entry_reason[:60],
            exit_reason=trade.exit_reason,
            stop_basis=trade.stop_basis,
            stop_distance_pct=trade.stop_distance_pct,
            stop_clamped=trade.stop_clamped,
            risk_r=trade.risk_r,
            risk_quote=trade.risk_quote,
            units=trade.units,
            entry_expected_price=trade.entry_expected_price,
            entry_fill_price=trade.entry_fill_price,
            stop_price=trade.stop_price,
            exit_quote_usd=trade.exit_quote_usd,
            fees_usd=trade.fees_usd,
            slippage_usd=trade.slippage_usd,
            latency_cost_usd=trade.latency_cost_usd,
            pnl_usd=trade.pnl_usd,
            r_multiple=trade.r_multiple,
        )
        session.add(rij)
        await session.flush()
        for fill in trade.fills:
            uit = fill.outcome
            session.add(
                QuantPaperFill(
                    trade_id=rij.id,
                    sequence=fill.sequence,
                    kind=fill.kind,
                    reason=fill.reason,
                    requested_at=uit.requested_at,
                    filled_at=uit.filled_at,
                    latency_ms=uit.latency_ms,
                    filled=uit.filled,
                    failure_reason=uit.failure_reason,
                    expected_price=uit.expected_price,
                    market_price=uit.market_price,
                    fill_price=uit.fill_price,
                    units=uit.units,
                    quote_usd=uit.quote_usd,
                    slippage_usd=uit.slippage_usd,
                    latency_cost_usd=uit.latency_cost_usd,
                    fee_usd=uit.fee_usd,
                    exit_haircut_applied=uit.exit_haircut_applied,
                )
            )

    await session.flush()
    logger.info(
        "%s (%s): %s signalen, %s trades, %s gesloten, %sR",
        hypothesis.label,
        variant,
        uitslag.signals_proposed,
        uitslag.trades_opened,
        uitslag.trades_closed,
        uitslag.realized_r,
    )
    return uitslag


async def run_stress_suite(
    session: AsyncSession,
    *,
    hypothesis: HypothesisFile,
    seed: int,
    safety: SafetyOracle,
    **kwargs,
) -> dict[str, EngineResult]:
    """Alle vier de varianten over hetzelfde corpus (sectie 10).

    Hetzelfde zaad en hetzelfde corpus voor alle vier, zodat het enige verschil het
    fill-model is. Zouden de instappen ook verschillen, dan vergelijk je twee strategieën
    in plaats van twee werelden. Het corpus wordt één keer geladen, ook om die reden.
    """
    corpus = await load_ticks(
        session, since=kwargs.get("since"), until=kwargs.get("until")
    )
    uit: dict[str, EngineResult] = {}
    for naam in STRESS_PROFILES:
        uit[naam] = await run_hypothesis(
            session,
            hypothesis=hypothesis,
            seed=seed,
            safety=safety,
            variant=naam,
            ticks=corpus,
            **{k: v for k, v in kwargs.items() if k not in ("since", "until")},
        )
    return uit


async def run_expectancy(
    session: AsyncSession, *, run_id: int, seed: int = 1, min_trades: int | None = None
) -> ExpectancyResult:
    """De expectancy van één run, met N, kosten en onzekerheidsmarge."""
    from app.quantlab.metrics import TradeResult

    rijen = (
        (
            await session.execute(
                select(QuantPaperTrade).where(
                    QuantPaperTrade.run_id == run_id,
                    QuantPaperTrade.r_multiple.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return expectancy(
        [TradeResult(r_multiple=rij.r_multiple) for rij in rijen],
        seed=seed,
        **({"min_trades": min_trades} if min_trades is not None else {}),
    )


async def list_hypotheses(session: AsyncSession) -> Sequence[QuantHypothesis]:
    rijen = await session.execute(
        select(QuantHypothesis).order_by(QuantHypothesis.name, QuantHypothesis.version)
    )
    return list(rijen.scalars().all())


async def recent_runs(
    session: AsyncSession, *, limit: int = 20
) -> Sequence[QuantStrategyRun]:
    rijen = await session.execute(
        select(QuantStrategyRun).order_by(QuantStrategyRun.id.desc()).limit(limit)
    )
    return list(rijen.scalars().all())


async def recent_trades(
    session: AsyncSession, *, run_id: int | None = None, limit: int = 50
) -> Sequence[QuantPaperTrade]:
    query = select(QuantPaperTrade).order_by(QuantPaperTrade.id.desc()).limit(limit)
    if run_id is not None:
        query = query.where(QuantPaperTrade.run_id == run_id)
    return list((await session.execute(query)).scalars().all())


async def trade_fills(
    session: AsyncSession, *, trade_id: int
) -> Sequence[QuantPaperFill]:
    rijen = await session.execute(
        select(QuantPaperFill)
        .where(QuantPaperFill.trade_id == trade_id)
        .order_by(QuantPaperFill.sequence)
    )
    return list(rijen.scalars().all())


async def skipped_signals(
    session: AsyncSession, *, run_id: int, limit: int = 50
) -> Sequence[QuantSignal]:
    rijen = await session.execute(
        select(QuantSignal)
        .where(QuantSignal.run_id == run_id, QuantSignal.taken.is_(False))
        .order_by(QuantSignal.id.desc())
        .limit(limit)
    )
    return list(rijen.scalars().all())
