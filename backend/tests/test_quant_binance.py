"""De Binance-bulkadapter: echte marktdata, zonder sleutel.

`data.binance.vision` publiceert dag- en maandbestanden met candles en trades van elk paar.
Gratis, geen sleutel, geen rate limit — alleen een poort die open moet in de netwerkpolicy.

Alles hieronder is geverifieerd tegen Binance' **eigen** repo (`binance/binance-public-data`,
gelezen op 6 oktober 2026): de kolomindeling, de URL-opzet, de bestandsnamen en de
intervallen. Dat is een stap verder dan bij de Vybe-adapter, waar ik de vorm uit een
voorbeeldimplementatie moest halen.

De valkuil die hier als eerste in staat:

> **De tijdstempels van SPOT-data zijn vanaf 1 januari 2025 in MICROseconden.** Daarvoor in
> milliseconden.

Zonder die kennis komt een bestand uit 2024 in het jaar 1970 terecht, of een bestand uit
2025 in het jaar 56000 — en de datumvelden zien er dan nog steeds uit als getallen.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.quantlab.sources.binance import (
    BASE_URL,
    DAILY_INTERVALS,
    BinanceKlineNormalizer,
    BinanceZipSource,
    detect_time_unit,
    kline_url,
    to_datetime,
    trades_url,
)

# Een regel precies zoals Binance hem in de README van hun eigen repo laat zien: SPOT,
# januari 2025, dus in microseconden.
KLINE_2025 = [
    "1735689600000000", "4.15070000", "4.15870000", "4.15060000", "4.15540000",
    "539.23000000", "1735693199999999", "2240.39860900", "13", "401.82000000",
    "1669.98121300", "0",
]
# Dezelfde vorm maar van vóór 2025, dus in milliseconden.
KLINE_2024 = [
    "1704067200000", "42000.00", "42100.00", "41900.00", "42050.00",
    "12.5", "1704067259999", "525625.00", "340", "6.1", "256000.00", "0",
]


def zip_met(rijen: list[list[str]], naam: str = "BTCUSDT-1m-2025-01-01.csv") -> bytes:
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rijen)
    uit = io.BytesIO()
    with zipfile.ZipFile(uit, "w") as archief:
        archief.writestr(naam, buffer.getvalue())
    return uit.getvalue()


# --- De valkuil met de tijdstempels -------------------------------------------


def test_microseconden_en_milliseconden_worden_herkend() -> None:
    """De belangrijkste test in dit bestand.

    Zonder deze herkenning komt data uit 2024 in 1970 terecht of data uit 2025 in het jaar
    56000 — en in beide gevallen zijn het nog steeds getallen die er plausibel uitzien."""
    assert detect_time_unit(1735689600000000) == "us"
    assert detect_time_unit(1704067200000) == "ms"
    # De grens tussen de twee: een milliseconde-stempel is dertien cijfers, een
    # microseconde-stempel zestien.
    assert detect_time_unit(int("9" * 13)) == "ms"
    assert detect_time_unit(int("1" * 16)) == "us"


@pytest.mark.parametrize(
    "ruw, verwacht_jaar",
    [(1735689600000000, 2025), (1704067200000, 2024), (1498793709153, 2017)],
)
def test_elk_tijdstempel_komt_in_het_juiste_jaar_uit(ruw: int, verwacht_jaar: int) -> None:
    moment = to_datetime(ruw)
    assert moment.year == verwacht_jaar
    assert moment.tzinfo == timezone.utc


def test_een_onmogelijk_tijdstempel_wordt_geweigerd() -> None:
    """Niet gokken. Een getal dat in geen van beide eenheden een plausibel jaar oplevert,
    is een fout in het bestand en geen uitdaging om op te lossen."""
    for onmogelijk in (0, -1, 12345, 10**22):
        with pytest.raises(ValueError):
            to_datetime(onmogelijk)


# --- De URL-opzet -------------------------------------------------------------


def test_de_kline_url_volgt_de_opzet_van_binance() -> None:
    """Geverifieerd tegen python/utility.py en download-kline.py in hun eigen repo."""
    assert kline_url(symbol="BTCUSDT", interval="1s", date="2026-10-05", period="daily") == (
        f"{BASE_URL}data/spot/daily/klines/BTCUSDT/1s/BTCUSDT-1s-2026-10-05.zip"
    )
    assert kline_url(symbol="btcusdt", interval="1m", date="2026-09", period="monthly") == (
        f"{BASE_URL}data/spot/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2026-09.zip"
    )


def test_de_trades_url_heeft_geen_interval() -> None:
    assert trades_url(symbol="SOLUSDT", date="2026-10-05", period="daily") == (
        f"{BASE_URL}data/spot/daily/trades/SOLUSDT/SOLUSDT-trades-2026-10-05.zip"
    )


def test_er_hoort_een_checksum_bij() -> None:
    """Binance publiceert naast elk bestand een .CHECKSUM met de SHA-256 (geverifieerd in
    hun README). Die niet gebruiken zou betekenen dat een halve download stilzwijgend een
    corpus met een gat oplevert."""
    from app.quantlab.sources.binance import checksum_url

    url = kline_url(symbol="BTCUSDT", interval="1m", date="2026-10-05", period="daily")
    assert checksum_url(url) == (
        f"{BASE_URL}data/spot/daily/klines/BTCUSDT/1m/BTCUSDT-1m-2026-10-05.zip.CHECKSUM"
    )


def test_een_url_die_niet_kan_bestaan_wordt_geweigerd() -> None:
    """Een verkeerde URL geeft bij Binance een 404 en dus een gat in het corpus. Beter hier
    stuklopen dan daar stil niets opleveren."""
    # Van 1w bestaan geen dagbestanden.
    with pytest.raises(ValueError):
        kline_url(symbol="BTCUSDT", interval="1w", date="2026-10-05", period="daily")
    # Een maandbestand heeft een datum zonder dag.
    with pytest.raises(ValueError):
        kline_url(symbol="BTCUSDT", interval="1m", date="2026-10-05", period="monthly")
    # En een dagbestand heeft er juist wel een.
    with pytest.raises(ValueError):
        kline_url(symbol="BTCUSDT", interval="1m", date="2026-10", period="daily")
    with pytest.raises(ValueError):
        kline_url(symbol="BTCUSDT", interval="2s", date="2026-10-05", period="daily")


def test_seconde_candles_bestaan_en_dat_is_de_reden_voor_deze_bron() -> None:
    """Uit het fase 3-rapport: de latency-stresstest doet niets bij een cadans van twintig
    seconden, want 800 en 1600 milliseconden vallen op dezelfde volgende tick. Met
    secondecandles valt het verschil wél ergens."""
    assert "1s" in DAILY_INTERVALS


# --- Het lezen van een bestand ------------------------------------------------


async def test_een_zip_wordt_regel_voor_regel_uitgelezen(tmp_path) -> None:
    pad = tmp_path / "BTCUSDT-1m-2025-01-01.zip"
    pad.write_bytes(zip_met([KLINE_2025, KLINE_2025]))

    bron = BinanceZipSource(path=pad, symbol="BTCUSDT", interval="1m")
    events = [e async for e in bron.events()]
    assert len(events) == 2
    assert bron.name == "binance"
    # De ruwe regel blijft de regel van het bestand; het omzetten komt daarna.
    assert "4.15070000" in events[0].payload_raw


async def test_een_lege_zip_levert_niets_op(tmp_path) -> None:
    pad = tmp_path / "leeg.zip"
    pad.write_bytes(zip_met([]))
    bron = BinanceZipSource(path=pad, symbol="BTCUSDT", interval="1m")
    assert [e async for e in bron.events()] == []


async def test_een_regel_met_te_weinig_kolommen_wordt_niet_aangevuld(tmp_path) -> None:
    pad = tmp_path / "stuk.zip"
    pad.write_bytes(zip_met([KLINE_2025[:5]]))
    bron = BinanceZipSource(path=pad, symbol="BTCUSDT", interval="1m")
    events = [e async for e in bron.events()]
    # Het event wordt wél bewaard — de ruwe opslag is append-only — maar het normaliseren
    # mislukt en dat wordt geteld.
    assert len(events) == 1
    with pytest.raises(ValueError):
        BinanceKlineNormalizer(symbol="BTCUSDT", interval="1m").normalize(events[0])


# --- Normaliseren -------------------------------------------------------------


def _event(rij: list[str], **kwargs):
    from app.quantlab.feed import RawEvent
    import json

    return RawEvent(
        source="binance",
        stream=kwargs.get("stream", "klines"),
        payload_raw=json.dumps(rij),
        received_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
    )


def test_een_candle_wordt_een_tick_met_de_slotkoers() -> None:
    tick = BinanceKlineNormalizer(symbol="BTCUSDT", interval="1m").normalize(
        _event(KLINE_2025)
    )[0]
    assert tick.pool_address == "BTCUSDT"
    assert tick.chain == "binance-spot"
    # De SLOTtijd, niet de openingstijd. Dit stond eerst andersom in deze test en dat was
    # fout: de slotkoers was pas waar aan het eind van het interval. Zou de tick op de
    # openingstijd staan, dan ziet de engine bij minuutcandles zestig seconden lang een
    # prijs die nog niet bestaat — gratis vooruitkijken, en precies de fout die een
    # backtest mooi maakt en waardeloos.
    assert tick.observed_at == datetime(2025, 1, 1, 0, 59, 59, 999999, tzinfo=timezone.utc)
    # De slotkoers en niet de openingskoers: dat is de prijs die aan het eind van het
    # interval gold, en dus de prijs waarop je op dat moment had kunnen handelen.
    assert tick.price_usd == Decimal("4.15540000")
    # Het volume in quote-eenheid (USDT), want dat is wat "liquiditeit in dollars" betekent.
    assert tick.volume_usd == Decimal("2240.39860900")
    assert tick.volume_window_seconds == 60


@pytest.mark.parametrize(
    "interval, seconden",
    [("1s", 1), ("1m", 60), ("3m", 180), ("1h", 3600), ("4h", 14400), ("1d", 86400)],
)
def test_het_venster_volgt_uit_het_interval(interval: str, seconden: int) -> None:
    tick = BinanceKlineNormalizer(symbol="BTCUSDT", interval=interval).normalize(
        _event(KLINE_2025)
    )[0]
    assert tick.volume_window_seconds == seconden


def test_liquiditeit_blijft_leeg_want_een_candle_zegt_er_niets_over() -> None:
    """Net als bij de Vybe-adapter: volume is niet hetzelfde als diepte. Het filter
    "liquiditeit minstens 50x de positie" heeft orderboekdiepte nodig, en die staat niet in
    een candle."""
    tick = BinanceKlineNormalizer(symbol="BTCUSDT", interval="1m").normalize(
        _event(KLINE_2025)
    )[0]
    assert tick.liquidity_usd is None


def test_een_candle_zonder_handel_wordt_gemeld_en_niet_stil_overgeslagen() -> None:
    leeg = [
        "1735689600000000", "4.15", "4.15", "4.15", "4.15", "0",
        "1735693199999999", "0", "0", "0", "0", "0",
    ]
    tick = BinanceKlineNormalizer(symbol="BTCUSDT", interval="1m").normalize(_event(leeg))[0]
    # De prijs staat er nog (de markt had een koers), het volume is nul.
    assert tick.price_usd == Decimal("4.15")
    assert tick.volume_usd == Decimal("0")


def test_de_prijzen_gaan_niet_door_een_float() -> None:
    """Binance geeft prijzen als tekst met acht decimalen. Door een float halen kost precisie
    bij precies de getallen waar het om gaat."""
    tick = BinanceKlineNormalizer(symbol="BTCUSDT", interval="1m").normalize(
        _event(KLINE_2025)
    )[0]
    assert tick.price_usd == Decimal("4.15540000")
    assert str(tick.price_usd) == "4.15540000"


def test_een_getal_in_de_ruwe_opslag_gaat_ook_niet_door_een_float() -> None:
    """Onze eigen bron schrijft de velden als tekst weg. Staat er ooit een getal in plaats
    van tekst, dan mag de waarde er nog steeds niet door een float heen."""
    import json

    from app.quantlab.feed import RawEvent

    # Een prijs met meer cijfers dan een float kan dragen; bij memecoins zijn dat precies
    # de prijzen. Met een kort getal als 4,1554 valt dit niet op: dat komt uit een float
    # nog hetzelfde terug, en dan bewijst de test niets.
    precies = "0.000000123456789012345678"
    rij = list(KLINE_2025)
    rij[4] = precies
    ruw = json.dumps(rij).replace(f'"{precies}"', precies)
    event = RawEvent(
        source="binance",
        stream="klines",
        payload_raw=ruw,
        received_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
    )
    tick = BinanceKlineNormalizer(symbol="BTCUSDT", interval="1m").normalize(event)[0]
    assert tick.price_usd == Decimal(precies)


def test_een_bestand_uit_2024_en_een_uit_2025_komen_beide_goed_uit() -> None:
    """De tijdstempelval, nu via de normalizer."""
    normalizer = BinanceKlineNormalizer(symbol="BTCUSDT", interval="1m")
    oud = normalizer.normalize(_event(KLINE_2024))[0]
    nieuw = normalizer.normalize(_event(KLINE_2025))[0]
    assert oud.observed_at.year == 2024
    assert nieuw.observed_at.year == 2025


def test_een_candle_die_sluit_voor_hij_opent_wordt_geweigerd() -> None:
    """Twee tijdstempels die niet bij elkaar passen, betekent een beschadigde regel of de
    verkeerde eenheid. Dan is er niets te normaliseren."""
    stuk = list(KLINE_2025)
    stuk[6] = stuk[0]  # sluit op hetzelfde moment als het opent
    with pytest.raises(ValueError):
        BinanceKlineNormalizer(symbol="BTCUSDT", interval="1m").normalize(_event(stuk))


def test_een_maandcandle_heeft_geen_vast_venster() -> None:
    """Een kalendermaand is 28 tot 31 dagen. Een getal verzinnen zou elk volumevenster van
    een maandcandle net verkeerd maken."""
    tick = BinanceKlineNormalizer(symbol="BTCUSDT", interval="1mo").normalize(
        _event(KLINE_2025)
    )[0]
    assert tick.volume_window_seconds is None


def test_een_paar_tegen_btc_levert_geen_dollarprijs_op() -> None:
    """Dezelfde regel als bij Vybe: `ETHBTC` staat in BTC, niet in dollars. Een prijs in de
    verkeerde eenheid maakt elk filter en elke uitkomst stilzwijgend verkeerd."""
    tick = BinanceKlineNormalizer(symbol="ETHBTC", interval="1m").normalize(
        _event(KLINE_2025)
    )[0]
    assert tick.price_usd is None
    assert tick.volume_usd is None
    # De prijs is er wel; hij is alleen niet in dollars, en dat staat in de tick.
    assert tick.pool_address == "ETHBTC"


@pytest.mark.parametrize(
    "paar, basis, quote",
    [
        ("BTCUSDT", "BTC", "USDT"),
        ("ETHUSD", "ETH", "USD"),
        ("ETHBTC", "ETH", "BTC"),
        ("RAREPAIR", "RAREPAIR", ""),
    ],
)
def test_het_paar_wordt_gesplitst_en_niet_gegokt(paar: str, basis: str, quote: str) -> None:
    """`USDT` moet vóór `USD` gematcht worden, anders wordt BTCUSDT een paar tegen USD met
    een basis van `BTCUST`. En een paar dat niet te splitsen is, wordt niet gesplitst."""
    from app.quantlab.sources.binance import split_symbol

    assert split_symbol(paar) == (basis, quote)


# --- Trades: de vorm die de latency-stresstest nodig heeft ---------------------

# tradeId, price, qty, quoteQty, time, isBuyerMaker, isBestMatch
TRADE_2025 = ["194754841", "4.15540000", "1.20000000", "4.98648000", "1735689600123456", "True", "True"]


def test_een_trade_wordt_een_tick_met_zijn_eigen_tijdstempel() -> None:
    """Uit het fase 3-rapport: met een cadans van twintig seconden doet de latency-stresstest
    niets, want 800 en 1600 milliseconden vallen op dezelfde volgende tick. Trades hebben
    elk hun eigen tijdstempel, tot op de microseconde."""
    from app.quantlab.sources.binance import BinanceTradesNormalizer

    tick = BinanceTradesNormalizer(symbol="SOLUSDT").normalize(
        _event(TRADE_2025, stream="trades")
    )[0]
    assert tick.observed_at == datetime(2025, 1, 1, 0, 0, 0, 123456, tzinfo=timezone.utc)
    assert tick.price_usd == Decimal("4.15540000")
    assert tick.volume_usd == Decimal("4.98648000")
    # Eén trade is geen venster.
    assert tick.volume_window_seconds == 0
    assert tick.liquidity_usd is None


def test_een_halve_traderegel_wordt_niet_aangevuld() -> None:
    from app.quantlab.sources.binance import BinanceTradesNormalizer

    with pytest.raises(ValueError):
        BinanceTradesNormalizer(symbol="SOLUSDT").normalize(
            _event(TRADE_2025[:3], stream="trades")
        )


# --- Door de gewone opslag heen ------------------------------------------------


async def test_de_bron_gaat_door_de_ketting_en_de_replay_heen(session, tmp_path) -> None:
    """De adapter is een gewone bron: de hashketting, de dubbeldetectie, de
    datakwaliteitscontrole en de replay uit fase 2 werken er zonder aanpassing op."""
    from app.models.quantlab import QuantMarketTick, QuantRawEvent
    from app.quantlab.normalize import NORMALIZERS
    from app.services import quant_data_service
    from sqlalchemy import select

    # Zestig candles van een minuut, elk met een andere tijd en prijs.
    rijen = []
    basis = 1735689600000000
    for n in range(60):
        prijs = f"{4.15 + n * 0.01:.8f}"
        rijen.append([
            str(basis + n * 60_000_000), prijs, prijs, prijs, prijs, "10.0",
            str(basis + (n + 1) * 60_000_000 - 1), "41.5", "5", "5.0", "20.0", "0",
        ])
    pad = tmp_path / "BTCUSDT-1m-2025-01-01.zip"
    pad.write_bytes(zip_met(rijen))

    NORMALIZERS["binance"] = BinanceKlineNormalizer(symbol="BTCUSDT", interval="1m")
    try:
        bron = BinanceZipSource(path=pad, symbol="BTCUSDT", interval="1m")
        opname = await quant_data_service.record(session, source=bron)
        await session.commit()

        assert opname.events == 60
        assert opname.ticks == 60
        assert opname.parse_failures == 0
        assert (await quant_data_service.verify_chain(session)).ok is True

        rapport = await quant_data_service.quality(
            session, now=datetime(2025, 1, 2, tzinfo=timezone.utc)
        )
        # Geen synthetische events: dit is echte-data-vorm.
        assert rapport.synthetic_events == 0
        assert "synthetisch" not in rapport.explanation.lower()

        ticks = (await session.execute(select(QuantMarketTick))).scalars().all()
        assert all(t.chain == "binance-spot" for t in ticks)
        rauw = (await session.execute(select(QuantRawEvent))).scalars().all()
        assert all(r.source == "binance" for r in rauw)

        # En de replay geeft hetzelfde resultaat.
        afdruk = await quant_data_service.normalized_digest(session)
        herhaling = await quant_data_service.replay(session)
        await session.commit()
        assert herhaling.digest == afdruk
    finally:
        NORMALIZERS.pop("binance", None)


# --- Het downloadscript -------------------------------------------------------


def test_de_sha256_wordt_uit_het_checksum_bestand_gehaald() -> None:
    """Binance publiceert de hash in de vorm van `sha256sum -c`. We zoeken het hex-woord in
    plaats van op kolom te splitsen: een extra `*` of een andere scheiding mag de controle
    niet stilletjes overslaan."""
    from scripts.quant_binance import _verwachte_hash

    hash_ = "a" * 64
    assert _verwachte_hash(f"{hash_}  BTCUSDT-1m-2025-01-01.zip\n") == hash_
    assert _verwachte_hash(f"{hash_} *BTCUSDT-1m-2025-01-01.zip\n") == hash_
    with pytest.raises(ValueError):
        _verwachte_hash("geen hash hier\n")


def test_de_datumreeks_loopt_over_maand_en_jaargrenzen() -> None:
    """Een reeks die bij een maandgrens stopt, levert een corpus met een gat op precies de
    plek waar niemand kijkt."""
    from scripts.quant_binance import _datums

    assert _datums("2026-01-30", "2026-02-02", "daily") == [
        "2026-01-30", "2026-01-31", "2026-02-01", "2026-02-02",
    ]
    assert _datums("2025-12-01", "2026-02-01", "monthly") == ["2025-12", "2026-01", "2026-02"]
    # Februari 2024 had 29 dagen; de maandloper mag daar niet op stuklopen.
    assert _datums("2024-02-28", "2024-03-01", "daily") == [
        "2024-02-28", "2024-02-29", "2024-03-01",
    ]


async def test_de_herkomst_van_een_bestand_wordt_vastgelegd(session, tmp_path) -> None:
    """Binance zegt zelf dat archiefbestanden later vervangen kunnen worden (twee keer
    gebeurd). Zonder de SHA-256 van het bestand in de run is achteraf niet na te gaan op
    welke data een resultaat is gemeten."""
    from app.models.quantlab import QuantIngestRun
    from app.quantlab.normalize import NORMALIZERS
    from app.services import quant_data_service
    from sqlalchemy import select

    pad = tmp_path / "BTCUSDT-1m-2025-01-01.zip"
    pad.write_bytes(zip_met([KLINE_2025]))

    NORMALIZERS["binance"] = BinanceKlineNormalizer(symbol="BTCUSDT", interval="1m")
    try:
        bron = BinanceZipSource(path=pad, symbol="BTCUSDT", interval="1m")
        await quant_data_service.record(session, source=bron, note=f"{pad.name} sha256=abc123")
        await session.commit()
        run = (await session.execute(select(QuantIngestRun))).scalars().one()
        assert run.note is not None
        assert "BTCUSDT-1m-2025-01-01.zip" in run.note
        assert "sha256=abc123" in run.note
    finally:
        NORMALIZERS.pop("binance", None)
