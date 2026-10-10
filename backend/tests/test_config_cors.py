"""De CORS-instelling uit de omgeving.

Dit bestand bestaat om één reden: de instelling zoals `deploy/ganz.env.example` hem
voorschrijft (`GANZ_CORS_ORIGINS=`, leeg) liet de server **niet starten**. Pydantic probeert
een lijstveld uit de omgeving eerst als JSON te lezen, en een lege regel is geen JSON. Je
merkte dat pas bij het opstarten op de server, en dan staat er een foutmelding over
"EnvSettingsSource" waar niemand iets aan heeft.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings

BASIS = {
    "GANZ_SECRET_KEY": "test",
    "GANZ_ENCRYPTION_KEY": "8sT2Yb0Vc9kQpLmXnZaWdEfGhIjKlMnOpQrStUvWxYz=",
}


@pytest.mark.parametrize(
    "waarde, verwacht",
    [
        # Zoals het voorbeeldbestand het voorschrijft.
        ("", []),
        # Eén naam, de gewone manier.
        ("https://ganz.example.net", ["https://ganz.example.net"]),
        # Meerdere met komma's, met en zonder ruimte erachter.
        ("https://a.net,https://b.net", ["https://a.net", "https://b.net"]),
        ("https://a.net, https://b.net", ["https://a.net", "https://b.net"]),
        # En JSON blijft werken, want zo stond het in bestaande opstellingen.
        ('["https://a.net","https://b.net"]', ["https://a.net", "https://b.net"]),
    ],
)
def test_elke_vorm_uit_de_omgeving_werkt(
    monkeypatch: pytest.MonkeyPatch, waarde: str, verwacht: list[str]
) -> None:
    for sleutel, inhoud in BASIS.items():
        monkeypatch.setenv(sleutel, inhoud)
    monkeypatch.setenv("GANZ_CORS_ORIGINS", waarde)
    assert Settings().cors_origins == verwacht


def test_niets_instellen_geeft_de_ontwikkelstandaard(monkeypatch: pytest.MonkeyPatch) -> None:
    for sleutel, inhoud in BASIS.items():
        monkeypatch.setenv(sleutel, inhoud)
    monkeypatch.delenv("GANZ_CORS_ORIGINS", raising=False)
    assert Settings().cors_origins == ["http://localhost:5173"]


def test_leeg_betekent_niets_toestaan_en_niet_alles(monkeypatch: pytest.MonkeyPatch) -> None:
    """De kant waarop dit fout mag gaan: een lege waarde staat géén vreemde herkomst toe.
    Zou het alles toestaan, dan mag elke site bij je API zonder dat iemand het ziet."""
    for sleutel, inhoud in BASIS.items():
        monkeypatch.setenv(sleutel, inhoud)
    monkeypatch.setenv("GANZ_CORS_ORIGINS", "   ")
    assert Settings().cors_origins == []
