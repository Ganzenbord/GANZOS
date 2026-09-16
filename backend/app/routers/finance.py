"""De finance API.

Alleen tier 1. Wijzigen vraagt bovendien een tweede bevestiging met het wachtwoord.
Antwoorden bevatten nooit credentials — die staan versleuteld en blijven daar.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.deps import require_confirmation, require_permission
from app.integrations.finance.registry import describe_finance_providers
from app.models.user import User
from app.schemas.finance import (
    FinanceHistoryPoint,
    FinanceOverviewOut,
    FinancialAccountIn,
    FinancialAccountOut,
    FinancialAccountPatch,
)
from app.services import finance_service
from app.services.finance_service import AccountNotFound

router = APIRouter(prefix="/finance", tags=["finance"])

read_access = require_permission("finance.read")
manage_access = require_confirmation("finance.manage")

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Dit account bestaat niet")


@router.get("/overview", response_model=FinanceOverviewOut)
async def overview(
    user: User = Depends(read_access), session: AsyncSession = Depends(get_session)
):
    return await finance_service.overview(session, user.id)


@router.get("/providers")
async def providers(user: User = Depends(read_access)):
    return describe_finance_providers()


@router.get("/accounts", response_model=list[FinancialAccountOut])
async def list_accounts(
    user: User = Depends(read_access), session: AsyncSession = Depends(get_session)
):
    return list(await finance_service.list_accounts(session, user.id))


@router.post(
    "/accounts", response_model=FinancialAccountOut, status_code=status.HTTP_201_CREATED
)
async def create_account(
    payload: FinancialAccountIn,
    user: User = Depends(manage_access),
    session: AsyncSession = Depends(get_session),
):
    account = await finance_service.create_account(session, user.id, payload.model_dump())
    # Meteen ophalen, zodat het dashboard niet eerst een leeg account laat zien.
    await finance_service.sync_account(session, account)
    await session.commit()
    await session.refresh(account)
    return account


@router.patch("/accounts/{account_id}", response_model=FinancialAccountOut)
async def update_account(
    account_id: int,
    payload: FinancialAccountPatch,
    user: User = Depends(manage_access),
    session: AsyncSession = Depends(get_session),
):
    try:
        account = await finance_service.update_account(
            session, user.id, account_id, payload.model_dump(exclude_unset=True)
        )
    except AccountNotFound:
        raise NOT_FOUND from None
    await session.commit()
    await session.refresh(account)
    return account


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: int,
    user: User = Depends(manage_access),
    session: AsyncSession = Depends(get_session),
):
    try:
        await finance_service.delete_account(session, user.id, account_id)
    except AccountNotFound:
        raise NOT_FOUND from None
    await session.commit()


@router.post("/sync", response_model=FinanceOverviewOut)
async def sync_now(
    user: User = Depends(manage_access), session: AsyncSession = Depends(get_session)
):
    """Handmatig bijwerken. De scheduler doet dit normaal vanzelf."""
    await finance_service.sync_all(session, user.id)
    await session.commit()
    return await finance_service.overview(session, user.id)


@router.get("/history", response_model=list[FinanceHistoryPoint])
async def history(
    days: int = Query(default=90, ge=1, le=1825),
    user: User = Depends(read_access),
    session: AsyncSession = Depends(get_session),
):
    return [
        FinanceHistoryPoint(captured_at=row.captured_at, total_eur=row.total_eur)
        for row in await finance_service.history(session, user.id, days)
    ]
