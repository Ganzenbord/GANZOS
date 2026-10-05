"""Hypotheses, vastgelegd en gehasht vóór de eerste run (sectie 8).

Een strategie is hier een bestand, niet een stel instellingen in een scherm. Dat bestand
wordt gehasht en de hash gaat mee in elke run. Wijzigen betekent een nieuwe versie, en bij
een nieuwe versie begint de trade-teller opnieuw.

Dat is met opzet onhandig. Zonder die drempel gebeurt wat altijd gebeurt: na een slechte
week schuift iemand een filter een stukje op, de curve wordt mooier, en niemand weet nog
tegen welke regels de oude trades zijn gemeten.

De hash gaat over de **tekst van het bestand**, niet over de geparste structuur. Dus ook
commentaar telt mee — en dat hoort, want het commentaar legt uit waarom een waarde zo
staat, en dat is onderdeel van de registratie.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from app.quantlab.exits import ExitRules
from app.quantlab.fills import FillModel, StressProfile


class PreRegistrationError(RuntimeError):
    """Deze hypothese is al geregistreerd met een andere inhoud."""


def hypothesis_hash(source_yaml: str) -> str:
    return hashlib.sha256(source_yaml.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class HypothesisFile:
    name: str
    version: str
    statement: str
    paper_only: bool
    universe: dict[str, Any]
    safety_filters: dict[str, Any]
    entry: dict[str, Any]
    exit_rules: ExitRules
    sizing_risk_r: Decimal
    cost_model: dict[str, Any]
    cost_model_provenance: dict[str, str]
    kill_criteria: dict[str, Any]
    success_criteria: str
    source_yaml: str
    path: str | None = None

    @property
    def label(self) -> str:
        return f"{self.name}_{self.version}"

    @property
    def content_hash(self) -> str:
        return hypothesis_hash(self.source_yaml)

    def with_source(self, source_yaml: str) -> "HypothesisFile":
        """Dezelfde hypothese met andere brontekst. Alleen voor tests en voor het maken van
        een nieuwe versie; de hash verandert mee, en dat is het hele punt."""
        return replace(parse_hypothesis(source_yaml), path=self.path)

    def fill_model(self, stress: StressProfile | None = None) -> FillModel:
        """Het kostenmodel van deze hypothese als fill-model."""
        kosten = self.cost_model
        return FillModel(
            swap_fee_bps=int(kosten["swap_fee_bps"]),
            priority_fee_usd=Decimal(str(kosten["priority_fee_usd"])),
            network_fee_usd=Decimal(str(kosten["network_fee_usd"])),
            failure_probability=float(kosten["failure_probability"]),
            latency_p50_ms=int(kosten["latency_p50_ms"]),
            latency_p95_ms=int(kosten["latency_p95_ms"]),
            exit_haircut_bps=int(kosten["exit_haircut_bps"]),
            exit_haircut_above_pool_share=Decimal(
                str(kosten["exit_haircut_above_pool_share"])
            ),
            stress=stress or StressProfile(),
        )

    @property
    def min_liquidity_multiple(self) -> Decimal:
        return Decimal(str(self.safety_filters.get("min_liquidity_multiple_of_position", 0)))

    @property
    def exclude_when_sellability_unverified(self) -> bool:
        return bool(self.safety_filters.get("exclude_when_sellability_unverified", True))

    @property
    def min_trades_for_conclusion(self) -> int:
        return int(self.kill_criteria.get("min_trades_for_conclusion", 150))


def parse_hypothesis(source_yaml: str, *, path: str | None = None) -> HypothesisFile:
    doc = yaml.safe_load(source_yaml)
    if not isinstance(doc, dict):
        raise ValueError("Een hypothese-bestand hoort een YAML-object te zijn.")

    ontbreekt = [
        veld
        for veld in ("name", "version", "statement", "exit", "sizing", "cost_model")
        if veld not in doc
    ]
    if ontbreekt:
        raise ValueError(f"Hypothese mist: {', '.join(ontbreekt)}")

    if not doc.get("paper_only", False):
        # Er is in dit project geen live handel. Een hypothese die dat niet met zoveel
        # woorden zegt, draait niet.
        raise ValueError(
            "Een hypothese moet `paper_only: true` hebben; er wordt hier niet live gehandeld."
        )

    uit = doc["exit"]
    kosten = dict(doc["cost_model"])
    herkomst = dict(doc.get("cost_model_provenance") or {})
    zonder_herkomst = set(kosten) - set(herkomst)
    if zonder_herkomst:
        # Een kostenparameter zonder herkomst is een gok, en een gok in een kostenmodel is
        # een resultaat dat je niet kunt verdedigen.
        raise ValueError(
            "Deze kostenparameters hebben geen herkomst in `cost_model_provenance`: "
            + ", ".join(sorted(zonder_herkomst))
        )

    return HypothesisFile(
        name=str(doc["name"]),
        version=str(doc["version"]),
        statement=str(doc["statement"]).strip(),
        paper_only=True,
        universe=dict(doc.get("universe") or {}),
        safety_filters=dict(doc.get("safety_filters") or {}),
        entry=dict(doc.get("entry") or {}),
        exit_rules=ExitRules(
            stop_distance_pct=Decimal(str(uit["stop_distance_pct"])),
            take_half_at_r=Decimal(str(uit["take_half_at_r"])),
            trailing_stop_pct=Decimal(str(uit["trailing_stop_pct"])),
            max_hold_minutes=int(uit["max_hold_minutes"]),
        ),
        sizing_risk_r=Decimal(str(doc["sizing"]["risk_per_trade_r"])),
        cost_model=kosten,
        cost_model_provenance=herkomst,
        kill_criteria=dict(doc.get("kill_criteria") or {}),
        success_criteria=str(doc.get("success_criteria") or "").strip(),
        source_yaml=source_yaml,
        path=path,
    )


def load_hypothesis(path: str | Path) -> HypothesisFile:
    pad = Path(path)
    return parse_hypothesis(pad.read_text(encoding="utf-8"), path=str(pad))
