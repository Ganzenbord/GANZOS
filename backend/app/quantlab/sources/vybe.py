"""Vybe Network als bron van Solana-trades.

Dit is de eerste adapter naar een echte bron. Hij is geschreven tegen de vorm die in de
referentie-implementatie van de leverancier zelf staat
(github.com/vybenetwork/solana-ohlc-api, commit bekeken op 2026-10-06), en **niet tegen de
live API** — die is vanuit deze omgeving onbereikbaar. Dat is een flink verschil met gokken,
maar het is geen verificatie. Zie docs/quant-lab/databronnen.md.

Waarom trades en niet candles: het endpoint `/v4/tokens/{mint}/candles` heeft een parameter
`eliminateCloseToOpenGaps` die **standaard op true staat**. Die vult gaten op door de vorige
slotkoers als nieuwe openingskoers te gebruiken. Voor een chart is dat netjes; voor dit lab
is het een leugen — precies de gaten die de datakwaliteitscontrole uit fase 2 moet vinden,
worden dan weggepoetst. Trades hebben dat probleem niet.

Drie dingen die uit de vorm van een trade volgen en die het ontwerp raken:

1. **De klok is de slot, niet de tijd.** `blockTime` is een Unix-tijd in seconden, en dat is
   te grof: op Solana vallen er meerdere trades in dezelfde seconde. `(slot, txIndex,
   ixOrdinal, iixOrdinal)` geeft een exacte ordening. Voor de volgorde gebruiken we die;
   `blockTime` blijft de klok voor vensters en leeftijd.
2. **`signature` is een echte sleutel.** Samen met de ordinalen is een trade daarmee uniek
   aan te wijzen. Dat is beter dan de hash over de payload die fase 2 gebruikt: die kan twee
   werkelijk verschillende events met dezelfde tekst niet onderscheiden.
3. **`price` is niet in dollars.** Het is de prijs van het basis-token in het quote-token.
   Bij een pool tegen SOL is dat een prijs in SOL. Alleen als het quote-token een bekende
   dollarstablecoin is, mag het als dollarprijs worden geboekt — anders blijft `price_usd`
   leeg en wordt het quote-token vastgelegd. Een prijs in de verkeerde eenheid is erger dan
   geen prijs.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, runtime_checkable

from app.quantlab.feed import RawEvent, parse_payload
from app.quantlab.normalize import MarketTick, TickKind

logger = logging.getLogger("ganz.quantlab.sources.vybe")

SOURCE_NAME = "vybe"
STREAM_TRADES = "trades"
API_BASE = "https://api.vybenetwork.xyz"
TRADES_PATH = "/v4/trades"

# De stablecoins waarvan we aannemen dat ze een dollar waard zijn. Alleen bij deze
# quote-tokens wordt de prijs als dollarprijs geboekt.
#
# Dit is een aanname en geen meting: een stablecoin kan van de dollar afwijken, en bij
# precies de gebeurtenissen waar dit lab naar kijkt (paniek, dunne liquiditeit) wijkt hij
# het meest af. Voor H1 is dat te overzien omdat de uitkomst in R wordt gemeten en niet in
# dollars; het staat hier zodat de aanname zichtbaar is.
USD_QUOTE_MINTS: dict[str, str] = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
}


@runtime_checkable
class VybeClient(Protocol):
    """Alles wat trades kan opvragen. De adapter opent zelf geen verbinding.

    Zo is deze laag te testen zonder netwerk, en kan de sleutel buiten de adapter blijven.
    """

    async def get_trades(self, **params: Any) -> Sequence[dict[str, Any]]: ...


@dataclass(frozen=True)
class VybeTradesSource:
    """Trades van één markt (pool), als ruwe events.

    De pagina's worden doorgelopen tot er niets meer komt. Elke trade gaat onveranderd als
    JSON-tekst de ruwe opslag in: wat de bron stuurt is de waarheid, en het omzetten gebeurt
    daarna en apart.
    """

    client: VybeClient
    market_address: str
    time_start: int | None = None
    time_end: int | None = None
    page_size: int = 1000
    max_pages: int = 100

    name: str = SOURCE_NAME

    def streams(self) -> tuple[str, ...]:
        return (STREAM_TRADES,)

    async def events(self) -> AsyncIterator[RawEvent]:
        for pagina in range(self.max_pages):
            params: dict[str, Any] = {
                "marketAddress": self.market_address,
                "limit": self.page_size,
                "page": pagina,
                # Oudste eerst: de ruwe opslag is append-only en de ketting hangt aan de
                # volgorde waarin dingen binnenkomen. Nieuwste eerst zou betekenen dat het
                # corpus achterstevoren groeit.
                "sortByAsc": "blockTime",
            }
            if self.time_start is not None:
                params["timeStart"] = self.time_start
            if self.time_end is not None:
                params["timeEnd"] = self.time_end

            trades = await self.client.get_trades(**params)
            if not trades:
                return
            for trade in trades:
                yield RawEvent(
                    source=self.name,
                    stream=STREAM_TRADES,
                    # `separators` vast en `sort_keys` uit: we bewaren wat er kwam, niet een
                    # eigen herformattering. Zie de uitleg in feed.py.
                    payload_raw=json.dumps(trade, separators=(",", ":")),
                    received_at=_block_time(trade) or datetime.now(timezone.utc),
                )
            if len(trades) < self.page_size:
                return
        logger.warning(
            "Gestopt na %s pagina's voor markt %s; er kan meer zijn",
            self.max_pages,
            self.market_address,
        )


def _block_time(trade: dict[str, Any]) -> datetime | None:
    waarde = trade.get("blockTime")
    if waarde is None:
        return None
    try:
        return datetime.fromtimestamp(int(waarde), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _decimaal(waarde: object) -> Decimal | None:
    """Een getal uit de bron. Komt als tekst, en dat is goed nieuws.

    De bron stuurt prijzen en hoeveelheden als string. Die door een float halen zou precisie
    kosten bij precies de getallen waar het om gaat, dus hier gaat het rechtstreeks naar
    Decimal.
    """
    if waarde is None or waarde == "":
        return None
    try:
        return Decimal(str(waarde))
    except InvalidOperation:
        return None


def trade_order_key(trade: dict[str, Any]) -> tuple[int, int, int, int, int]:
    """De exacte ordening van een trade op de chain.

    `blockTime` is in seconden en dus te grof: binnen één seconde vallen meerdere trades.
    Deze sleutel ordent ze zoals ze werkelijk zijn gebeurd. De ordinalen staan op 255 als ze
    niet van toepassing zijn, wat ze netjes achteraan zet.
    """
    return (
        int(trade.get("slot") or 0),
        int(trade.get("txIndex") or 0),
        int(trade.get("ixOrdinal") or 0),
        int(trade.get("interIxOrdinal") or 0),
        int(trade.get("iixOrdinal") or 0),
    )


def trade_identity(trade: dict[str, Any]) -> str:
    """Een sleutel die één trade uniek aanwijst.

    `signature` is de transactie; de ordinalen wijzen de instructie binnen die transactie
    aan. Samen is dat uniek, en daarmee een betere dubbeldetectie dan een hash over de
    tekst: twee werkelijk verschillende events met toevallig dezelfde tekst zijn hiermee wél
    te onderscheiden.
    """
    slot, tx, ix, inter, iix = trade_order_key(trade)
    return f"{trade.get('signature', '')}:{tx}:{ix}:{inter}:{iix}"


class VybeTradeNormalizer:
    """Zet een Vybe-trade om in een tick.

    Wat deze normalizer níét doet: een prijs in dollars verzinnen. Is het quote-token geen
    bekende dollarstablecoin, dan blijft `price_usd` leeg. Een prijs in SOL die als
    dollarprijs wordt geboekt, maakt elk filter en elke uitkomst stilzwijgend verkeerd.

    Wat hij ook niet doet: liquiditeit invullen. Een trade zegt niets over de diepte van de
    pool, en H1 heeft die diepte nodig voor het filter "liquiditeit minstens 50x de
    positie". Die komt uit een ander endpoint; tot die er is, blijft het veld leeg en
    blokkeert het filter de instap. Dat is de juiste kant om fout te zitten.
    """

    def normalize(self, event: RawEvent) -> Sequence[MarketTick]:
        trade = parse_payload(event.payload_raw)

        ontbreekt = [
            veld
            for veld in ("marketAddress", "baseMintAddress", "price", "blockTime")
            if not trade.get(veld)
        ]
        if ontbreekt:
            raise ValueError(f"Trade mist {', '.join(ontbreekt)}")

        moment = _block_time(trade)
        if moment is None:
            raise ValueError("Trade heeft geen bruikbare blockTime")

        quote = str(trade.get("quoteMintAddress") or "")
        prijs = _decimaal(trade.get("price"))
        in_dollars = quote in USD_QUOTE_MINTS

        # Het verhandelde volume in de quote-eenheid. Alleen als die quote een dollar is,
        # is dit een dollarbedrag.
        quote_omvang = _decimaal(trade.get("quoteSize"))

        return (
            MarketTick(
                kind=TickKind.TRADE,
                venue=str(trade.get("programAddress") or "unknown"),
                chain="solana",
                pool_address=str(trade["marketAddress"]),
                token_address=str(trade["baseMintAddress"]),
                observed_at=moment,
                price_usd=prijs if in_dollars else None,
                # Liquiditeit komt niet uit een trade. Leeg laten is juister dan iets
                # aannemelijks invullen.
                liquidity_usd=None,
                volume_usd=quote_omvang if in_dollars else None,
                # Eén trade is geen venster. Nul betekent hier "dit is één gebeurtenis",
                # en de Screener telt ze zelf op tot vensters.
                volume_window_seconds=0,
                pool_created_at=None,
            ),
        )
