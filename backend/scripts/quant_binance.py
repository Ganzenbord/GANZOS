"""Binance' publieke bulkdata ophalen en inlezen.

    # eerst downloaden (heeft netwerk nodig)
    python -m scripts.quant_binance download --symbol BTCUSDT --interval 1m \
        --from 2026-09-01 --to 2026-09-07 --dir ../data/binance

    # daarna inlezen in de database (geen netwerk nodig)
    GANZ_DATABASE_URL=... python -m scripts.quant_binance import \
        --symbol BTCUSDT --interval 1m --dir ../data/binance

Downloaden en inlezen staan met opzet apart. Zo is een corpus herhaalbaar: de bestanden op
schijf zijn de waarheid, en inlezen kan zo vaak als je wil zonder dat de bron opnieuw iets
hoeft te sturen. Het is ook de enige manier om een download te kunnen controleren vóórdat
hij de database in gaat.

**Elk bestand wordt tegen zijn `.CHECKSUM` gecontroleerd.** Binance publiceert naast elk
bestand de SHA-256 ervan (geverifieerd in hun README, 6 oktober 2026). Die controle
overslaan zou betekenen dat een halve download stilzwijgend een corpus met een gat oplevert
— en een gat in de data is precies waar de controle uit fase 2 op zoekt.

De SHA-256 van het bestand gaat ook mee in de ingest-run. Dat is geen netheid: Binance zegt
zelf dat archiefbestanden later vervangen kunnen worden (twee keer gebeurd, 2022-04-21 en
2022-08-08). Zonder die hash is "we hebben dit gemeten op dit bestand" niet meer na te gaan.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

from app.quantlab.sources.binance import (
    DAILY_INTERVALS,
    INTERVALS,
    BinanceKlineNormalizer,
    BinanceTradesNormalizer,
    BinanceZipSource,
    checksum_url,
    kline_url,
    trades_url,
)

HOST = "data.binance.vision"
HEX64 = re.compile(r"\b[0-9a-f]{64}\b", re.IGNORECASE)

GEEN_NETWERK = f"""
Geen verbinding met {HOST}.

Deze omgeving laat alleen hosts door die in de netwerkpolicy staan. Zet `{HOST}`
erbij onder Network access -> Custom -> Allowed domains (de standaardlijst met
pakketbronnen laat je staan), of kies een ruimere toegang.

