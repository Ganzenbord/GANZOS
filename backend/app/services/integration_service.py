"""Gekoppelde diensten en hun sleutels.

Hier komt binnen wat een gebruiker zelf invult — een API-sleutel van Higgsfield, een token
van een dienst die Ganz nog niet kent. Twee regels die het hele bestand verklaren:

- **Wat erin gaat, gaat versleuteld de database in** en komt er nooit meer uit richting een
  client. Er is geen functie die de gegevens teruggeeft; alleen de rest van de backend kan
  ze ophalen om er iets mee te doen.
- **Bijwerken zonder nieuwe gegevens laat de oude staan.** Zonder die regel zou een
  gebruiker die alleen de naam wijzigt zijn sleutel kwijtraken — en dat merkt hij pas als
  er iets niet meer werkt.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityAction
from app.models.platform import Integration, IntegrationStatus
from app.services.activity_service import log_activity
from app.utils.crypto import get_vault


class IntegrationNotFound(Exception):
    pass


async def _owned(session: AsyncSession, integration_id: int, user_id: int) -> Integration:
    rij = await session.get(Integration, integration_id)
    # Dezelfde uitkomst voor "bestaat niet" en "is niet van jou": anders kun je via de
    # foutmelding aftasten welke ID's bestaan.
    if rij is None or rij.user_id != user_id:
        raise IntegrationNotFound
    return rij


async def list_integrations(session: AsyncSession, user_id: int) -> list[Integration]:
    rijen = await session.scalars(
        select(Integration).where(Integration.user_id == user_id).order_by(Integration.name)
    )
    return list(rijen.all())


async def create(
    session: AsyncSession, user_id: int, data: dict[str, Any]
) -> Integration:
    credentials = data.pop("credentials", None)
    rij = Integration(user_id=user_id, **data)
    rij.credentials_encrypted = get_vault().encrypt(credentials)
    rij.status = (
        IntegrationStatus.CONNECTED if credentials else IntegrationStatus.DISCONNECTED
    )
    session.add(rij)
    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.INTEGRATION_CONNECTED,
        user_id=user_id,
        message=f"Dienst '{rij.name}' gekoppeld.",
        subject_type="integration",
        subject_id=rij.id,
        # Alleen wélke dienst. Wat erin is gezet gaat hier niet langs, en het logboek
        # schoont zijn context bovendien zelf nog een keer.
        context={"key": rij.key},
    )
    return rij


async def update(
    session: AsyncSession, user_id: int, integration_id: int, data: dict[str, Any]
) -> Integration:
    rij = await _owned(session, integration_id, user_id)
    if "credentials" in data:
        credentials = data.pop("credentials")
        # None betekent "laat staan", een leeg object betekent "gooi weg". Dat onderscheid
        # is er omdat de client de oude waarde niet kan terugsturen: hij heeft hem nooit
        # gezien.
        if credentials is not None:
            rij.credentials_encrypted = get_vault().encrypt(credentials)
            rij.status = (
                IntegrationStatus.CONNECTED if credentials else IntegrationStatus.DISCONNECTED
            )
            rij.status_detail = None
    for veld, waarde in data.items():
        if waarde is not None:
            setattr(rij, veld, waarde)
    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.INTEGRATION_UPDATED,
        user_id=user_id,
        message=f"Dienst '{rij.name}' gewijzigd.",
        subject_type="integration",
        subject_id=rij.id,
    )
    return rij


async def delete(session: AsyncSession, user_id: int, integration_id: int) -> None:
    rij = await _owned(session, integration_id, user_id)
    naam = rij.name
    await session.delete(rij)
    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.INTEGRATION_REMOVED,
        user_id=user_id,
        message=f"Dienst '{naam}' losgekoppeld.",
        subject_type="integration",
        subject_id=integration_id,
    )


async def credentials_for(
    session: AsyncSession, user_id: int, key: str
) -> dict[str, Any] | None:
    """De gegevens van één dienst, voor gebruik binnen de backend.

    Met opzet geen endpoint erboven: dit is de enige weg naar buiten, en die loopt niet
    langs een client.
    """
    rij = await session.scalar(
        select(Integration).where(Integration.user_id == user_id, Integration.key == key)
    )
    if rij is None:
        return None
    return get_vault().decrypt(rij.credentials_encrypted)
