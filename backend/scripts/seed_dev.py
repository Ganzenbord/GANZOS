"""Voorbeelddata om tijdens het bouwen iets op het scherm te hebben.

Draait alleen als GANZ_ALLOW_SEED_DATA=true én de omgeving niet productie is. Alles
wat hier wordt aangemaakt krijgt het voorvoegsel [DEMO], zodat je in één oogopslag
ziet dat het geen echte gegevens zijn.

    GANZ_ALLOW_SEED_DATA=true python -m scripts.seed_dev --email jij@example.com
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models.finance import AccountStatus, AccountType, FinancialAccount
from app.models.platform import Integration, IntegrationStatus, MemoryEntry, Skill
from app.models.social import ChannelStatus, SocialChannel, SocialChannelStats
from app.models.todo import TodoSubtask, TodoTask
from app.models.upload import UploadSchedule, UploadStatus
from app.models.user import User
from app.utils.crypto import get_vault

DEMO = "[DEMO] "


async def seed(email: str) -> None:
    settings = get_settings()
    if settings.is_production or not settings.allow_seed_data:
        raise SystemExit(
            "Seed-data staat uit. Zet GANZ_ALLOW_SEED_DATA=true en draai niet in productie."
        )

    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            raise SystemExit(f"Geen gebruiker met {email}. Maak er eerst een met create_user.")

        katten = TodoTask(
            user_id=user.id, title=DEMO + "Katten eten geven", scheduled_time="08:00",
            category="Huis", sort_order=1,
        )
        katten.subtasks = [TodoSubtask(title="Pip", sort_order=0), TodoSubtask(title="Johann", sort_order=1)]
        session.add(katten)
        for order, (title, time, category) in enumerate(
            [
                ("Back-up controleren", "09:00", "Systeem"),
                ("YouTube statistieken controleren", "10:00", "Kanalen"),
                ("Social media planning controleren", "11:00", "Kanalen"),
                ("Inbox controleren", "13:00", "Mail"),
                ("Trading dashboard controleren", "15:00", "Geld"),
                ("Avondroutine", "21:00", "Huis"),
            ],
            start=2,
        ):
            session.add(
                TodoTask(
                    user_id=user.id, title=DEMO + title, scheduled_time=time,
                    category=category, sort_order=order,
                )
            )

        vault = get_vault()
        session.add(
            FinancialAccount(
                user_id=user.id, provider="manual", account_type=AccountType.BANK,
                name=DEMO + "Betaalrekening", currency="EUR",
                current_value=Decimal("12420.00"), current_value_eur=Decimal("12420.00"),
                status=AccountStatus.CONNECTED, last_synced_at=now,
                credentials_encrypted=vault.encrypt({"value": "12420.00"}),
            )
        )
        session.add(
            FinancialAccount(
                user_id=user.id, provider="manual", account_type=AccountType.BROKER,
                name=DEMO + "Beleggingen", currency="EUR",
                current_value=Decimal("21950.00"), current_value_eur=Decimal("21950.00"),
                status=AccountStatus.CONNECTED, last_synced_at=now,
                credentials_encrypted=vault.encrypt({"value": "21950.00"}),
            )
        )

        for platform, name, followers, views, likes, offset in [
            ("youtube", "YouTube Kanaal 1", 6421, 2_000_000, 30_000, timedelta(hours=1, minutes=13)),
            ("instagram", "Instagram Reels", 4832, 500_000, 15_000, timedelta(hours=2, minutes=4)),
            ("tiktok", "TikTok Kanaal 1", 1589, 340_000, 3_921, timedelta(minutes=28)),
        ]:
            channel = SocialChannel(
                user_id=user.id, platform=platform, channel_name=DEMO + name,
                status=ChannelStatus.CONNECTED, last_synced_at=now,
            )
            session.add(channel)
            await session.flush()
            session.add(
                SocialChannelStats(
                    channel_id=channel.id, followers=followers, views=views, likes=likes,
                    measured_at=now,
                )
            )
            # Een tweede meting van vorige week, zodat de groei iets kan laten zien.
            session.add(
                SocialChannelStats(
                    channel_id=channel.id, followers=int(followers * 0.92),
                    views=int(views * 0.9), likes=int(likes * 0.9),
                    measured_at=now - timedelta(days=8),
                )
            )
            session.add(
                UploadSchedule(
                    channel_id=channel.id, title=DEMO + "Volgende aflevering",
                    scheduled_at=now + offset, status=UploadStatus.SCHEDULED,
                )
            )

        for name, category in [
            ("Ochtendbriefing", "routine"), ("Kanaalanalyse", "kanalen"),
            ("Mailtriage", "mail"), ("Uploadplanner", "kanalen"),
        ]:
            session.add(Skill(user_id=user.id, name=DEMO + name, category=category))
        for key, name, category, status in [
            ("youtube", "YouTube", "social", IntegrationStatus.CONNECTED),
            ("tiktok", "TikTok", "social", IntegrationStatus.REAUTH_REQUIRED),
            ("agenda", "Agenda", "kalender", IntegrationStatus.CONNECTED),
        ]:
            session.add(
                Integration(
                    user_id=user.id, key=key, name=DEMO + name, category=category,
                    status=status, last_checked_at=now,
                )
            )
        session.add(
            MemoryEntry(
                user_id=user.id, title=DEMO + "Voorkeur uploadtijd",
                content="Shorts doen het het best rond 18:00.", importance=3,
            )
        )
        await session.commit()
    print("Voorbeelddata toegevoegd. Alles begint met [DEMO].")


def main() -> int:
    parser = argparse.ArgumentParser(description="Vul Ganz met voorbeelddata (alleen development)")
    parser.add_argument("--email", required=True)
    asyncio.run(seed(parser.parse_args().email))
    return 0


if __name__ == "__main__":
    sys.exit(main())
