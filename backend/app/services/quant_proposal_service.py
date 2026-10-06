"""De inbox van de Reviewer (sectie 6).

De Reviewer mag nooit config of een hypothese wijzigen. Alles wat hij voorstelt komt hier
terecht, en blijft hier tot iemand het goedkeurt of afwijst.

Goedkeuren verandert ook dan niets rechtstreeks: het is een aantekening dat dit voorstel
heeft geleid tot een nieuwe hypothese-versie, en die versie wordt apart geregistreerd met
zijn eigen hash. Zo blijft het onmogelijk dat een agent een parameter verzet.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.quantlab import QuantProposal
from app.quantlab.agents_llm import ReviewerReport

OPEN = "open"
APPROVED = "approved"
REJECTED = "rejected"


async def store(
    session: AsyncSession, report: ReviewerReport, *, period: str
) -> list[QuantProposal]:
    """Zet de voorstellen uit een rapport in de inbox. Een afgekeurd rapport levert niets op."""
    if not report.ok:
        return []
    rijen = [
        QuantProposal(
            period=period,
            title=voorstel.title,
            argument=voorstel.argument,
            changes_nl=voorstel.changes_nl,
            status=OPEN,
        )
        for voorstel in report.proposals
    ]
    for rij in rijen:
        session.add(rij)
    await session.flush()
    return rijen


async def reject(
    session: AsyncSession, *, proposal_id: int, note: str, user_id: int | None = None
) -> QuantProposal | None:
    """Afwijzen, met een reden. De rij blijft staan.

    Weggooien zou betekenen dat je niet meer kunt zien wat je hebt afgewezen en waarom — en
    dat is precies wat je een half jaar later wil nalezen, als iemand hetzelfde voorstelt.
    """
    rij = await session.get(QuantProposal, proposal_id)
    if rij is None:
        return None
    rij.status = REJECTED
    rij.decision_note = note[:500]
    rij.decided_by = user_id
    rij.decided_at = datetime.now(timezone.utc)
    await session.flush()
    return rij


async def approve(
    session: AsyncSession,
    *,
    proposal_id: int,
    note: str,
    hypothesis_id: int | None = None,
    user_id: int | None = None,
) -> QuantProposal | None:
    """Goedkeuren. Verandert zelf niets: het legt vast dat dit voorstel tot een nieuwe
    hypothese-versie heeft geleid, en die versie staat los geregistreerd met zijn eigen hash.
    """
    rij = await session.get(QuantProposal, proposal_id)
    if rij is None:
        return None
    rij.status = APPROVED
    rij.decision_note = note[:500]
    rij.decided_by = user_id
    rij.decided_at = datetime.now(timezone.utc)
    rij.applied_hypothesis_id = hypothesis_id
    await session.flush()
    return rij


async def open_proposals(
    session: AsyncSession, *, limit: int = 50
) -> Sequence[QuantProposal]:
    rijen = await session.execute(
        select(QuantProposal)
        .where(QuantProposal.status == OPEN)
        .order_by(QuantProposal.id.desc())
        .limit(limit)
    )
    return list(rijen.scalars().all())


async def recent(session: AsyncSession, *, limit: int = 50) -> Sequence[QuantProposal]:
    rijen = await session.execute(
        select(QuantProposal).order_by(QuantProposal.id.desc()).limit(limit)
    )
    return list(rijen.scalars().all())
