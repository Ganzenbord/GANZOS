"""Loopt elke functie van Ganz één keer langs en zegt wat er stuk is.

    GANZ_ALLOW_SEED_DATA=true python -m scripts.ganz_smoke

Dit meet iets anders dan de testsuite. De tests controleren of een onderdeel doet wat het
hoort te doen; dit controleert of de hele app overeind blijft als je er in één keer
langsloopt. Daar zijn al twee dingen mee gevonden die de tests niet zagen:

1. `/api/memory` gaf een harde 500 bij élke aanroep — het beloofde in zijn `response_model`
   iets anders dan het teruggaf. Er was geen test die dat endpoint aanraakte.
2. Een lege database bewijst niets. Een leeg lijstje valideert ook tegen een verkeerd
   itemschema, dus deze proef zet eerst voorbeelddata klaar. Zonder dat stond de bug er nog.

Wat een regel betekent:

- `200`-`204`: de functie antwoordt.
- `4xx`: ook een antwoord ("mag niet", "ontbreekt een parameter") en dus geen storing.
- `STUK`: een serverfout of een uitzondering. Dit is wat je wil zien staan op nul.

Alleen GET-routes zonder padparameters: dit is een levenstekencheck, geen functietest. Iets
aanmaken of versturen hoort in de testsuite, niet in een proef die je tegen een echte
database kunt draaien.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from httpx import ASGITransport, AsyncClient

from app.core.database import Database
from app.core.security import create_token, hash_password
from app.main import create_app
from app.models import Base, User
from app.models.user import TIER_OWNER
import app.models.quantlab  # noqa: F401  zodat ook die tabellen bestaan

E_MAIL = "smoke@example.com"


async def _verse_database(url: str) -> int:
    db = Database.from_url(url)
    async with db.engine.begin() as verbinding:
        await verbinding.run_sync(Base.metadata.drop_all)
        await verbinding.run_sync(Base.metadata.create_all)
    async with db.session() as sessie:
        gebruiker = User(
            email=E_MAIL,
            display_name="Smoke",
            password_hash=hash_password("alleen-voor-deze-proef"),
            tier=TIER_OWNER,
        )
        sessie.add(gebruiker)
        await sessie.commit()
        await sessie.refresh(gebruiker)
        uid = int(gebruiker.id)
    await db.dispose()
    return uid


async def main() -> int:
    parser = argparse.ArgumentParser(description="Levenstekencheck over alle functies")
    parser.add_argument(
        "--no-seed",
        action="store_true",
        help="zonder voorbeelddata; dan vindt de proef minder, zie de uitleg bovenaan",
    )
    args = parser.parse_args()

    url = os.environ.get("GANZ_DATABASE_URL", "")
    if "sqlite" not in url:
        # Deze proef gooit de tabellen weg en maakt ze opnieuw. Dat mag nooit per ongeluk
        # op een echte database gebeuren.
        raise SystemExit(
            "Zet GANZ_DATABASE_URL op een eigen sqlite-bestand: deze proef maakt de "
            f"database leeg. Nu: {url or '(leeg)'}"
        )

    uid = await _verse_database(url)
    if not args.no_seed:
        from scripts.seed_dev import seed

        await seed(E_MAIL)

    app = create_app()
    token = create_token(subject=str(uid), minutes=60)
    paden = sorted(
        {
            route.path
            for route in app.routes
            if "GET" in (getattr(route, "methods", None) or set())
            and "{" not in getattr(route, "path", "{")
            and getattr(route, "path", "").startswith(("/api", "/health"))
        }
    )

    goed: list[tuple[str, int]] = []
    stuk: list[tuple[str, str]] = []
    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app), base_url="http://smoke"
    ) as client:
        for pad in paden:
            try:
                antwoord = await client.get(
                    pad, headers={"Authorization": f"Bearer {token}"}
                )
            except Exception as fout:  # een uitzondering is altijd een storing
                stuk.append((pad, f"{type(fout).__name__}: {fout}"))
                continue
            if antwoord.status_code >= 500:
                stuk.append((pad, f"{antwoord.status_code} {antwoord.text[:200]}"))
            else:
                goed.append((pad, antwoord.status_code))

    for pad, code in goed:
        print(f"  {code}  {pad}")
    print(f"\n{len(goed)} routes antwoordden, {len(stuk)} gaven een serverfout.")
    for pad, detail in stuk:
        print(f"  STUK  {pad}\n        {detail}")
    return 1 if stuk else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
