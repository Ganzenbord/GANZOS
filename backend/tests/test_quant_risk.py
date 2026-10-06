"""De risicolaag van het Quant Lab (sectie 9 van de opdracht).

Deze tests zijn vóór de implementatie geschreven, en dat is hier geen stijlkwestie: een
risicogrens die pas achteraf een test krijgt, is een grens waarvan niemand weet of hij ooit
heeft gewerkt. Elke regel uit sectie 9 heeft hieronder een test die faalt zodra de grens
wegvalt — inclusief een test per *bewuste overtreding*.

Er wordt in dit project niet live gehandeld. Alles hieronder gaat over papier.
"""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.quantlab import risk_limits
from app.quantlab.risk import (
    EntryRequest,
    RiskSnapshot,
    RiskVeto,
    VETO_UITLEG,
    evaluate_entry,
    one_r_amount,
    position_units,
)

QUANTLAB_DIR = Path(__file__).resolve().parents[1] / "app" / "quantlab"

# Een stand waarin alles mag. Elke test zet één ding fout, zodat je uit de naam van de test
# weet welke grens hem tegenhoudt.
GEZOND = RiskSnapshot(
    equity=Decimal("10000"),
    open_risk_r=Decimal("0"),
    realized_day_r=Decimal("0"),
    realized_week_r=Decimal("0"),
    kill_switch_active=False,
    heartbeat_age_seconds=5.0,
)

# Een instap met een stop 10% onder de instapprijs.
INSTAP = EntryRequest(
    hypothesis="H1_v1", entry_price=Decimal("1.00"), stop_price=Decimal("0.90")
)


# --- 1R en positiegrootte ----------------------------------------------------


def test_1r_is_driekwart_procent_van_de_paper_equity() -> None:
    assert one_r_amount(Decimal("10000")) == Decimal("75.00")
    assert one_r_amount(Decimal("1000")) == Decimal("7.50")


def test_1r_wordt_naar_beneden_afgerond() -> None:
    """Naar boven afronden zou betekenen dat 1R stiekem meer dan 0,75% is."""
    assert one_r_amount(Decimal("1234.56")) == Decimal("9.25")


def test_zonder_equity_is_er_niets_te_riskeren() -> None:
    assert one_r_amount(Decimal("0")) == Decimal("0")
    assert one_r_amount(Decimal("-50")) == Decimal("0")


def test_de_omvang_hangt_uitsluitend_aan_de_equity() -> None:
    """Geen martingale, en dat is hier geen afspraak maar een signatuur.

    `one_r_amount` kán niet naar de laatste uitslagen kijken, want die krijgt hij niet mee.
    Komt er ooit een tweede parameter bij, dan valt deze test om en is dat een gesprek."""
    parameters = list(inspect.signature(one_r_amount).parameters)
    assert parameters == ["equity"], (
        "one_r_amount mag alleen de equity zien. Een parameter erbij is de deur naar "
        f"positiegrootte op gevoel: {parameters}"
    )


def test_een_reeks_verliezen_verandert_de_inzet_niet() -> None:
    """Vijf verliezen achter elkaar: bij dezelfde equity blijft 1R exact hetzelfde."""
    eerste = one_r_amount(Decimal("10000"))
    for _ in range(5):
        assert one_r_amount(Decimal("10000")) == eerste


def test_de_positie_volgt_uit_de_afstand_tot_de_stop() -> None:
    """75 euro risico, 10 cent afstand tot de stop, dus 750 stuks."""
    stuks = position_units(
        risk_eur=Decimal("75.00"), entry_price=Decimal("1.00"), stop_price=Decimal("0.90")
    )
    assert stuks == Decimal("750")


def test_de_positie_wordt_naar_beneden_afgerond() -> None:
    """Afronden naar boven zou het werkelijke risico boven 1R duwen."""
    stuks = position_units(
        risk_eur=Decimal("75.00"), entry_price=Decimal("1.00"), stop_price=Decimal("0.93")
    )
    assert stuks * Decimal("0.07") <= Decimal("75.00")


