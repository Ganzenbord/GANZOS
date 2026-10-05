"""Laat zien dat een opgenomen uur bit-voor-bit herhaalbaar is.

Dit is de acceptatie-eis van fase 2, en hij is met opzet niet "de tests zijn groen" maar
een losse proef tegen een echte PostgreSQL. De tests draaien op SQLite; het verschil tussen
de twee databases zit juist in hoe ze getallen en tijdstippen teruggeven, en dat is precies
waar een afdruk over heen kan vallen.

    GANZ_DATABASE_URL=postgresql+asyncpg://ganz:ganz@localhost:5432/ganz_proef \\
      python -m scripts.quant_replay_proof

Het script schrijft rijen en ruimt ze daarna op. Draai hem op een proefdatabase.

De data is **synthetisch**: verzonnen. Deze proef gaat over de machinerie (de ketting, de
replay, de controles), niet over de markt.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update

from app.core.config import get_settings
from app.core.database import Database
from app.models.quantlab import (
    QuantIngestRun,
    QuantMarketTick,
    QuantRawEvent,
)
from app.quantlab.synthetic import SyntheticDefect, SyntheticPoolSource
from app.services import quant_data_service

START = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
UUR = timedelta(hours=1)


def kop(tekst: str) -> None:
    print(f"\n{tekst}\n{'-' * len(tekst)}")


def bron(**kwargs) -> SyntheticPoolSource:
    opties = dict(seed=20261007, start_at=START, duration=UUR, pools=3, cadence_seconds=10)
    opties.update(kwargs)
    return SyntheticPoolSource(**opties)


async def leegmaken(session) -> None:
    for tabel in (QuantMarketTick, QuantRawEvent, QuantIngestRun):
        await session.execute(delete(tabel))
    await session.commit()


async def opnemen(session) -> None:
    kop("1. Een uur opnemen")
    opname = await quant_data_service.record(session, source=bron())
    await session.commit()
    print(f"  events opgeslagen:   {opname.events}")
    print(f"  ticks genormaliseerd:{opname.ticks:>5}")
    print(f"  onleesbaar:          {opname.parse_failures}")
    print(f"  dubbel:              {opname.duplicates}")
    print(f"  bytes ruwe tekst:    {opname.bytes_stored}")


async def ketting(session) -> None:
    kop("2. De ketting narekenen")
    controle = await quant_data_service.verify_chain(session)
    print(f"  sluit aan:  {controle.ok}")
    print(f"  afdruk:     {controle.digest}")
    assert controle.ok


async def replayen(session) -> None:
    kop("3. Replayen en de afdrukken vergelijken")
    voor = await quant_data_service.normalized_digest(session)
    ruw_voor = (await quant_data_service.verify_chain(session)).digest
    ticks_voor = int(
        await session.scalar(select(func.count()).select_from(QuantMarketTick)) or 0
    )

    herhaling = await quant_data_service.replay(session)
    await session.commit()

    ticks_na = int(
        await session.scalar(select(func.count()).select_from(QuantMarketTick)) or 0
    )
    ruw_na = (await quant_data_service.verify_chain(session)).digest

    print(f"  afdruk voor:  {voor}")
    print(f"  afdruk na:    {herhaling.digest}")
    print(f"  identiek:     {herhaling.digest == voor}")
    print(f"  ticks voor/na:{ticks_voor} / {ticks_na}")
    print(f"  ruwe opslag onveranderd: {ruw_voor == ruw_na}")
    assert herhaling.digest == voor
    assert ticks_voor == ticks_na
    assert ruw_voor == ruw_na


async def afdruk_is_streng(session) -> None:
    kop("4. Zou de afdruk een verschil wel merken?")
    voor = await quant_data_service.normalized_digest(session)
    eerste = (
        await session.execute(
            select(QuantMarketTick)
            .where(QuantMarketTick.price_usd.is_not(None))
            .order_by(QuantMarketTick.id)
            .limit(1)
        )
    ).scalar_one()
    oude_prijs = eerste.price_usd
    await session.execute(
        update(QuantMarketTick).where(QuantMarketTick.id == eerste.id).values(price_usd=1)
    )
    await session.commit()
    na = await quant_data_service.normalized_digest(session)
    print(f"  één prijs veranderd ({oude_prijs} -> 1): afdruk verschilt = {na != voor}")
    assert na != voor

    # En weer terugzetten door te replayen: de ruwe opslag is de waarheid.
    await quant_data_service.replay(session)
    await session.commit()
    herstel = await quant_data_service.normalized_digest(session)
    print(f"  na een replay weer de oude afdruk:       {herstel == voor}")
    assert herstel == voor


async def gebroken_corpus(session) -> None:
    kop("5. Een aangepaste ruwe rij stopt de replay")
    eerste = (
        await session.execute(select(QuantRawEvent).order_by(QuantRawEvent.seq).limit(1))
    ).scalar_one()
    origineel = eerste.payload_raw
    await session.execute(
        update(QuantRawEvent).where(QuantRawEvent.id == eerste.id).values(payload_raw="{}")
    )
    await session.commit()

    controle = await quant_data_service.verify_chain(session)
    print(f"  ketting sluit aan: {controle.ok}")
    print(f"  eerste foute seq:  {controle.first_bad_seq}")
    try:
        await quant_data_service.replay(session)
        raise AssertionError("de replay had moeten weigeren")
    except quant_data_service.CorpusBroken as fout:
        print(f"  replay weigert:    {fout}")

    await session.execute(
        update(QuantRawEvent).where(QuantRawEvent.id == eerste.id).values(payload_raw=origineel)
    )
    await session.commit()
    print(f"  na herstel sluit de ketting weer aan: "
          f"{(await quant_data_service.verify_chain(session)).ok}")


async def kwaliteit_en_opslag(session) -> None:
    kop("6. Datakwaliteit en opslaggroei van het schone uur")
    rapport = await quant_data_service.quality(session, now=START + UUR)
    print(f"  oordeel:     {rapport.verdict.value}")
    print(f"  pools:       {rapport.pools}")
    print(f"  bevindingen: {[(b.check.value, b.count) for b in rapport.findings] or 'geen'}")
    print(f"  uitleg:      {rapport.explanation}")

    stand = await quant_data_service.storage_report(session, now=START + UUR)
    print(f"\n  {stand.explanation}")
    print(f"  bytes per event: {stand.bytes_per_event}")

    kop("7. Hetzelfde uur, nu met ingebouwde gebreken")
    await leegmaken(session)
    await quant_data_service.record(
        session,
        source=bron(
            defects={
                SyntheticDefect.GAP,
                SyntheticDefect.ZERO_PRICE,
                SyntheticDefect.DUPLICATE,
                SyntheticDefect.BROKEN_JSON,
            }
        ),
    )
    await session.commit()
    rapport = await quant_data_service.quality(session, now=START + UUR)
    print(f"  oordeel: {rapport.verdict.value}")
    for bevinding in rapport.findings:
        print(f"    {bevinding.check.value:<24} {bevinding.count:>4}  {bevinding.severity.value}")
        print(f"      voorbeeld: {bevinding.examples[0] if bevinding.examples else '-'}")


async def main() -> None:
    settings = get_settings()
    if settings.is_production:
        raise SystemExit("Dit script schrijft rijen en draait niet in productie.")
    url = os.environ.get("GANZ_DATABASE_URL", settings.database_url)
    print(f"Database: {url.rsplit('@', 1)[-1]}")
    print("Data: synthetisch (verzonnen). Deze proef gaat over de machinerie, niet over de markt.")
    database = Database.from_url(url)
    try:
        async with database.session() as session:
            await leegmaken(session)
            await opnemen(session)
            await ketting(session)
            await replayen(session)
            await afdruk_is_streng(session)
            await gebroken_corpus(session)
            await kwaliteit_en_opslag(session)
            await leegmaken(session)
            print("\nTabellen weer leeggemaakt.")
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
