"""De Risk Officer met een database eronder.

De beslissing zelf staat in `app/quantlab/risk.py` en is pure code. Dit bestand doet de
twee dingen die een database nodig hebben: de stand van zaken opbouwen, en elke beslissing
vastleggen — ook de geweigerde.

De stand wordt elke keer opnieuw opgeteld uit de boekingen en nergens bewaard. Een stand
die ook ergens los staat, loopt vroeg of laat uiteen met de rijen waar hij uit komt, en
dan weet je bij een blokkade niet meer welke van de twee de waarheid was.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone  # noqa: F401
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.quantlab import (
    QuantControl,
    QuantControlAction,
    QuantControlSource,
    QuantHeartbeat,
    QuantRiskBooking,
    QuantRiskControl,
    QuantRiskEvent,
)
from app.quantlab.risk import (
    EntryRequest,
    RiskDecision,
    RiskSnapshot,
    day_start,
    evaluate_entry,
    week_start,
)
from app.quantlab.risk_limits import WEEK_LOSS_STOP_R


# `day_start` en `week_start` komen uit de pure risicolaag: de engine van fase 3 heeft ze
# ook nodig en mag de databaselaag niet importeren. Eén definitie, één waarheid.

async def _realized_r(session: AsyncSession, vanaf: datetime) -> Decimal:
    totaal = await session.scalar(
        select(func.coalesce(func.sum(QuantRiskBooking.r_multiple), 0)).where(
            QuantRiskBooking.closed_at >= vanaf
        )
    )
    return Decimal(str(totaal or 0))


async def _laatste_controle(
    session: AsyncSession, control: QuantControl
) -> QuantRiskControl | None:
    return await session.scalar(
        select(QuantRiskControl)
        .where(QuantRiskControl.control == control.value)
        .order_by(QuantRiskControl.id.desc())
        .limit(1)
    )


async def kill_switch_active(session: AsyncSession) -> bool:
    laatste = await _laatste_controle(session, QuantControl.KILL_SWITCH)
    return bool(laatste and laatste.action == QuantControlAction.ENGAGE.value)


async def week_stop_level(session: AsyncSession, *, now: datetime) -> Decimal:
    """Bij welke weekstand alles stilstaat.

    Standaard -8R. Na een handmatige reset schuift de grens 8R mee vanaf de stand waarop
    is gereset, zodat het verlies van deze week in de cijfers blijft staan en alleen de
    stop opnieuw is gezet. Een reset uit een vorige week telt niet meer mee: elke week
    begint weer op -8R.
    """
    laatste = await session.scalar(
        select(QuantRiskControl)
        .where(
            QuantRiskControl.control == QuantControl.WEEK_STOP.value,
            QuantRiskControl.action == QuantControlAction.RELEASE.value,
            QuantRiskControl.created_at >= week_start(now),
        )
        .order_by(QuantRiskControl.id.desc())
        .limit(1)
    )
    if laatste is None:
        return WEEK_LOSS_STOP_R
    stand_bij_reset = Decimal(str((laatste.detail or {}).get("week_r_at_reset", "0")))
    return stand_bij_reset + WEEK_LOSS_STOP_R


async def heartbeat_age_seconds(session: AsyncSession, *, now: datetime) -> float | None:
    """Hoe lang het stil is. `None` betekent: er is nog nooit een hartslag geweest.

    De jongste hartslag van álle onderdelen telt. Eén levend onderdeel is genoeg om te
    weten dat het lab draait; welk onderdeel precies stil is, hoort in de monitoring.
    """
    laatste = await session.scalar(select(func.max(QuantHeartbeat.last_seen_at)))
    if laatste is None:
        return None
    if laatste.tzinfo is None:
        laatste = laatste.replace(tzinfo=timezone.utc)
    return max(0.0, (now.astimezone(timezone.utc) - laatste).total_seconds())


async def snapshot(
    session: AsyncSession,
    *,
    equity: Decimal,
    open_risk_r: Decimal = Decimal("0"),
    now: datetime | None = None,
) -> RiskSnapshot:
    """De stand van zaken, opgeteld uit de database.

    `open_risk_r` komt van buiten omdat de open posities in een latere fase pas bestaan.
    Zolang dat zo is, is de waarde nul en blokkeert de grens van 5R dus nooit — dat staat
    zo in het fase 1-rapport, zodat niemand denkt dat die grens al iets doet.
    """
    nu = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return RiskSnapshot(
        equity=equity,
        open_risk_r=open_risk_r,
        realized_day_r=await _realized_r(session, day_start(nu)),
        realized_week_r=await _realized_r(session, week_start(nu)),
        kill_switch_active=await kill_switch_active(session),
        heartbeat_age_seconds=await heartbeat_age_seconds(session, now=nu),
        week_stop_level_r=await week_stop_level(session, now=nu),
    )


async def check_entry(
    session: AsyncSession,
    *,
    equity: Decimal,
    request: EntryRequest,
    open_risk_r: Decimal = Decimal("0"),
    now: datetime | None = None,
) -> RiskDecision:
    """De enige weg naar een papieren instap. Elke uitkomst komt in `quant_risk_events`.

    De aanroeper commit zelf, zodat er nooit een logregel staat voor iets dat is
    teruggedraaid — dezelfde afspraak als bij het activiteitenlog.
    """
    stand = await snapshot(session, equity=equity, open_risk_r=open_risk_r, now=now)
    besluit = evaluate_entry(stand, request)
    session.add(
        QuantRiskEvent(
            hypothesis=request.hypothesis,
            allowed=besluit.allowed,
            veto=besluit.veto.value if besluit.veto else None,
            reason=besluit.reason[:300],
            equity=stand.equity,
            risk_eur=besluit.risk_eur,
            position_units=besluit.position_units,
            open_risk_r=stand.open_risk_r,
            realized_day_r=stand.realized_day_r,
            realized_week_r=stand.realized_week_r,
        )
    )
    await session.flush()
    return besluit


async def engage_kill_switch(
    session: AsyncSession,
    *,
    reason: str,
    source: str | QuantControlSource = QuantControlSource.USER,
    user_id: int | None,
) -> QuantRiskControl:
    rij = QuantRiskControl(
        control=QuantControl.KILL_SWITCH.value,
        action=QuantControlAction.ENGAGE.value,
        source=str(source),
        reason=reason[:300],
        user_id=user_id,
    )
    session.add(rij)
    await session.flush()
    return rij


async def release_kill_switch(
    session: AsyncSession, *, reason: str, user_id: int | None
) -> QuantRiskControl:
    """De noodstop eruit halen. Altijd met een naam erbij: dit is de gevaarlijke richting."""
    rij = QuantRiskControl(
        control=QuantControl.KILL_SWITCH.value,
        action=QuantControlAction.RELEASE.value,
        source=QuantControlSource.USER.value,
        reason=reason[:300],
        user_id=user_id,
    )
    session.add(rij)
    await session.flush()
    return rij


async def reset_week_stop(
    session: AsyncSession,
    *,
    user_id: int | None,
    reason: str,
    now: datetime | None = None,
) -> QuantRiskControl:
    """De weekstop opnieuw zetten. Alleen met de hand, en de stand gaat mee in de rij.

    De teller gaat niet op nul: het verlies van deze week blijft staan in de cijfers. Wat
    verschuift is de grens, en wel met 8R vanaf de stand van dit moment — dus na een reset
    op -8R staat alles weer stil bij -16R.
    """
    nu = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stand = await _realized_r(session, week_start(nu))
    rij = QuantRiskControl(
        control=QuantControl.WEEK_STOP.value,
        action=QuantControlAction.RELEASE.value,
        source=QuantControlSource.USER.value,
        reason=reason[:300],
        user_id=user_id,
        detail={"week_r_at_reset": str(stand)},
    )
    session.add(rij)
    await session.flush()
    return rij


async def heartbeat(
    session: AsyncSession,
    *,
    component: str,
    now: datetime | None = None,
    note: str | None = None,
) -> QuantHeartbeat:
    """"Ik leef nog." Eén rij per onderdeel; alleen de laatste stand is interessant."""
    nu = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rij = await session.scalar(
        select(QuantHeartbeat).where(QuantHeartbeat.component == component)
    )
    if rij is None:
        rij = QuantHeartbeat(component=component, last_seen_at=nu, note=note)
        session.add(rij)
    else:
        rij.last_seen_at = nu
        if note is not None:
            rij.note = note
    await session.flush()
    return rij


async def recent_events(
    session: AsyncSession, *, limit: int = 20
) -> list[QuantRiskEvent]:
    rijen = await session.execute(
        select(QuantRiskEvent).order_by(QuantRiskEvent.id.desc()).limit(limit)
    )
    return list(rijen.scalars().all())


async def booking_day(session: AsyncSession, *, day: date) -> Decimal:
    """De R-stand van één UTC-dag. Voor het dagrapport."""
    begin = datetime.combine(day, time.min, tzinfo=timezone.utc)
    einde = begin + timedelta(days=1)
    totaal = await session.scalar(
        select(func.coalesce(func.sum(QuantRiskBooking.r_multiple), 0)).where(
            QuantRiskBooking.closed_at >= begin, QuantRiskBooking.closed_at < einde
        )
    )
    return Decimal(str(totaal or 0))
