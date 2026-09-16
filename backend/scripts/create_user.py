"""Maak de eerste gebruiker aan.

Gebruik:
    python -m scripts.create_user --email jij@example.com --name Stef --tier 1

Het wachtwoord wordt gevraagd en niet meegegeven op de commandoregel; anders staat
het in de geschiedenis van je terminal.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.database import SessionLocal
from app.models.user import User
from app.security import hash_password


async def create(email: str, name: str, tier: int, password: str) -> None:
    async with SessionLocal() as session:
        existing = await session.scalar(select(User).where(User.email == email.lower()))
        if existing is not None:
            print(f"Er bestaat al een gebruiker met {email}.")
            return
        session.add(
            User(
                email=email.lower(),
                display_name=name,
                password_hash=hash_password(password),
                tier=tier,
            )
        )
        await session.commit()
    print(f"Gebruiker {email} aangemaakt met tier {tier}.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Maak een Ganz-gebruiker aan")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--tier", type=int, default=1, choices=[1, 2, 3, 4])
    args = parser.parse_args()

    password = getpass.getpass("Wachtwoord: ")
    if len(password) < 10:
        print("Kies een wachtwoord van minstens 10 tekens.")
        return 1
    if password != getpass.getpass("Nog een keer: "):
        print("De wachtwoorden zijn niet gelijk.")
        return 1

    asyncio.run(create(args.email, args.name, args.tier, password))
    return 0


if __name__ == "__main__":
    sys.exit(main())