def test_een_stop_op_de_instapprijs_is_geen_stop() -> None:
    with pytest.raises(ValueError):
        position_units(
            risk_eur=Decimal("75"), entry_price=Decimal("1.00"), stop_price=Decimal("1.00")
        )


# --- De grenzen, elk met een bewuste overtreding -----------------------------


def test_een_gezonde_stand_laat_een_instap_door() -> None:
    besluit = evaluate_entry(GEZOND, INSTAP)
    assert besluit.allowed is True
    assert besluit.veto is None
    assert besluit.risk_eur == Decimal("75.00")
    assert besluit.position_units == Decimal("750")


def test_meer_dan_1r_per_trade_wordt_geblokkeerd() -> None:
    overtreding = EntryRequest(
        hypothesis="H1_v1",
        entry_price=Decimal("1.00"),
        stop_price=Decimal("0.90"),
        risk_r=Decimal("1.5"),
    )
    besluit = evaluate_entry(GEZOND, overtreding)
    assert besluit.allowed is False
    assert besluit.veto is RiskVeto.RISK_PER_TRADE_EXCEEDED


def test_precies_1r_mag_nog() -> None:
    besluit = evaluate_entry(
        GEZOND,
        EntryRequest(
            hypothesis="H1_v1",
            entry_price=Decimal("1.00"),
            stop_price=Decimal("0.90"),
            risk_r=Decimal("1"),
        ),
    )
    assert besluit.allowed is True


def test_risico_nul_of_negatief_is_geen_instap() -> None:
    for waarde in (Decimal("0"), Decimal("-1")):
        besluit = evaluate_entry(
            GEZOND,
            EntryRequest(
                hypothesis="H1_v1",
                entry_price=Decimal("1.00"),
                stop_price=Decimal("0.90"),
                risk_r=waarde,
            ),
        )
        assert besluit.allowed is False
        assert besluit.veto is RiskVeto.RISK_PER_TRADE_EXCEEDED


def test_boven_5r_open_risico_gaat_er_niets_meer_bij() -> None:
    besluit = evaluate_entry(GEZOND.met(open_risk_r=Decimal("5")), INSTAP)
    assert besluit.allowed is False
    assert besluit.veto is RiskVeto.OPEN_RISK_EXCEEDED


def test_de_vijfde_positie_mag_nog_wel() -> None:
    besluit = evaluate_entry(GEZOND.met(open_risk_r=Decimal("4")), INSTAP)
    assert besluit.allowed is True


def test_bij_minus_3r_op_een_dag_gaan_er_geen_nieuwe_posities_open() -> None:
    besluit = evaluate_entry(GEZOND.met(realized_day_r=Decimal("-3")), INSTAP)
    assert besluit.allowed is False
    assert besluit.veto is RiskVeto.DAY_LOSS_HALT


def test_net_boven_de_dagstop_mag_nog() -> None:
    besluit = evaluate_entry(GEZOND.met(realized_day_r=Decimal("-2.9")), INSTAP)
    assert besluit.allowed is True


def test_bij_minus_8r_in_een_week_staat_alles_stil() -> None:
    besluit = evaluate_entry(
        GEZOND.met(realized_day_r=Decimal("-1"), realized_week_r=Decimal("-8")), INSTAP
    )
    assert besluit.allowed is False
    assert besluit.veto is RiskVeto.WEEK_LOSS_STOP


def test_de_weekstop_weegt_zwaarder_dan_de_dagstop() -> None:
    """Allebei overtreden: de melding moet de zwaarste noemen, anders denk je dat je er
    morgen weer in mag."""
    besluit = evaluate_entry(
        GEZOND.met(realized_day_r=Decimal("-4"), realized_week_r=Decimal("-9")), INSTAP
    )
    assert besluit.veto is RiskVeto.WEEK_LOSS_STOP


