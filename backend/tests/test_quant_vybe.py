"""De eerste adapter naar een echte bron (Vybe Network).

Belangrijk voorbehoud: deze tests meten of de adapter zich houdt aan de vorm die in de
referentie-implementatie van de leverancier staat. Ze bewijzen **niet** dat de live API die
vorm stuurt — die is vanuit deze omgeving onbereikbaar. Het verschil met gokken is groot;
het verschil met verifiëren ook.

Drie valkuilen zitten hier als test in, en alle drie zijn gevonden door de broncode van de
leverancier te lezen in plaats van de documentatie:

1. de klok van een trade is de slot en niet `blockTime` (seconden is te grof);
2. `signature` plus de ordinalen wijzen een trade uniek aan;
3. `price` is in het quote-token, niet in dollars.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.quantlab.feed import RawEvent
from app.quantlab.normalize import TickKind
from app.quantlab.sources.vybe import (
    SOURCE_NAME,
    USD_QUOTE_MINTS,
    VybeTradeNormalizer,
    VybeTradesSource,
    trade_identity,
    trade_order_key,
)

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WSOL = "So11111111111111111111111111111111111111112"

# Een trade in de vorm zoals die in src/types/api.ts van de leverancier staat.
TRADE = {
    "authorityAddress": "auth1",
    "baseMintAddress": "TokenMint111",
    "baseSize": "1234.5678",
    "blockTime": 1793000000,
    "fee": "0.000005",
    "feePayerAddress": "payer1",
    "iixOrdinal": 255,
    "interIxOrdinal": 255,
    "ixOrdinal": 3,
    "marketAddress": "Pool111",
    "price": "0.000123456789",
    "programAddress": "RaydiumProgram11",
    "quoteMintAddress": USDC,
    "quoteSize": "152.40",
    "signature": "sig-abc",
    "slot": 310_000_000,
    "txIndex": 42,
}


def event(trade: dict) -> RawEvent:
    # `blockTime` kan ontbreken: dat is precies een van de gevallen die getest wordt, en de
    # ontvangsttijd is onze eigen klok en niet die van de bron.
    moment = trade.get("blockTime")
    return RawEvent(
        source=SOURCE_NAME,
        stream="trades",
        payload_raw=json.dumps(trade, separators=(",", ":")),
        received_at=(
            datetime.fromtimestamp(moment, tz=timezone.utc)
            if moment is not None
            else datetime.now(timezone.utc)
        ),
    )


class NamaakClient:
    """Geeft pagina's trades terug zonder netwerk."""

    def __init__(self, *paginas: list[dict]) -> None:
        self._paginas = list(paginas)
        self.aanroepen: list[dict] = []

    async def get_trades(self, **params):
        self.aanroepen.append(params)
        index = params.get("page", 0)
        return self._paginas[index] if index < len(self._paginas) else []


# --- De ordening op de chain --------------------------------------------------


def test_de_klok_van_een_trade_is_de_slot_en_niet_de_tijd() -> None:
    """`blockTime` is in seconden, en binnen één seconde vallen meerdere trades.

    Zou de volgorde op `blockTime` gaan, dan is de ordening binnen een seconde willekeurig
    — en dat is precies de schaal waarop een sniper werkt."""
    eerste = {**TRADE, "slot": 100, "txIndex": 1, "blockTime": 1793000000}
    tweede = {**TRADE, "slot": 100, "txIndex": 2, "blockTime": 1793000000}
    derde = {**TRADE, "slot": 101, "txIndex": 0, "blockTime": 1793000000}

    assert eerste["blockTime"] == tweede["blockTime"] == derde["blockTime"]
    sleutels = [trade_order_key(t) for t in (eerste, tweede, derde)]
    assert sleutels == sorted(sleutels)
    assert len(set(sleutels)) == 3


