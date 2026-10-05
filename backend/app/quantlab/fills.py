"""Het fill-model (sectie 10): wat een papieren order werkelijk zou hebben gekost.

Memecoin-paper-trading is berucht om onrealistische fills. De fout is altijd dezelfde: je
rekent met de prijs op het moment van het signaal. Geen vertraging, geen slippage, geen
fee, geen mislukte transacties — en dan komt er een curve uit die niets met de werkelijkheid
te maken heeft. Dit bestand modelleert alle vijf.

De uitkomst is met opzet uitgesplitst in vier stukken, omdat "de fill was slechter" een
nutteloze mededeling is als je niet weet waardoor:

- `expected_price`  de prijs op het moment van het signaal
- `market_price`    de prijs na de vertraging — het verschil hiermee is wat de klok kostte
- `fill_price`      de prijs die je werkelijk kreeg — het verschil hiermee is slippage
- `fee_usd`         de tip en de netwerkkosten, die je ook betaalt als het mislukt

**Geen van de kostenparameters is geverifieerd.** Ze staan in de hypothese-bestanden met
hun herkomst erbij, en de stresstest is er juist om te laten zien hoe gevoelig een resultaat
voor die getallen is. Een edge die 2x slippage niet overleeft, is geen edge.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from statistics import NormalDist

PRICE_SCALE = Decimal("0.000000000001")
MONEY_SCALE = Decimal("0.000001")
UNIT_SCALE = Decimal("0.00000001")
BPS = Decimal("10000")

# Het 95e percentiel van een standaardnormale verdeling. Hiermee wordt de spreiding van de
# vertraging zo gezet dat p50 en p95 uit de config er ook echt uitkomen.
_Z95 = NormalDist().inv_cdf(0.95)
_NORMAL = NormalDist()


class FillKind(StrEnum):
    ENTRY = "entry"
    EXIT = "exit"


@dataclass(frozen=True)
class StressProfile:
    """Hoeveel zwaarder de werkelijkheid mag zijn dan het model denkt.

    De faalkans staat er met opzet niet in: zou de stresstest die ook opschroeven, dan weet
    je bij een slechter resultaat niet meer waar het vandaan komt.
    """

    slippage_multiplier: Decimal = Decimal("1")
    latency_multiplier: Decimal = Decimal("1")


# De vier varianten waarin elk resultaat wordt gerapporteerd (sectie 10).
STRESS_PROFILES: dict[str, StressProfile] = {
    "base": StressProfile(Decimal("1"), Decimal("1")),
    "slippage_2x": StressProfile(Decimal("2"), Decimal("1")),
    "latency_2x": StressProfile(Decimal("1"), Decimal("2")),
    "both_2x": StressProfile(Decimal("2"), Decimal("2")),
}


@dataclass(frozen=True)
class PoolDepth:
    """De twee kanten van een constant-product pool, plus de spotprijs."""

    token_reserve: Decimal
    quote_reserve: Decimal
    spot_price: Decimal

    @property
    def liquidity_usd(self) -> Decimal:
        return self.quote_reserve * 2


def pool_depth_from_liquidity(*, liquidity_usd: Decimal, spot_price: Decimal) -> PoolDepth:
    """Leid de diepte af uit de gerapporteerde liquiditeit.

    Een constant-product pool heeft de helft van zijn waarde aan elke kant; dat is geen
    aanname maar hoe zo'n pool werkt. De gerapporteerde liquiditeit is de totale waarde,
    dus de quote-kant is de helft, en de token-kant volgt uit de spotprijs.

    Dit is wat er mogelijk is met de gegevens die een feed geeft. Heb je de werkelijke
    reserves, gebruik die dan: dan is dit een afleiding minder.
    """
    if spot_price <= 0:
        raise ValueError("Zonder een positieve spotprijs is er geen diepte af te leiden.")
    quote = liquidity_usd / 2
    return PoolDepth(
        token_reserve=quote / spot_price, quote_reserve=quote, spot_price=spot_price
    )


def price_impact(
    pool: PoolDepth,
    *,
    quote_usd: Decimal | None = None,
    units: Decimal | None = None,
    swap_fee_bps: int,
) -> Decimal:
    """Hoeveel slechter je prijs is dan de spot, als deel van 1.

    Altijd positief of nul: een order die jou een betere prijs geeft dan de spot, bestaat
    niet in een AMM. De fee zit erin, want die betaal je over je inleg en niet apart.
    """
    if pool.token_reserve <= 0 or pool.quote_reserve <= 0:
        raise ValueError("Een lege pool laat geen order toe.")
    fee = Decimal(swap_fee_bps) / BPS

    if quote_usd is not None:
        if quote_usd <= 0:
            return Decimal("0")
        inleg = quote_usd * (Decimal("1") - fee)
        gekregen = pool.token_reserve * inleg / (pool.quote_reserve + inleg)
        if gekregen <= 0:
            raise ValueError("De pool is te klein voor deze order.")
        werkelijke_prijs = quote_usd / gekregen
        return werkelijke_prijs / pool.spot_price - Decimal("1")

    if units is None or units <= 0:
        return Decimal("0")
    inleg = units * (Decimal("1") - fee)
    opbrengst = pool.quote_reserve * inleg / (pool.token_reserve + inleg)
    werkelijke_prijs = opbrengst / units
    return Decimal("1") - werkelijke_prijs / pool.spot_price


def latency_for_quantile(quantile: float, *, p50_ms: int, p95_ms: int) -> float:
    """De vertraging bij een bepaald percentiel, in milliseconden.

    Lognormaal met mediaan `p50_ms` en 95e percentiel `p95_ms`. Die vorm is gekozen omdat
    vertraging niet negatief kan zijn en een lange staart heeft: de meeste transacties zijn
    snel, en af en toe duurt er één vijf keer zo lang. Een normale verdeling zou negatieve
    vertragingen opleveren en de staart missen.
    """
    if p95_ms <= p50_ms:
        return float(p50_ms)
    sigma = (Decimal(p95_ms) / Decimal(p50_ms)).ln() / Decimal(str(_Z95))
    z = _NORMAL.inv_cdf(min(max(quantile, 1e-9), 1 - 1e-9))
    return float(Decimal(p50_ms) * (sigma * Decimal(str(z))).exp())


@dataclass(frozen=True)
class FillRequest:
    kind: FillKind
    requested_at: datetime
    expected_price: Decimal
    pool: PoolDepth
    quote_usd: Decimal | None = None
    units: Decimal | None = None


@dataclass(frozen=True)
class FillOutcome:
    kind: FillKind
    filled: bool
    requested_at: datetime
    filled_at: datetime
    latency_ms: float
    expected_price: Decimal
    market_price: Decimal | None
    fill_price: Decimal
    units: Decimal
    quote_usd: Decimal
    slippage_usd: Decimal
    latency_cost_usd: Decimal
    fee_usd: Decimal
    exit_haircut_applied: bool
    failure_reason: str | None


@dataclass(frozen=True)
class FillModel:
    """Het kostenmodel van één hypothese. Alle waarden komen uit het hypothese-bestand."""

    swap_fee_bps: int
    priority_fee_usd: Decimal
    network_fee_usd: Decimal
    failure_probability: float
    latency_p50_ms: int
    latency_p95_ms: int
    exit_haircut_bps: int
    exit_haircut_above_pool_share: Decimal
    stress: StressProfile = field(default_factory=StressProfile)

    @property
    def transaction_fee_usd(self) -> Decimal:
        """De tip plus de netwerkkosten. De swap-fee zit níét hierin: die zit in de
        fill-prijs, net als in de werkelijkheid, en zou hier dubbel geteld worden."""
        return self.priority_fee_usd + self.network_fee_usd

    def fill(
        self,
        request: FillRequest,
        *,
        seed: int,
        price_after: Callable[[datetime], Decimal | None],
    ) -> FillOutcome:
        """Simuleer één order.

        `price_after` geeft de marktprijs op een moment terug, of `None` als de data daar
        stopt. Dat laatste is geen marktgebeurtenis maar een gat in onze gegevens, en wordt
        daarom apart geteld en zonder kosten geboekt.

        De twee toevalsgetallen worden altijd in dezelfde volgorde getrokken, ook als ze
        niet allebei nodig zijn. Dat is wat een stresstest geldig maakt: bij hetzelfde zaad
        krijg je exact dezelfde transactie, en is het enige verschil de stress.
        """
        toeval = random.Random(seed)
        mislukt = toeval.random() < self.failure_probability
        kwantiel = toeval.random()

        vertraging = (
            latency_for_quantile(
                kwantiel, p50_ms=self.latency_p50_ms, p95_ms=self.latency_p95_ms
            )
            * float(self.stress.latency_multiplier)
        )
        moment = request.requested_at + timedelta(milliseconds=vertraging)
        markt = price_after(moment)

        if markt is None or markt <= 0:
            return self._niets(
                request, moment, vertraging, "no_price_after_latency", fee=Decimal("0")
            )
        if mislukt:
            return self._niets(
                request,
                moment,
                vertraging,
                "transaction_failed",
                fee=self.transaction_fee_usd,
                markt=markt,
            )

        # De diepte opnieuw afleiden op de prijs van dít moment. Alleen de spotprijs
        # bijwerken en de reserves laten staan, zou een pool opleveren die intern niet
        # klopt: de reserves zouden nog de oude prijs vertellen, en dan rekent de impact
        # de prijsbeweging weg in plaats van erbij op.
        pool = pool_depth_from_liquidity(
            liquidity_usd=request.pool.liquidity_usd, spot_price=markt
        )

        if request.kind is FillKind.ENTRY:
            return self._instap(request, pool, moment, vertraging, markt)
        return self._uitstap(request, pool, moment, vertraging, markt)

    def mark_to_market(
        self,
        *,
        units: Decimal,
        price: Decimal,
        pool: PoolDepth,
        moment: datetime,
        reason: str,
    ) -> FillOutcome:
        """Waardeer een positie op een bekende prijs, zonder een transactie te simuleren.

        Nodig op twee momenten waarop er geen toekomst meer is om op te vullen: als het
        corpus ophoudt terwijl er nog een positie open staat, en als een pool stopt met
        ticken. In beide gevallen is er geen "prijs na de vertraging" — die prijs bestaat
        niet in de gegevens.

        Daarom geen vertraging en geen kans op falen: dat zou doen alsof er een order is
        verstuurd die we hebben zien landen. Wat er wél in zit, is de slippage en de
        haircut, want de positie moet nog wel de pool uit. Het resultaat is een waardering
        en geen uitstap, en het wordt in de boekhouding apart gemarkeerd.
        """
        impact = price_impact(pool, units=units, swap_fee_bps=self.swap_fee_bps)
        waarde = units * price
        haircut = (
            pool.liquidity_usd > 0
            and waarde / pool.liquidity_usd > self.exit_haircut_above_pool_share
        )
        if haircut:
            impact += Decimal(self.exit_haircut_bps) / BPS
        impact = min(impact * self.stress.slippage_multiplier, Decimal("1"))
        prijs = (price * (Decimal("1") - impact)).quantize(
            PRICE_SCALE, rounding=ROUND_HALF_UP
        )
        return FillOutcome(
            kind=FillKind.EXIT,
            filled=True,
            requested_at=moment,
            filled_at=moment,
            latency_ms=0.0,
            expected_price=price,
            market_price=price,
            fill_price=prijs,
            units=units,
            quote_usd=(prijs * units).quantize(MONEY_SCALE),
            slippage_usd=((price - prijs) * units).quantize(MONEY_SCALE),
            latency_cost_usd=Decimal("0"),
            fee_usd=self.transaction_fee_usd,
            exit_haircut_applied=haircut,
            failure_reason=None,
        )

    def _instap(
        self,
        request: FillRequest,
        pool: PoolDepth,
        moment: datetime,
        vertraging: float,
        markt: Decimal,
    ) -> FillOutcome:
        inleg = request.quote_usd or Decimal("0")
        impact = price_impact(pool, quote_usd=inleg, swap_fee_bps=self.swap_fee_bps)
        impact *= self.stress.slippage_multiplier
        prijs = (markt * (Decimal("1") + impact)).quantize(
            PRICE_SCALE, rounding=ROUND_HALF_UP
        )
        stuks = (inleg / prijs).quantize(UNIT_SCALE, rounding=ROUND_HALF_UP) if prijs else Decimal("0")
        return FillOutcome(
            kind=FillKind.ENTRY,
            filled=True,
            requested_at=request.requested_at,
            filled_at=moment,
            latency_ms=vertraging,
            expected_price=request.expected_price,
            market_price=markt,
            fill_price=prijs,
            units=stuks,
            quote_usd=inleg,
            slippage_usd=((prijs - markt) * stuks).quantize(MONEY_SCALE),
            latency_cost_usd=((markt - request.expected_price) * stuks).quantize(MONEY_SCALE),
            fee_usd=self.transaction_fee_usd,
            exit_haircut_applied=False,
            failure_reason=None,
        )

    def _uitstap(
        self,
        request: FillRequest,
        pool: PoolDepth,
        moment: datetime,
        vertraging: float,
        markt: Decimal,
    ) -> FillOutcome:
        stuks = request.units or Decimal("0")
        impact = price_impact(pool, units=stuks, swap_fee_bps=self.swap_fee_bps)

        # Boven een deel van de pool komt er een haircut bij: in paniek krijg je slechter
        # dan de AMM-curve je voorrekent, omdat je niet de enige bent die eruit wil. Dit is
        # een bewust conservatieve aanname en geen meting.
        waarde = stuks * markt
        haircut = (
            pool.liquidity_usd > 0
            and waarde / pool.liquidity_usd > self.exit_haircut_above_pool_share
        )
        if haircut:
            impact += Decimal(self.exit_haircut_bps) / BPS
        impact *= self.stress.slippage_multiplier
        impact = min(impact, Decimal("1"))

        prijs = (markt * (Decimal("1") - impact)).quantize(
            PRICE_SCALE, rounding=ROUND_HALF_UP
        )
        return FillOutcome(
            kind=FillKind.EXIT,
            filled=True,
            requested_at=request.requested_at,
            filled_at=moment,
            latency_ms=vertraging,
            expected_price=request.expected_price,
            market_price=markt,
            fill_price=prijs,
            units=stuks,
            quote_usd=(prijs * stuks).quantize(MONEY_SCALE),
            slippage_usd=((markt - prijs) * stuks).quantize(MONEY_SCALE),
            latency_cost_usd=((request.expected_price - markt) * stuks).quantize(MONEY_SCALE),
            fee_usd=self.transaction_fee_usd,
            exit_haircut_applied=haircut,
            failure_reason=None,
        )

    def _niets(
        self,
        request: FillRequest,
        moment: datetime,
        vertraging: float,
        reden: str,
        *,
        fee: Decimal,
        markt: Decimal | None = None,
    ) -> FillOutcome:
        return FillOutcome(
            kind=request.kind,
            filled=False,
            requested_at=request.requested_at,
            filled_at=moment,
            latency_ms=vertraging,
            expected_price=request.expected_price,
            market_price=markt,
            fill_price=Decimal("0"),
            units=Decimal("0"),
            quote_usd=Decimal("0"),
            slippage_usd=Decimal("0"),
            latency_cost_usd=Decimal("0"),
            fee_usd=fee,
            exit_haircut_applied=False,
            failure_reason=reden,
        )