def test_een_handmatige_reset_schuift_de_weekgrens_mee() -> None:
    """Na een reset op -8R is er weer 8R ruimte; de grens staat dan op -16R.

    Dat is met opzet geen "zet de teller op nul": het verlies van deze week blijft staan in
    de cijfers, alleen de stop is opnieuw gezet."""
    na_reset = GEZOND.met(
        realized_week_r=Decimal("-8"), week_stop_level_r=Decimal("-16")
    )
    assert evaluate_entry(na_reset, INSTAP).allowed is True

    weer_stil = na_reset.met(realized_week_r=Decimal("-16"))
    assert evaluate_entry(weer_stil, INSTAP).veto is RiskVeto.WEEK_LOSS_STOP


def test_de_killswitch_blokkeert_alles() -> None:
    besluit = evaluate_entry(GEZOND.met(kill_switch_active=True), INSTAP)
    assert besluit.allowed is False
    assert besluit.veto is RiskVeto.KILL_SWITCH_ACTIVE


def test_de_killswitch_wordt_als_eerste_gemeld() -> None:
    """Staat alles tegelijk fout, dan is de killswitch het antwoord: dat is de knop waar
    iemand bewust op heeft geduwd."""
    alles_fout = GEZOND.met(
        kill_switch_active=True,
        open_risk_r=Decimal("9"),
        realized_day_r=Decimal("-5"),
        realized_week_r=Decimal("-20"),
        heartbeat_age_seconds=None,
    )
    assert evaluate_entry(alles_fout, INSTAP).veto is RiskVeto.KILL_SWITCH_ACTIVE


def test_een_oude_hartslag_blokkeert_een_instap() -> None:
    oud = float(risk_limits.HEARTBEAT_MAX_AGE_SECONDS) + 1
    besluit = evaluate_entry(GEZOND.met(heartbeat_age_seconds=oud), INSTAP)
    assert besluit.allowed is False
    assert besluit.veto is RiskVeto.HEARTBEAT_STALE


def test_zonder_enige_hartslag_blokkeert_een_instap() -> None:
    """Nooit een hartslag gehad is erger dan een oude, niet beter."""
    besluit = evaluate_entry(GEZOND.met(heartbeat_age_seconds=None), INSTAP)
    assert besluit.allowed is False
    assert besluit.veto is RiskVeto.HEARTBEAT_STALE


def test_zonder_equity_kan_er_niet_worden_ingestapt() -> None:
    besluit = evaluate_entry(GEZOND.met(equity=Decimal("0")), INSTAP)
    assert besluit.allowed is False
    assert besluit.veto is RiskVeto.NO_EQUITY


def test_een_instap_zonder_afstand_tot_de_stop_wordt_geblokkeerd() -> None:
    besluit = evaluate_entry(
        GEZOND,
        EntryRequest(
            hypothesis="H1_v1", entry_price=Decimal("1.00"), stop_price=Decimal("1.00")
        ),
    )
    assert besluit.allowed is False
    assert besluit.veto is RiskVeto.INVALID_STOP


# --- Vorm en herkomst van de grenzen -----------------------------------------


def test_elke_weigering_heeft_een_uitleg_in_gewone_taal() -> None:
    """De stoplichten en de banner lezen deze tekst; een lege uitleg is een leeg scherm."""
    for veto in RiskVeto:
        assert VETO_UITLEG[veto].strip(), veto
        assert len(VETO_UITLEG[veto]) > 20, veto


