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

from app.integrations import catalog
from app.integrations.base import ProviderNotConfigured
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


# --- De catalogus: welke functie welke sleutel nodig heeft --------------------


async def require_credentials(
    session: AsyncSession, user_id: int, key: str
) -> dict[str, Any]:
    """De sleutels van één functie, of een nette weigering.

    Dit is de aanroep die elke functie hoort te doen in plaats van zelf in de database te
    kijken. Hij doet drie dingen die je anders op vijftien plekken opnieuw schrijft: hij
    weet welke velden deze functie nodig heeft, hij zegt in gewone taal wat er mist, en hij
    zegt waar je het moet invullen.

    Wat hij níét doet: een half ingevulde koppeling doorlaten. Een functie die met een
    ontbrekend veld begint, faalt halverwege — en bij een upload of een mail is halverwege
    de slechtste plek om te stoppen.
    """
    plek = catalog.capability(key)
    naam = plek.name if plek else key

    if plek is not None and plek.store is not catalog.Store.INTEGRATION:
        raise ProviderNotConfigured(
            f"De sleutels van {naam} staan niet in de kluis maar hier: "
            f"{catalog.WAAR_UITLEG[plek.store]}"
        )

    gegevens = await credentials_for(session, user_id, key)
    if not gegevens:
        waar = catalog.WAAR_UITLEG[catalog.Store.INTEGRATION]
        raise ProviderNotConfigured(f"{naam} is nog niet gekoppeld. {waar}")

    if plek is not None:
        ontbreekt = [veld.label for veld in plek.fields if not gegevens.get(veld.name)]
        if ontbreekt:
            raise ProviderNotConfigured(
                f"De koppeling met {naam} is niet compleet. Nog invullen: "
                f"{', '.join(ontbreekt)}."
            )
    return gegevens


async def catalog_status(
    session: AsyncSession, user_id: int, *, settings: Any
) -> list[dict[str, Any]]:
    """Per functie: wat hij kan, welke sleutels hij nodig heeft en of ze er zijn.

    Hier komt **nooit een sleutel** uit, alleen de namen van velden die nog ontbreken. Dat
    onderscheid is het hele punt: je moet kunnen zien dat `signing_secret` leeg is zonder
    dat iemand `bot_token` kan lezen.
    """
    rijen = {rij.key: rij for rij in await list_integrations(session, user_id)}

    uit: list[dict[str, Any]] = []
    for plek in catalog.CATALOG:
        ontbreekt: list[str] = []
        if not plek.fields:
            # Niet elke functie heeft een sleutel nodig (de Binance-bulkdata bijvoorbeeld
            # alleen netwerktoegang). "Ingevuld" melden zou suggereren dat jij iets hebt
            # gedaan wat niet nodig was.
            staat = "no_key_needed"
        elif plek.store is catalog.Store.INTEGRATION:
            rij = rijen.get(plek.key)
            if rij is None or rij.credentials_encrypted is None:
                staat = "missing"
                ontbreekt = [veld.name for veld in plek.fields]
            else:
                # Ontsleutelen om te zien welke velden er zijn. Alleen de námen gaan naar
                # buiten; de waarden blijven in dit proces.
                gegevens = get_vault().decrypt(rij.credentials_encrypted) or {}
                ontbreekt = [veld.name for veld in plek.fields if not gegevens.get(veld.name)]
                staat = "incomplete" if ontbreekt else "connected"
        elif plek.store is catalog.Store.SERVER:
            ontbreekt = [
                veld.name for veld in plek.fields if not getattr(settings, veld.name, None)
            ]
            staat = "missing" if ontbreekt else "connected"
        else:
            # Per kanaal of per rekening: of die er zijn, hangt van het kanaal af en niet
            # van de gebruiker. Hier alleen zeggen waar het hoort.
            staat = "elsewhere"

        uit.append(
            {
                "key": plek.key,
                "name": plek.name,
                "category": plek.category,
                "purpose": plek.purpose,
                "store": plek.store.value,
                "where": catalog.WAAR_UITLEG[plek.store],
                "docs_url": plek.docs_url,
                "wired": plek.wired,
                "note": plek.note,
                "state": staat,
                "missing_fields": ontbreekt,
                "fields": [
                    {
                        "name": veld.name,
                        "label": veld.label,
                        "masked": veld.masked,
                        "hint": veld.hint,
                    }
                    for veld in plek.fields
                ],
            }
        )
    return uit