Downloaden kan ook op een eigen machine: de ZIP's die daar landen, leest
`python -m scripts.quant_binance import` zonder netwerk in.
"""


def _datums(van: str, tot: str, period: str) -> list[str]:
    """De datums tussen twee grenzen, in de vorm die het bestandspad wil."""
    if period == "monthly":
        begin = date.fromisoformat(f"{van}-01" if len(van) == 7 else van)
        eind = date.fromisoformat(f"{tot}-01" if len(tot) == 7 else tot)
        uit: list[str] = []
        loper = begin.replace(day=1)
        while loper <= eind:
            uit.append(loper.strftime("%Y-%m"))
            loper = (loper.replace(day=28) + timedelta(days=5)).replace(day=1)
        return uit
    begin, eind = date.fromisoformat(van), date.fromisoformat(tot)
    if eind < begin:
        raise SystemExit("--to ligt voor --from")
    return [
        (begin + timedelta(days=n)).isoformat() for n in range((eind - begin).days + 1)
    ]


def _sha256(pad: Path) -> str:
    hasher = hashlib.sha256()
    with pad.open("rb") as bestand:
        for blok in iter(lambda: bestand.read(1024 * 1024), b""):
            hasher.update(blok)
    return hasher.hexdigest()


def _verwachte_hash(tekst: str) -> str:
    """De hash uit een `.CHECKSUM`-bestand.

    De vorm is die van `sha256sum -c`: de hash, witruimte, de bestandsnaam. We zoeken het
    eerste 64-tekens hex-woord in plaats van op kolom te splitsen, zodat een extra `*` of
    een andere scheiding de controle niet stilletjes overslaat.
    """
    treffer = HEX64.search(tekst)
    if not treffer:
        raise ValueError("In het .CHECKSUM-bestand staat geen SHA-256.")
    return treffer.group(0).lower()


def _urls(args: argparse.Namespace, datum: str) -> str:
    if args.kind == "trades":
        return trades_url(symbol=args.symbol, date=datum, period=args.period)
    return kline_url(
        symbol=args.symbol, interval=args.interval, date=datum, period=args.period
    )


def download(args: argparse.Namespace) -> int:
    map_ = Path(args.dir)
    map_.mkdir(parents=True, exist_ok=True)

    gelukt = overgeslagen = ontbreekt = 0
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        for datum in _datums(args.date_from, args.date_to, args.period):
            url = _urls(args, datum)
            doel = map_ / url.rsplit("/", 1)[-1]

            try:
                antwoord = client.get(checksum_url(url))
            except httpx.HTTPError as fout:
                print(GEEN_NETWERK)
                print(f"(technisch: {type(fout).__name__}: {fout})")
                return 2

            if antwoord.status_code in (403, 407, 451, 502, 503):
                # Zo weigert een egress-proxy: met een status, niet met een
                # verbindingsfout. Zonder deze tak kreeg je een traceback in plaats van
                # het antwoord op de vraag wat er mis is.
                print(GEEN_NETWERK)
                print(f"(technisch: HTTP {antwoord.status_code} van de proxy)")
                return 2
            if antwoord.status_code == 404:
                # Een dag die niet bestaat is geen fout: een paar begint ergens, en de dag
                # van vandaag staat er pas morgen.
                print(f"  {doel.name}: bestaat niet bij Binance (404)")
                ontbreekt += 1
                continue
            antwoord.raise_for_status()
            verwacht = _verwachte_hash(antwoord.text)

            if doel.exists() and _sha256(doel) == verwacht:
                print(f"  {doel.name}: al binnen en klopt")
                overgeslagen += 1
                continue

            tijdelijk = doel.with_suffix(doel.suffix + ".deel")
            with client.stream("GET", url) as stroom:
                stroom.raise_for_status()
                with tijdelijk.open("wb") as bestand:
                    for blok in stroom.iter_bytes(1024 * 1024):
                        bestand.write(blok)

            werkelijk = _sha256(tijdelijk)
            if werkelijk != verwacht:
                # Niet hernoemen. Een bestand met de goede naam en de verkeerde inhoud is
                # erger dan geen bestand: het wordt ingelezen en niemand ziet het.
                tijdelijk.unlink(missing_ok=True)
                print(
                    f"  {doel.name}: AFGEKEURD, sha256 {werkelijk[:16]} hoort "
                    f"{verwacht[:16]} te zijn"
                )
                return 1
            tijdelijk.replace(doel)
            print(f"  {doel.name}: binnen, sha256 {werkelijk[:16]} klopt")
            gelukt += 1

    print(
        f"\n{gelukt} gedownload, {overgeslagen} stonden er al, {ontbreekt} bestaan niet "
        f"bij Binance."
    )
    print(f"Inlezen: python -m scripts.quant_binance import --symbol {args.symbol} "
          f"--interval {args.interval} --dir {args.dir}")
    return 0


async def inlezen(args: argparse.Namespace) -> int:
    # Laat binnen: zonder database-instellingen is `download` nog wel te gebruiken.
    from app.core.config import get_settings
    from app.core.database import create_database
    from app.quantlab.normalize import NORMALIZERS
    from app.services import quant_data_service

    map_ = Path(args.dir)
    patroon = (
        f"{args.symbol.upper()}-trades-*.zip"
        if args.kind == "trades"
        else f"{args.symbol.upper()}-{args.interval}-*.zip"
    )
    bestanden = sorted(map_.glob(patroon))
    if not bestanden:
        raise SystemExit(f"Geen bestanden als {patroon} in {map_}")

    # De normalizer hangt aan het paar en het interval, en die staan niet in de regels zelf.
    # Daarom staat hij niet standaard in de registratie maar wordt hij hier gezet.
    NORMALIZERS["binance"] = (
        BinanceTradesNormalizer(symbol=args.symbol)
        if args.kind == "trades"
        else BinanceKlineNormalizer(symbol=args.symbol, interval=args.interval)
    )

    database = create_database(get_settings())
    try:
        async with database.session() as session:
            for pad in bestanden:
                afdruk = _sha256(pad)
                bron = BinanceZipSource(
                    path=pad,
                    symbol=args.symbol,
                    interval=args.interval,
                    stream="trades" if args.kind == "trades" else "klines",
                )
                uitkomst = await quant_data_service.record(
                    session, source=bron, note=f"{pad.name} sha256={afdruk}"[:200]
                )
                await session.commit()
                print(
                    f"  {pad.name}: {uitkomst.events} events, {uitkomst.ticks} ticks, "
                    f"{uitkomst.duplicates} dubbel, {uitkomst.parse_failures} onleesbaar"
                )

            ketting = await quant_data_service.verify_chain(session)
            rapport = await quant_data_service.quality(session)
            afdruk_corpus = await quant_data_service.normalized_digest(session)

        print(f"\nketting: {'klopt' if ketting.ok else 'KLOPT NIET'} ({ketting.events} events)")
        print(f"oordeel: {rapport.verdict.value} - {rapport.explanation}")
        for bevinding in rapport.findings:
            print(f"  {bevinding.check.value}: {bevinding.count} ({bevinding.severity.value})")
            for voorbeeld in bevinding.examples:
                print(f"      {voorbeeld}")
        print(f"ticks: {rapport.ticks}, pools: {rapport.pools}")
        print(f"van {rapport.first_observed_at} tot {rapport.last_observed_at}")
        print(f"synthetische events: {rapport.synthetic_events}")
        print(f"corpusafdruk: {afdruk_corpus}")
        return 0 if ketting.ok else 1
    finally:
        await database.dispose()
        NORMALIZERS.pop("binance", None)


def main() -> int:
    parser = argparse.ArgumentParser(description="Binance-bulkdata ophalen en inlezen")
    sub = parser.add_subparsers(dest="commando", required=True)

    for naam in ("download", "import"):
        p = sub.add_parser(naam)
        p.add_argument("--symbol", required=True, help="bijvoorbeeld BTCUSDT")
        p.add_argument("--interval", default="1m", choices=INTERVALS)
        p.add_argument("--kind", default="klines", choices=("klines", "trades"))
        p.add_argument("--period", default="daily", choices=("daily", "monthly"))
        p.add_argument("--dir", default="data/binance")
        if naam == "download":
            p.add_argument("--from", dest="date_from", required=True, help="JJJJ-MM-DD")
            p.add_argument("--to", dest="date_to", required=True, help="JJJJ-MM-DD")

    args = parser.parse_args()
    if args.period == "daily" and args.kind == "klines" and args.interval not in DAILY_INTERVALS:
        raise SystemExit(
            f"Van {args.interval} bestaan geen dagbestanden; gebruik --period monthly."
        )

    if args.commando == "download":
        return download(args)
    return asyncio.run(inlezen(args))


if __name__ == "__main__":
    sys.exit(main())