def test_de_grenzen_staan_in_code_en_niet_in_een_instelling() -> None:
    """Sectie 9: constanten in code, niet in config en niet bereikbaar voor agents.

    Een grens die uit een omgevingsvariabele komt, is een grens die je om half drie 's
    nachts even verzet. Deze test leest de boom van het bestand — niet de tekst, want dan
    zou een woord in een toelichting hem al laten omvallen — en eist dat er niets anders
    in staat dan toekenningen: geen import behalve `decimal`, en geen aanroep behalve
    `Decimal(...)`.
    """
    boom = ast.parse((QUANTLAB_DIR / "risk_limits.py").read_text())

    for knoop in ast.walk(boom):
        if isinstance(knoop, (ast.Import, ast.ImportFrom)):
            assert set(_modules(knoop)) <= {"__future__", "decimal"}, (
                "risk_limits.py mag niets importeren: elke import is een manier om de "
                f"grenzen van buiten te laten komen ({_modules(knoop)})"
            )
        if isinstance(knoop, ast.Call):
            naam = getattr(knoop.func, "id", None) or getattr(knoop.func, "attr", "")
            assert naam == "Decimal", (
                f"risk_limits.py roept {naam}() aan. Een grens die wordt berekend of "
                "opgehaald, is geen constante."
            )
        assert not isinstance(knoop, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)), (
            "risk_limits.py bevat alleen constanten; een functie erin is een plek om ze "
            "te laten afhangen van iets anders"
        )


