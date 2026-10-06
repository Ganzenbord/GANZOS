"""Binance' publieke bulkdata als bron: echte marktdata, zonder sleutel.

`data.binance.vision` publiceert per paar en per dag (of maand) een ZIP met candles of
trades. Geen sleutel, geen rate limit, geen abonnement — alleen een host die open moet staan
in de netwerkpolicy van deze omgeving. Zie `docs/quant-lab/databronnen.md`.

Alles hieronder is geverifieerd tegen Binance' **eigen** repo `binance/binance-public-data`
(README, `python/utility.py`, `python/enums.py`, gelezen op 6 oktober 2026): de URL-opzet,
de bestandsnamen, de intervallen en de kolomindeling. Dat is een stap verder dan bij de
Vybe-adapter, waar de vorm uit een voorbeeldimplementatie kwam.

Drie dingen die het ontwerp raken:

1. **De tijdstempels van SPOT-data zijn vanaf 1 januari 2025 in MICROseconden**, daarvoor in
   milliseconden. Binance zegt dat zelf in hun README. Reken je met de verkeerde eenheid,
   dan komt een bestand uit 2024 in 1970 terecht of een bestand uit 2025 in het jaar 56000 —
   en in beide gevallen zijn het nog steeds getallen die er plausibel uitzien. Daarom kiest
   `to_datetime()` de eenheid per waarde, en weigert hij een getal dat in geen van beide
   eenheden een plausibel jaar oplevert.

2. **De tick krijgt de SLOTtijd van de candle, niet de openingstijd.** De slotkoers was pas
   waar aan het eind van het interval. Zou de tick op de openingstijd staan, dan ziet de
   engine een prijs die nog een heel interval lang niet bestaat — bij minuutcandles zestig
   seconden gratis vooruitkijken. Dat is precies het soort fout dat een backtest mooi maakt
   en waardeloos.

3. **Een paar tegen BTC of ETH is geen dollarprijs.** `BTCUSDT` wel, `ETHBTC` niet. Is het
   quote-token geen dollarstablecoin, dan blijft `price_usd` leeg; een prijs in de verkeerde
   eenheid maakt elk filter en elke uitkomst stilzwijgend verkeerd. Dezelfde regel als bij
   de Vybe-adapter.

Wat de ruwe opslag hier bewaart: een CSV-regel heeft geen zelfbeschrijvende vorm, dus gaat
elke regel als JSON-array van de **onveranderde veldteksten** de opslag in. De waarden
blijven letter voor letter wat er in het bestand stond; alleen de scheidingstekens van het
CSV-formaat verdwijnen. Dat is een afwijking van "bewaar de bytes" uit sectie 11, en ze
staat hier zodat ze zichtbaar is.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.quantlab.feed import RawEvent
from app.quantlab.normalize import MarketTick, TickKind

logger = logging.getLogger("ganz.quantlab.sources.binance")

SOURCE_NAME = "binance"
STREAM_KLINES = "klines"
STREAM_TRADES = "trades"
CHAIN = "binance-spot"

BASE_URL = "https://data.binance.vision/"

# Alleen SPOT. De futures-markten (`um`, `cm`) bestaan ook, maar de microseconde-regel
# hierboven geldt expliciet voor SPOT — die data erbij halen zonder dat na te kijken zou
# betekenen dat de klok er stil naast ligt.
TRADING_TYPE = "spot"

# Geverifieerd: python/enums.py in binance/binance-public-data.
INTERVALS: tuple[str, ...] = (
    "1s", "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w", "1mo",
)
# Dagbestanden bestaan niet voor de langste intervallen.
DAILY_INTERVALS: tuple[str, ...] = tuple(i for i in INTERVALS if i not in {"3d", "1w", "1mo"})

PERIODS: tuple[str, ...] = ("daily", "monthly")

# Het aantal kolommen zoals Binance ze publiceert. Minder betekent een afgebroken of
# beschadigde regel, en die wordt niet aangevuld.
KLINE_COLUMNS = 12
TRADE_COLUMNS = 7

# Kolomnummers, met de naam erbij zodat de code leesbaar blijft zonder de README erbij.
KLINE_OPEN_TIME = 0
KLINE_CLOSE = 4
KLINE_CLOSE_TIME = 6
KLINE_QUOTE_VOLUME = 7

TRADE_PRICE = 1
TRADE_QUOTE_QTY = 3
TRADE_TIME = 4

# De eenheid van een tijdstempel volgt uit het aantal cijfers: milliseconden zijn dertien
# cijfers, microseconden zestien. Twaalf en vijftien staan erbij voor de randen.
MS_DIGITS = (12, 13)
US_DIGITS = (15, 16)

# Buiten dit venster is een tijdstempel geen tijdstempel maar een fout in het bestand.
# De ondergrens ligt vóór de oprichting van Binance, de bovengrens ruim in de toekomst.
PLAUSIBLE_FROM = datetime(2015, 1, 1, tzinfo=timezone.utc)
PLAUSIBLE_UNTIL = datetime(2040, 1, 1, tzinfo=timezone.utc)

# De quote-tokens die we als dollar behandelen. Een aanname, net als bij Vybe: een
# stablecoin kan van de dollar afwijken, en bij paniek wijkt hij het meest af.
USD_QUOTES: tuple[str, ...] = ("USDT", "USDC", "FDUSD", "BUSD", "TUSD", "USDP", "DAI", "USD")
# Alle quote-tokens die we kennen, om een paar in basis en quote te kunnen splitsen. Langste
# eerst, anders eet "USD" de "USDT" op.
KNOWN_QUOTES: tuple[str, ...] = tuple(
    sorted(
        USD_QUOTES + ("BTC", "ETH", "BNB", "SOL", "EUR", "TRY", "BRL", "JPY", "GBP", "AUD"),
        key=len,
        reverse=True,
    )
)

_EENHEDEN = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


# --- Tijd ---------------------------------------------------------------------


def detect_time_unit(value: int | str) -> str:
    """Milliseconden of microseconden? Dit is de belangrijkste functie in dit bestand.

    De keuze gaat op het aantal cijfers en niet op een datumgrens, want een bestand zegt
    nergens welke eenheid het gebruikt: de overgang zat op 1 januari 2025 en is alleen uit
    het getal zelf te zien.
    """
    cijfers = len(str(abs(int(value))))
    if cijfers in MS_DIGITS:
        return "ms"
    if cijfers in US_DIGITS:
        return "us"
    raise ValueError(
        f"{value} heeft {cijfers} cijfers en is dus noch milliseconden noch microseconden. "
        "Niet gokken: dit is een fout in het bestand."
    )


def to_datetime(value: int | str) -> datetime:
    """Een tijdstempel uit een Binance-bestand, in UTC.

    Rekent met hele getallen en niet via een float: 1735693199999999 microseconden heeft
    zestien significante cijfers, en daar houdt een float het niet droog.
    """
    try:
        getal = int(value)
    except (TypeError, ValueError) as fout:
        raise ValueError(f"Geen tijdstempel: {value!r}") from fout
    if getal <= 0:
        raise ValueError(f"Een tijdstempel van {getal} bestaat niet.")

    eenheid = detect_time_unit(getal)
    deler = 1_000_000 if eenheid == "us" else 1_000
    seconden, rest = divmod(getal, deler)
    microseconden = rest if eenheid == "us" else rest * 1_000
    moment = datetime.fromtimestamp(seconden, tz=timezone.utc) + timedelta(
        microseconds=microseconden
    )
    if not (PLAUSIBLE_FROM <= moment < PLAUSIBLE_UNTIL):
        raise ValueError(
            f"{getal} komt als {eenheid} uit op {moment.isoformat()}, en dat ligt buiten "
            f"{PLAUSIBLE_FROM.date()} - {PLAUSIBLE_UNTIL.date()}."
        )
    return moment


def interval_seconds(interval: str) -> int | None:
    """Hoeveel seconden een interval beslaat. `1mo` heeft geen vast antwoord.

    Een kalendermaand is 28 tot 31 dagen. Daar een getal voor verzinnen zou betekenen dat
    elk volumevenster van een maandcandle er net naast ligt, dus blijft het leeg.
    """
    if interval not in INTERVALS:
        raise ValueError(f"Onbekend interval {interval!r}; bekend zijn {', '.join(INTERVALS)}.")
    if interval.endswith("mo"):
        return None
    getal, eenheid = interval[:-1], interval[-1]
    return int(getal) * _EENHEDEN[eenheid]


# --- URL's --------------------------------------------------------------------


def _periode(period: str, date: str) -> None:
    if period not in PERIODS:
        raise ValueError(f"Periode is {', '.join(PERIODS)}, niet {period!r}.")
    verwacht = 10 if period == "daily" else 7
    if len(date) != verwacht or date.count("-") != (2 if period == "daily" else 1):
        vorm = "JJJJ-MM-DD" if period == "daily" else "JJJJ-MM"
        raise ValueError(f"Een {period}-bestand heeft een datum als {vorm}, niet {date!r}.")


def kline_url(*, symbol: str, interval: str, date: str, period: str = "daily") -> str:
    """De URL van één candlebestand. Geverifieerd tegen hun eigen `get_path`."""
    _periode(period, date)
    if interval not in INTERVALS:
        raise ValueError(f"Onbekend interval {interval!r}.")
    if period == "daily" and interval not in DAILY_INTERVALS:
        raise ValueError(f"Van {interval} bestaan geen dagbestanden, alleen maandbestanden.")
    paar = symbol.upper()
    return (
        f"{BASE_URL}data/{TRADING_TYPE}/{period}/klines/{paar}/{interval}/"
        f"{paar}-{interval}-{date}.zip"
    )


def trades_url(*, symbol: str, date: str, period: str = "daily") -> str:
    """De URL van één tradesbestand. Trades hebben geen interval in het pad."""
    _periode(period, date)
    paar = symbol.upper()
    return f"{BASE_URL}data/{TRADING_TYPE}/{period}/trades/{paar}/{paar}-trades-{date}.zip"


def checksum_url(file_url: str) -> str:
    """Bij elk bestand staat een `.CHECKSUM`.

    Die niet gebruiken zou betekenen dat een halve download stilzwijgend een corpus met een
    gat oplevert — en een gat in de data is precies waar fase 2 op controleert.
    """
    return f"{file_url}.CHECKSUM"


# --- Het paar splitsen --------------------------------------------------------


def split_symbol(symbol: str) -> tuple[str, str]:
    """`BTCUSDT` wordt `("BTC", "USDT")`. Onbekend quote-token: quote blijft leeg.

    Binance zet basis en quote aan elkaar zonder scheidingsteken, dus dit kan alleen met een
    lijst bekende quote-tokens. Een paar dat er niet in staat, wordt niet gegokt.
    """
    paar = symbol.upper()
    for quote in KNOWN_QUOTES:
        if paar.endswith(quote) and len(paar) > len(quote):
            return paar[: -len(quote)], quote
    return paar, ""


def _decimaal(waarde: object) -> Decimal | None:
    """Een getal uit het bestand. Komt als tekst, en dat is goed nieuws: rechtstreeks naar
    Decimal, nooit via een float."""
    if waarde is None or str(waarde).strip() == "":
        return None
    try:
        return Decimal(str(waarde))
    except InvalidOperation:
        return None


def _velden(payload_raw: str) -> list[str]:
    """De velden van een regel terug uit de ruwe opslag.

    `parse_float=Decimal` voor het geval een regel ooit als getal in de opslag staat in
    plaats van als tekst: dan gaat de waarde nog steeds niet door een float heen. Onze eigen
    bron schrijft tekst weg, maar dat is een aanname over de toekomst die niets kost om te
    laten kloppen.
    """
    waarde = json.loads(payload_raw, parse_float=Decimal)
    if not isinstance(waarde, list):
        raise ValueError("Een Binance-event hoort een JSON-array met de kolommen te zijn.")
    return [str(veld) for veld in waarde]


# --- De bron ------------------------------------------------------------------


@dataclass(frozen=True)
class BinanceZipSource:
    """Eén gedownloade ZIP als databron.

    Hij opent zelf geen verbinding: downloaden en inlezen staan los, zodat het inlezen
    offline te testen is en een corpus herhaalbaar blijft. Downloaden doet
    `scripts/quant_binance_download.py`.
    """

    path: str | Path
    symbol: str
    interval: str | None = None
    stream: str = STREAM_KLINES
    name: str = SOURCE_NAME

    def streams(self) -> tuple[str, ...]:
        return (self.stream,)

    async def events(self) -> AsyncIterator[RawEvent]:
        bestand = Path(self.path)
        with zipfile.ZipFile(bestand) as archief:
            namen = [naam for naam in archief.namelist() if naam.lower().endswith(".csv")]
            if not namen:
                raise ValueError(f"{bestand.name} bevat geen CSV-bestand.")
            for naam in sorted(namen):
                with archief.open(naam) as binair:
                    tekst = io.TextIOWrapper(binair, encoding="utf-8", newline="")
                    for nummer, rij in enumerate(csv.reader(tekst)):
                        if not rij or not any(veld.strip() for veld in rij):
                            continue
                        if nummer == 0 and not rij[0].strip().lstrip("-").isdigit():
                            # Sommige bestanden hebben een kopregel. Die melden en
                            # overslaan; stil weggooien zou een regel kunnen kosten die
                            # wél data was.
                            logger.info("Kopregel overgeslagen in %s: %s", naam, rij)
                            continue
                        yield RawEvent(
                            source=self.name,
                            stream=self.stream,
                            payload_raw=json.dumps(rij, separators=(",", ":")),
                            received_at=self._klok(rij),
                        )

    def _klok(self, rij: list[str]) -> datetime:
        """Wanneer dit event bekend kon zijn.

        Voor een candle is dat de slottijd en niet de openingstijd: eerder bestond de
        slotkoers nog niet. Lukt het niet, dan onze eigen klok — dan valt het op in de
        controle op feedvertraging in plaats van dat het verdwijnt.
        """
        kolom = KLINE_CLOSE_TIME if self.stream == STREAM_KLINES else TRADE_TIME
        try:
            return to_datetime(rij[kolom])
        except (IndexError, ValueError):
            return datetime.now(timezone.utc)


# --- Normaliseren -------------------------------------------------------------


@dataclass(frozen=True)
class BinanceKlineNormalizer:
    """Zet een candle om in een tick.

    Het symbool en het interval staan niet in de regel zelf, dus komen ze van buiten. Dat is
    ook de reden dat deze normalizer niet standaard in `NORMALIZERS` staat: wie een bestand
    inleest, weet welk paar en welk interval het is en registreert hem dan.
    """

    symbol: str
    interval: str

    def normalize(self, event: RawEvent) -> Sequence[MarketTick]:
        rij = _velden(event.payload_raw)
        if len(rij) < KLINE_COLUMNS:
            raise ValueError(
                f"Een candle heeft {KLINE_COLUMNS} kolommen, deze regel heeft {len(rij)}."
            )

        open_tijd = to_datetime(rij[KLINE_OPEN_TIME])
        sluit_tijd = to_datetime(rij[KLINE_CLOSE_TIME])
        if sluit_tijd <= open_tijd:
            raise ValueError(
                f"Candle sluit ({sluit_tijd.isoformat()}) niet na het openen "
                f"({open_tijd.isoformat()})."
            )

        basis, quote = split_symbol(self.symbol)
        in_dollars = quote in USD_QUOTES
        slotkoers = _decimaal(rij[KLINE_CLOSE])
        quote_volume = _decimaal(rij[KLINE_QUOTE_VOLUME])

        return (
            MarketTick(
                # Een candle is een samenvatting van meerdere trades, geen losse trade.
                kind=TickKind.TICK,
                venue=SOURCE_NAME,
                chain=CHAIN,
                pool_address=self.symbol.upper(),
                token_address=basis,
                # De slottijd: zie punt 2 bovenaan dit bestand.
                observed_at=sluit_tijd,
                price_usd=slotkoers if in_dollars else None,
                # Volume is geen diepte. Het filter "liquiditeit minstens 50x de positie"
                # heeft orderboekdiepte nodig, en die staat niet in een candle. Leeg laten
                # blokkeert de instap, en dat is de juiste kant om fout te zitten.
                liquidity_usd=None,
                volume_usd=quote_volume if in_dollars else None,
                volume_window_seconds=interval_seconds(self.interval),
                pool_created_at=None,
            ),
        )


@dataclass(frozen=True)
class BinanceTradesNormalizer:
    """Zet één trade om in een tick.

    Trades zijn fijner dan candles: elke trade heeft zijn eigen tijdstempel, dus de
    latency-stresstest uit fase 3 kan er wél verschil in zien. De kant van de trade
    (`isBuyerMaker`) blijft hier liggen omdat `MarketTick` geen veld voor richting heeft —
    een kolom inlezen die nergens heen gaat, suggereert dat ermee gerekend wordt.
    """

    symbol: str

    def normalize(self, event: RawEvent) -> Sequence[MarketTick]:
        rij = _velden(event.payload_raw)
        if len(rij) < TRADE_COLUMNS:
            raise ValueError(
                f"Een trade heeft {TRADE_COLUMNS} kolommen, deze regel heeft {len(rij)}."
            )

        basis, quote = split_symbol(self.symbol)
        in_dollars = quote in USD_QUOTES
        return (
            MarketTick(
                kind=TickKind.TRADE,
                venue=SOURCE_NAME,
                chain=CHAIN,
                pool_address=self.symbol.upper(),
                token_address=basis,
                observed_at=to_datetime(rij[TRADE_TIME]),
                price_usd=_decimaal(rij[TRADE_PRICE]) if in_dollars else None,
                liquidity_usd=None,
                volume_usd=_decimaal(rij[TRADE_QUOTE_QTY]) if in_dollars else None,
                # Eén trade is geen venster; de Screener telt ze zelf op tot vensters.
                volume_window_seconds=0,
                pool_created_at=None,
            ),
        )