def test_de_ordinalen_ordenen_binnen_een_transactie() -> None:
    basis = {**TRADE, "slot": 100, "txIndex": 1}
    a = {**basis, "ixOrdinal": 1, "interIxOrdinal": 255, "iixOrdinal": 255}
    b = {**basis, "ixOrdinal": 1, "interIxOrdinal": 0, "iixOrdinal": 255}
    assert trade_order_key(b) < trade_order_key(a)


def test_een_trade_is_uniek_aan_te_wijzen() -> None:
    """Beter dan een hash over de tekst: twee werkelijk verschillende events met toevallig
    dezelfde tekst zijn hiermee wél te onderscheiden."""
    a = {**TRADE, "signature": "sig-a", "ixOrdinal": 1}
    b = {**TRADE, "signature": "sig-a", "ixOrdinal": 2}
    c = {**TRADE, "signature": "sig-b", "ixOrdinal": 1}
    sleutels = {trade_identity(t) for t in (a, b, c)}
    assert len(sleutels) == 3
    assert trade_identity(a) == trade_identity({**a})


# --- De prijs is niet in dollars ---------------------------------------------


def test_een_prijs_tegen_usdc_is_een_dollarprijs() -> None:
    ticks = VybeTradeNormalizer().normalize(event(TRADE))
    assert len(ticks) == 1
    tick = ticks[0]
    assert tick.kind is TickKind.TRADE
    assert tick.price_usd == Decimal("0.000123456789")
    assert tick.volume_usd == Decimal("152.40")


def test_een_prijs_tegen_sol_wordt_niet_als_dollarprijs_geboekt() -> None:
    """De val waar ik bijna in liep. `price` is de prijs in het quote-token. Bij een pool
    tegen SOL is dat een prijs in SOL, en die als dollarprijs boeken maakt elk filter en
    elke uitkomst stilzwijgend verkeerd."""
    tegen_sol = {**TRADE, "quoteMintAddress": WSOL}
    tick = VybeTradeNormalizer().normalize(event(tegen_sol))[0]
    assert tick.price_usd is None
    assert tick.volume_usd is None
    # De tick bestaat wel: we weten dát er gehandeld is, alleen niet tegen welke dollarprijs.
    assert tick.pool_address == "Pool111"
    assert tick.token_address == "TokenMint111"


def test_de_lijst_met_dollarstablecoins_is_expliciet() -> None:
    """Geen patroonherkenning op symbolen: een token dat zich "USDX" noemt is daarmee geen
    dollar. Alleen wat hier staat, geldt als dollar."""
    assert USDC in USD_QUOTE_MINTS
    assert WSOL not in USD_QUOTE_MINTS
    assert all(len(mint) > 30 for mint in USD_QUOTE_MINTS), "mints, geen symbolen"


# --- Wat een trade niet weet --------------------------------------------------


def test_liquiditeit_blijft_leeg_want_een_trade_zegt_er_niets_over() -> None:
    """H1 heeft pooldiepte nodig voor "liquiditeit minstens 50x de positie". Die komt uit
    een ander endpoint. Leeg laten betekent dat het filter de instap blokkeert — en dat is
    de juiste kant om fout te zitten."""
    tick = VybeTradeNormalizer().normalize(event(TRADE))[0]
    assert tick.liquidity_usd is None


def test_een_losse_trade_is_geen_venster() -> None:
    tick = VybeTradeNormalizer().normalize(event(TRADE))[0]
    assert tick.volume_window_seconds == 0


@pytest.mark.parametrize("veld", ["marketAddress", "baseMintAddress", "price", "blockTime"])
def test_een_trade_zonder_verplicht_veld_wordt_geweigerd(veld: str) -> None:
    """Niet aanvullen met een aanname: een event dat niet te lezen is, wordt geteld en
    blijft ruw bewaard (zie fase 2)."""
    stuk = {**TRADE}
    del stuk[veld]
    with pytest.raises(ValueError, match=veld):
        VybeTradeNormalizer().normalize(event(stuk))


