"""Diensten koppelen met je eigen sleutels.

Hiermee zet een gebruiker zijn eigen gegevens in Ganz, vanaf welk apparaat dan ook: de
sleutels staan op de server en niet op de computer waar je toevallig achter zit.

Wat opvalt als je dit vergelijkt met een gewone CRUD: er is geen GET die de gegevens
teruggeeft. Niet vergeten — er is geen weg terug. Wat je invult, kun je vervangen of
weggooien, niet uitlezen. Dat is wat "server-side versleuteld, nooit client-side" in de
praktijk betekent.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_confirmation
from app.core.database import get_session
from app.models.user import User
from app.schemas.integration import IntegrationIn, IntegrationPatch
from app.schemas.platform import IntegrationOut
from app.services import integration_service

router = APIRouter(prefix="/integrations", tags=["integrations"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Deze koppeling bestaat niet")


def _uit(rij) -> IntegrationOut:
    """Eén plek die bepaalt wat er van een koppeling naar buiten gaat."""
    return IntegrationOut(
        id=rij.id,
        key=rij.key,
        name=rij.name,
        category=rij.category,
        status=rij.status,
        status_detail=rij.status_detail,
        last_checked_at=rij.last_checked_at,
        has_credentials=rij.credentials_encrypted is not None,
    )


@router.post("", response_model=IntegrationOut, status_code=status.HTTP_201_CREATED)
async def create_integration(
    payload: IntegrationIn,
    user: User = Depends(require_confirmation("integrations.manage")),
    session: AsyncSession = Depends(get_session),
):
    """Koppel een dienst met je eigen sleutel.

    Vraagt een tweede bevestiging: een sleutel toevoegen is iets wat Ganz daarna namens jou
    kan gebruiken.
    """
    rij = await integration_service.create(session, user.id, payload.model_dump())
    await session.commit()
    return _uit(rij)


@router.patch("/{integration_id}", response_model=IntegrationOut)
async def update_integration(
    integration_id: int,
    payload: IntegrationPatch,
    user: User = Depends(require_confirmation("integrations.manage")),
    session: AsyncSession = Depends(get_session),
):
    """Wijzig een koppeling. Laat je `credentials` weg, dan blijft de oude sleutel staan."""
    try:
        rij = await integration_service.update(
            session, user.id, integration_id, payload.model_dump(exclude_unset=True)
        )
    except integration_service.IntegrationNotFound:
        raise NOT_FOUND from None
    await session.commit()
    return _uit(rij)


@router.delete("/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration(
    integration_id: int,
    user: User = Depends(require_confirmation("integrations.manage")),
    session: AsyncSession = Depends(get_session),
):
    try:
        await integration_service.delete(session, user.id, integration_id)
    except integration_service.IntegrationNotFound:
        raise NOT_FOUND from None
    await session.commit()