def _modules(knoop: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(knoop, ast.ImportFrom):
        return [knoop.module or ""]
    return [alias.name for alias in knoop.names]


def test_de_waarden_uit_de_opdracht_staan_er_letterlijk() -> None:
    assert risk_limits.RISK_PER_TRADE_PCT == Decimal("0.0075")
    assert risk_limits.MAX_RISK_PER_TRADE_R == Decimal("1")
    assert risk_limits.MAX_OPEN_RISK_R == Decimal("5")
    assert risk_limits.DAY_LOSS_HALT_R == Decimal("-3")
    assert risk_limits.WEEK_LOSS_STOP_R == Decimal("-8")
    assert risk_limits.HEARTBEAT_MAX_AGE_SECONDS > 0


def test_de_risicolaag_praat_met_geen_enkel_taalmodel() -> None:
    """Sectie 6: geen enkele LLM-aanroep in het pad waarin een trade tot stand komt.

    Dit is een importtest en geen belofte. Zou iemand de Analyst erbij halen "om nog even
    te kijken", dan valt dit om."""
    for naam in ("risk.py", "risk_limits.py"):
        boom = ast.parse((QUANTLAB_DIR / naam).read_text())
        geimporteerd = [
            module
            for knoop in ast.walk(boom)
            if isinstance(knoop, (ast.Import, ast.ImportFrom))
            for module in _modules(knoop)
        ]
        for module in geimporteerd:
            for verboden in ("httpx", "requests", "anthropic", "openai", "decision", "llm"):
                assert verboden not in module, (
                    f"{naam} importeert {module}; de risicolaag moet pure code blijven"
                )


def test_een_snapshot_is_niet_te_wijzigen() -> None:
    """De Risk Officer deelt zijn stand uit; niemand mag er een getal in veranderen."""
    with pytest.raises(Exception):
        GEZOND.equity = Decimal("999999")  # type: ignore[misc]


# --- De stand uit de database ------------------------------------------------


async def test_alleen_de_verliezen_van_vandaag_tellen_voor_de_dagstop(session) -> None:
    from app.models.quantlab import QuantRiskBooking
    from app.services import quant_risk_service

    # Een vast moment midden in de week. Met `now()` zou deze test op een maandag anders
    # uitpakken dan op een donderdag: "gisteren" valt dan in de vorige week.
    nu = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    gisteren = nu - timedelta(days=1)
    for tijd, r in ((gisteren, Decimal("-3")), (nu, Decimal("-1"))):
        session.add(
            QuantRiskBooking(
                hypothesis="H1_v1", r_multiple=r, closed_at=tijd, note="test"
            )
        )
    await session.commit()

    stand = await quant_risk_service.snapshot(session, equity=Decimal("10000"), now=nu)
    assert stand.realized_day_r == Decimal("-1")
    assert stand.realized_week_r == Decimal("-4")


async def test_de_weekstand_begint_maandag_nul_uur_utc(session) -> None:
    from app.models.quantlab import QuantRiskBooking
    from app.services import quant_risk_service

    # Woensdag 7 oktober 2026, 12:00 UTC. De maandag ervoor is de 5e.
    woensdag = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    session.add(
        QuantRiskBooking(
            hypothesis="H1_v1",
            r_multiple=Decimal("-5"),
            closed_at=datetime(2026, 10, 4, 23, 59, tzinfo=timezone.utc),
            note="vorige week",
        )
    )
    session.add(
        QuantRiskBooking(
            hypothesis="H1_v1",
            r_multiple=Decimal("-2"),
            closed_at=datetime(2026, 10, 5, 0, 1, tzinfo=timezone.utc),
            note="deze week",
        )
    )
    await session.commit()

    stand = await quant_risk_service.snapshot(
        session, equity=Decimal("10000"), now=woensdag
    )
    assert stand.realized_week_r == Decimal("-2")


async def test_de_killswitch_blijft_staan_na_een_herstart(session) -> None:
    """De stand komt uit de database, niet uit het geheugen van een proces."""
    from app.services import quant_risk_service

    await quant_risk_service.engage_kill_switch(
        session, reason="test", source="user", user_id=None
    )
    await session.commit()

    stand = await quant_risk_service.snapshot(session, equity=Decimal("10000"))
    assert stand.kill_switch_active is True

    await quant_risk_service.release_kill_switch(
        session, reason="test klaar", user_id=None
    )
    await session.commit()
    opnieuw = await quant_risk_service.snapshot(session, equity=Decimal("10000"))
    assert opnieuw.kill_switch_active is False


async def test_de_weekstop_gaat_niet_vanzelf_weer_open(session) -> None:
    from app.models.quantlab import QuantRiskBooking
    from app.services import quant_risk_service

    # Woensdag, met het verlies op maandag. Twee redenen voor die opzet: de dagstop mag
    # deze test niet overnemen (die geldt alleen voor vandaag), en zonder hartslag zou de
    # dead-man switch al eerder tegenhouden.
    nu = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    maandag = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)
    await quant_risk_service.heartbeat(session, component="scout", now=nu)
    session.add(
        QuantRiskBooking(
            hypothesis="H1_v1", r_multiple=Decimal("-8"), closed_at=maandag, note="slechte week"
        )
    )
    await session.commit()

    stand = await quant_risk_service.snapshot(session, equity=Decimal("10000"), now=nu)
    assert stand.week_stop_level_r == Decimal("-8")
    assert evaluate_entry(stand, INSTAP).veto is RiskVeto.WEEK_LOSS_STOP

    # Alleen een handmatige reset schuift de grens.
    await quant_risk_service.reset_week_stop(
        session, user_id=None, reason="Stef kijkt mee", now=nu
    )
    await session.commit()
    na = await quant_risk_service.snapshot(session, equity=Decimal("10000"), now=nu)
    assert na.week_stop_level_r == Decimal("-16")
    assert evaluate_entry(na, INSTAP).allowed is True


async def test_elke_beslissing_komt_in_het_logboek(session) -> None:
    """Bewijs boven verhaal: ook een geweigerde instap laat een rij achter."""
    from app.models.quantlab import QuantRiskEvent
    from app.services import quant_risk_service
    from sqlalchemy import select

    await quant_risk_service.engage_kill_switch(
        session, reason="test", source="user", user_id=None
    )
    await session.commit()

    besluit = await quant_risk_service.check_entry(
        session, equity=Decimal("10000"), request=INSTAP
    )
    await session.commit()

    assert besluit.allowed is False
    rijen = (await session.execute(select(QuantRiskEvent))).scalars().all()
    assert len(rijen) == 1
    assert rijen[0].allowed is False
    assert rijen[0].veto == RiskVeto.KILL_SWITCH_ACTIVE.value
    assert rijen[0].hypothesis == "H1_v1"