def test_een_onleesbare_prijs_wordt_leeg_en_niet_nul() -> None:
    raar = {**TRADE, "price": "niet-een-getal"}
    tick = VybeTradeNormalizer().normalize(event(raar))[0]
    assert tick.price_usd is None, "nul zou betekenen dat het token niets waard is"


# --- De bron ------------------------------------------------------------------


async def test_de_bron_loopt_de_paginas_door() -> None:
    client = NamaakClient([TRADE] * 1000, [TRADE] * 3)
    bron = VybeTradesSource(client=client, market_address="Pool111", page_size=1000)
    events = [e async for e in bron.events()]
    assert len(events) == 1003
    assert [a["page"] for a in client.aanroepen] == [0, 1]


async def test_de_bron_stopt_bij_een_lege_pagina() -> None:
    client = NamaakClient([])
    bron = VybeTradesSource(client=client, market_address="Pool111")
    assert [e async for e in bron.events()] == []


async def test_de_bron_vraagt_oudste_eerst() -> None:
    """De ruwe opslag is append-only en de hashketting hangt aan de volgorde van binnenkomst.
    Nieuwste eerst zou betekenen dat het corpus achterstevoren groeit."""
    client = NamaakClient([TRADE])
    bron = VybeTradesSource(client=client, market_address="Pool111")
    [e async for e in bron.events()]
    assert client.aanroepen[0]["sortByAsc"] == "blockTime"


async def test_de_bron_filtert_op_markt_en_niet_op_token() -> None:
    """Een token kan in meerdere pools handelen. H1 kijkt naar een pool, dus de markt is
    het filter — en volgens de documentatie van de leverancier negeert de API de
    mint-filters zodra `marketAddress` is gezet."""
    client = NamaakClient([TRADE])
    bron = VybeTradesSource(client=client, market_address="Pool111")
    [e async for e in bron.events()]
    assert client.aanroepen[0]["marketAddress"] == "Pool111"
    assert "baseMintAddress" not in client.aanroepen[0]


async def test_de_ruwe_tekst_blijft_de_tekst_van_de_bron() -> None:
    client = NamaakClient([TRADE])
    bron = VybeTradesSource(client=client, market_address="Pool111")
    events = [e async for e in bron.events()]
    # Dezelfde sleutels, en de prijs nog steeds als tekst zodat er geen precisie weg is.
    heringelezen = json.loads(events[0].payload_raw)
    assert heringelezen == TRADE
    assert isinstance(heringelezen["price"], str)


async def test_de_bron_gaat_door_de_normale_opslag_heen(session) -> None:
    """De adapter is een gewone bron: de ketting, de dubbeldetectie en de normalisatie uit
    fase 2 werken er zonder aanpassing op."""
    from app.models.quantlab import QuantMarketTick, QuantRawEvent
    from app.quantlab.normalize import NORMALIZERS
    from app.services import quant_data_service
    from sqlalchemy import select

    NORMALIZERS[SOURCE_NAME] = VybeTradeNormalizer()
    try:
        trades = [
            {**TRADE, "signature": f"sig-{n}", "slot": 310_000_000 + n, "txIndex": n}
            for n in range(5)
        ]
        bron = VybeTradesSource(client=NamaakClient(trades), market_address="Pool111")
        opname = await quant_data_service.record(session, source=bron)
        await session.commit()

        assert opname.events == 5
        assert opname.ticks == 5
        assert opname.parse_failures == 0
        assert (await quant_data_service.verify_chain(session)).ok is True

        rijen = (await session.execute(select(QuantRawEvent))).scalars().all()
        assert all(r.source == SOURCE_NAME for r in rijen)
        ticks = (await session.execute(select(QuantMarketTick))).scalars().all()
        assert all(t.chain == "solana" for t in ticks)
        assert all(t.pool_address == "Pool111" for t in ticks)
    finally:
        NORMALIZERS.pop(SOURCE_NAME, None)
