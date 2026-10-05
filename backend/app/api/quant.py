"""De API van het Quant Lab.

In fase 1 is dat precies twee dingen: de risicostand met de noodstop, en het kostenboek
met de budgetstand. De rest van de module (hypotheses, kandidaten, papieren posities,
rapporten) komt in latere fases.

Let op de richting van de twee knoppen. Stilzetten mag vanaf tier 2 en zonder tweede
bevestiging — stoppen is de veilige kant, en een pincode intikken terwijl je ziet dat het
misgaat kost seconden die je niet hebt. De noodstop eruit halen is wél gevoelig en vraagt
om een bevestiging.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_confirmation, require_permission
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.models.activity import ActivityAction
from app.models.user import User
from app.quantlab import risk_limits
from app.quantlab.agents import AGENT_UITLEG
from app.quantlab.budget import MODE_UITLEG
from app.quantlab.budget_limits import RESERVE_EUR
from app.quantlab.dataquality import CHECK_UITLEG, DataCheck, QualityVerdict
from app.quantlab.risk import VETO_UITLEG, RiskSnapshot, RiskVeto, one_r_eur
from app.schemas.quant import (
    AgentSpendOut,
    BudgetStatusOut,
    ControlIn,
    DataCheckOut,
    DataQualityOut,
    IngestRunOut,
    KillSwitchOut,
    LlmCallOut,
    RiskEventOut,
    RiskLimitsOut,
    RiskStatusOut,
    StorageOut,
)
from app.services import quant_cost_service, quant_data_service, quant_risk_service
from app.services.activity_service import log_activity

router = APIRouter(prefix="/quant", tags=["quant"])

read_access = require_permission("quant.read")
costs_access = require_permission("quant.costs.read")
stop_access = require_permission("quant.run.stop")
start_access = require_confirmation("quant.run.start")
reset_access = require_confirmation("quant.risk.reset")


def _limits_out() -> RiskLimitsOut:
    return RiskLimitsOut(
        risk_per_trade_pct=risk_limits.RISK_PER_TRADE_PCT,
        max_risk_per_trade_r=risk_limits.MAX_RISK_PER_TRADE_R,
        max_open_risk_r=risk_limits.MAX_OPEN_RISK_R,
        day_loss_halt_r=risk_limits.DAY_LOSS_HALT_R,
        week_loss_stop_r=risk_limits.WEEK_LOSS_STOP_R,
        heartbeat_max_age_seconds=risk_limits.HEARTBEAT_MAX_AGE_SECONDS,
    )


def _status_out(snapshot: RiskSnapshot) -> RiskStatusOut:
    """De stand voor het scherm, met alles wat op dit moment tegenhoudt.

    `blocking` is een lijst en niet één reden: op het scherm wil je alles zien wat eraan
    scheelt, ook als de Risk Officer bij een instap maar één reden teruggeeft."""
    blokkades: list[tuple[str, str]] = []
    if snapshot.kill_switch_active:
        blokkades.append((RiskVeto.KILL_SWITCH_ACTIVE.value, VETO_UITLEG[RiskVeto.KILL_SWITCH_ACTIVE]))
    if snapshot.heartbeat_stale:
        blokkades.append((RiskVeto.HEARTBEAT_STALE.value, VETO_UITLEG[RiskVeto.HEARTBEAT_STALE]))
    if snapshot.week_stop_engaged:
        blokkades.append((RiskVeto.WEEK_LOSS_STOP.value, VETO_UITLEG[RiskVeto.WEEK_LOSS_STOP]))
    if snapshot.day_halt_engaged:
        blokkades.append((RiskVeto.DAY_LOSS_HALT.value, VETO_UITLEG[RiskVeto.DAY_LOSS_HALT]))
    if snapshot.equity <= 0:
        blokkades.append((RiskVeto.NO_EQUITY.value, VETO_UITLEG[RiskVeto.NO_EQUITY]))

    return RiskStatusOut(
        trading_mode="paper",
        limits=_limits_out(),
        equity_eur=snapshot.equity,
        one_r_eur=one_r_eur(snapshot.equity),
        open_risk_r=snapshot.open_risk_r,
        realized_day_r=snapshot.realized_day_r,
        realized_week_r=snapshot.realized_week_r,
        week_stop_level_r=snapshot.week_stop_level_r,
        kill_switch_active=snapshot.kill_switch_active,
        day_halt_engaged=snapshot.day_halt_engaged,
        week_stop_engaged=snapshot.week_stop_engaged,
        heartbeat_age_seconds=snapshot.heartbeat_age_seconds,
        heartbeat_stale=snapshot.heartbeat_stale,
        entries_allowed=not blokkades,
        blocking=[code for code, _ in blokkades],
        explanation=(
            " ".join(uitleg for _, uitleg in blokkades)
            if blokkades
            else "Binnen alle grenzen; er mogen papieren posities open."
        ),
    )


async def _snapshot(session: AsyncSession, settings: Settings) -> RiskSnapshot:
    return await quant_risk_service.snapshot(
        session, equity=settings.quant_paper_equity_eur
    )


@router.get("/risk", response_model=RiskStatusOut)
async def risk_status(
    user: User = Depends(read_access),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    return _status_out(await _snapshot(session, settings))


@router.get("/risk/events", response_model=list[RiskEventOut])
async def risk_events(
    limit: int = Query(default=20, ge=1, le=200),
    user: User = Depends(read_access),
    session: AsyncSession = Depends(get_session),
):
    """Elke beslissing van de Risk Officer, de geweigerde voorop in de tijd.

    Dit is het bewijs dat de grenzen werken. Een leeg logboek na een week draaien betekent
    niet dat alles goed ging, maar dat er niets is langsgekomen."""
    return await quant_risk_service.recent_events(session, limit=limit)


@router.post("/risk/kill-switch", response_model=KillSwitchOut)
async def engage_kill_switch(
    body: ControlIn,
    user: User = Depends(stop_access),
    session: AsyncSession = Depends(get_session),
):
    rij = await quant_risk_service.engage_kill_switch(
        session, reason=body.reason, source="user", user_id=user.id
    )
    await log_activity(
        session,
        action=ActivityAction.QUANT_KILL_SWITCH_ENGAGED,
        user_id=user.id,
        message="Noodstop van het Quant Lab aangezet",
        subject_type="quant_risk_control",
        subject_id=rij.id,
        context={"reason": body.reason},
    )
    await session.commit()
    return KillSwitchOut(
        kill_switch_active=True,
        reason=rij.reason,
        changed_at=rij.created_at,
        explanation=VETO_UITLEG[RiskVeto.KILL_SWITCH_ACTIVE],
    )


@router.delete("/risk/kill-switch", response_model=KillSwitchOut)
async def release_kill_switch(
    body: ControlIn,
    user: User = Depends(start_access),
    session: AsyncSession = Depends(get_session),
):
    """De noodstop eruit halen. Gevoelig, dus met een bevestiging en met een reden erbij."""
    rij = await quant_risk_service.release_kill_switch(
        session, reason=body.reason, user_id=user.id
    )
    await log_activity(
        session,
        action=ActivityAction.QUANT_KILL_SWITCH_RELEASED,
        user_id=user.id,
        message="Noodstop van het Quant Lab eruit gehaald",
        subject_type="quant_risk_control",
        subject_id=rij.id,
        context={"reason": body.reason},
    )
    await session.commit()
    return KillSwitchOut(
        kill_switch_active=False,
        reason=rij.reason,
        changed_at=rij.created_at,
        explanation="De noodstop staat uit. De gewone grenzen gelden weer.",
    )


@router.post("/risk/week-reset", response_model=RiskStatusOut)
async def reset_week_stop(
    body: ControlIn,
    user: User = Depends(reset_access),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """De weekstop opnieuw zetten. Alleen de eigenaar, en alleen met de hand.

    De teller gaat niet op nul: het verlies van deze week blijft staan. Wat verschuift is
    de grens, met 8R vanaf de stand van dit moment."""
    rij = await quant_risk_service.reset_week_stop(
        session, user_id=user.id, reason=body.reason
    )
    await log_activity(
        session,
        action=ActivityAction.QUANT_WEEK_STOP_RESET,
        user_id=user.id,
        message="Weekstop van het Quant Lab opnieuw gezet",
        subject_type="quant_risk_control",
        subject_id=rij.id,
        context={"reason": body.reason},
    )
    await session.commit()
    return _status_out(await _snapshot(session, settings))


@router.get("/costs", response_model=BudgetStatusOut)
async def costs(
    user: User = Depends(costs_access),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    stand = await quant_cost_service.budget_status(session)
    return BudgetStatusOut(
        mode=stand.mode.value,
        explanation=MODE_UITLEG[stand.mode],
        month=stand.month,
        month_total_eur=stand.month_total_eur,
        month_remaining_eur=stand.month_remaining_eur,
        monthly_cap_eur=stand.monthly_cap_eur,
        monthly_warning_eur=stand.monthly_warning_eur,
        reserve_eur=RESERVE_EUR,
        usd_eur_rate=settings.quant_usd_eur_rate,
        agents=[
            AgentSpendOut(
                agent=regel.agent.value,
                description=AGENT_UITLEG[regel.agent],
                monthly_budget_eur=regel.monthly_budget_eur,
                month_spent_eur=regel.month_spent_eur,
                month_remaining_eur=regel.month_remaining_eur,
                daily_cap_eur=regel.daily_cap_eur,
                day_spent_eur=regel.day_spent_eur,
            )
            for regel in stand.agents
        ],
    )


@router.get("/costs/calls", response_model=list[LlmCallOut])
async def cost_calls(
    limit: int = Query(default=20, ge=1, le=200),
    user: User = Depends(costs_access),
    session: AsyncSession = Depends(get_session),
):
    """Het kostenboek zelf. Met de tokens erbij, want "waarom werd dit duurder" is altijd
    een vraag over hoeveel context erin ging."""
    return await quant_cost_service.recent_calls(session, limit=limit)


# --- De datalaag (fase 2) ----------------------------------------------------


@router.get("/data/quality", response_model=DataQualityOut)
async def data_quality(
    user: User = Depends(read_access),
    session: AsyncSession = Depends(get_session),
):
    """Het datakwaliteitsrapport, met de ketting van de ruwe opslag erbij.

    De ketting staat er niet voor niets naast de bevindingen: een rapport over data die
    onderweg is veranderd, zegt niets over de data die er oorspronkelijk stond."""
    rapport = await quant_data_service.quality(session)
    ketting = await quant_data_service.verify_chain(session)
    gevonden = {bevinding.check: bevinding for bevinding in rapport.findings}
    return DataQualityOut(
        verdict=rapport.verdict.value,
        explanation=rapport.explanation,
        ticks=rapport.ticks,
        raw_events=rapport.raw_events,
        pools=rapport.pools,
        synthetic_events=rapport.synthetic_events,
        first_observed_at=rapport.first_observed_at,
        last_observed_at=rapport.last_observed_at,
        chain_ok=ketting.ok,
        chain_explanation=ketting.explanation,
        findings=[_check_out(b.check, b) for b in rapport.findings],
        checks=[_check_out(check, gevonden.get(check)) for check in DataCheck],
    )


def _check_out(check: DataCheck, bevinding=None) -> DataCheckOut:
    if bevinding is None:
        return DataCheckOut(
            check=check.value,
            count=0,
            severity=QualityVerdict.OK.value,
            explanation=CHECK_UITLEG[check],
            examples=[],
        )
    return DataCheckOut(
        check=check.value,
        count=bevinding.count,
        severity=bevinding.severity.value,
        explanation=bevinding.explanation,
        examples=list(bevinding.examples),
    )


@router.get("/data/storage", response_model=StorageOut)
async def data_storage(
    user: User = Depends(read_access),
    session: AsyncSession = Depends(get_session),
):
    """Hoeveel er staat en hoeveel het per dag wordt. Gemeten, niet geschat."""
    stand = await quant_data_service.storage_report(session)
    return StorageOut(
        events=stand.events,
        ticks=stand.ticks,
        bytes_stored=stand.bytes_stored,
        bytes_per_event=stand.bytes_per_event,
        measured_seconds=stand.measured_seconds,
        first_received_at=stand.first_received_at,
        last_received_at=stand.last_received_at,
        projected_bytes_per_day=stand.projected_bytes_per_day,
        projected_bytes_per_month=stand.projected_bytes_per_month,
        explanation=stand.explanation,
    )


@router.get("/data/runs", response_model=list[IngestRunOut])
async def data_runs(
    limit: int = Query(default=20, ge=1, le=200),
    user: User = Depends(read_access),
    session: AsyncSession = Depends(get_session),
):
    """Wat de Scout wanneer heeft opgenomen, en waarom hij stopte."""
    return list(await quant_data_service.recent_runs(session, limit=limit))