async def test_een_hartslag_veroudert(session) -> None:
    from app.services import quant_risk_service

    nu = datetime.now(timezone.utc)
    await quant_risk_service.heartbeat(session, component="scout", now=nu)
    await session.commit()

    vers = await quant_risk_service.snapshot(session, equity=Decimal("10000"), now=nu)
    assert vers.heartbeat_age_seconds is not None
    assert vers.heartbeat_age_seconds < 1

    later = nu + timedelta(seconds=risk_limits.HEARTBEAT_MAX_AGE_SECONDS + 10)
    oud = await quant_risk_service.snapshot(session, equity=Decimal("10000"), now=later)
    assert evaluate_entry(oud, INSTAP).veto is RiskVeto.HEARTBEAT_STALE


# --- Over HTTP ---------------------------------------------------------------


async def test_de_risicostand_is_zichtbaar_vanaf_tier_2(client, trusted) -> None:
    from tests.conftest import auth_headers

    antwoord = await client.get("/quant/risk", headers=auth_headers(trusted))
    assert antwoord.status_code == 200, antwoord.text
    body = antwoord.json()
    assert body["limits"]["max_open_risk_r"] == "5"
    assert body["kill_switch_active"] is False


async def test_een_gast_mag_het_quant_lab_niet_zien(client, session) -> None:
    from app.models.user import TIER_GUEST, User
    from app.core.security import hash_password
    from tests.conftest import auth_headers

    gast = User(
        email="gast4@example.com",
        display_name="Gast",
        password_hash=hash_password("geheim123"),
        tier=TIER_GUEST,
    )
    session.add(gast)
    await session.commit()

    antwoord = await client.get("/quant/risk", headers=auth_headers(gast))
    assert antwoord.status_code == 403


async def test_de_killswitch_gaat_aan_zonder_tweede_bevestiging(client, trusted) -> None:
    """Stoppen moet meteen kunnen. Een pincode intikken terwijl het misgaat, kost seconden
    die je niet hebt — en stoppen is de veilige richting."""
    from tests.conftest import auth_headers

    antwoord = await client.post(
        "/quant/risk/kill-switch",
        json={"reason": "ik zie iets wat ik niet snap"},
        headers=auth_headers(trusted),
    )
    assert antwoord.status_code == 200, antwoord.text
    assert antwoord.json()["kill_switch_active"] is True


async def test_de_killswitch_eruit_halen_vraagt_wel_om_een_bevestiging(
    client, owner, session
) -> None:
    from tests.conftest import auth_headers, confirm_headers

    await client.post(
        "/quant/risk/kill-switch", json={"reason": "test"}, headers=auth_headers(owner)
    )

    zonder = await client.request(
        "DELETE",
        "/quant/risk/kill-switch",
        json={"reason": "weer aan"},
        headers=auth_headers(owner),
    )
    assert zonder.status_code == 428

    headers = await confirm_headers(session, owner, "quant.run.start")
    met = await client.request(
        "DELETE", "/quant/risk/kill-switch", json={"reason": "weer aan"}, headers=headers
    )
    assert met.status_code == 200, met.text
    assert met.json()["kill_switch_active"] is False


async def test_alleen_de_eigenaar_zet_de_weekstop_opnieuw(client, trusted, owner, session) -> None:
    from tests.conftest import auth_headers, confirm_headers

    geweigerd = await client.post(
        "/quant/risk/week-reset", json={"reason": "toch doorgaan"}, headers=auth_headers(trusted)
    )
    assert geweigerd.status_code == 403

    headers = await confirm_headers(session, owner, "quant.risk.reset")
    toegestaan = await client.post(
        "/quant/risk/week-reset", json={"reason": "ik kijk mee"}, headers=headers
    )
    assert toegestaan.status_code == 200, toegestaan.text
