"""Tests voor inloggen, rechten, bevestiging en het schoonhouden van het log."""

from __future__ import annotations

import pytest

from app.core.config import DEV_ENCRYPTION_KEY, DEV_SECRET_KEY, Settings
from app.core.permissions import PERMISSIONS, permissions_for_tier, tier_allows
from app.core.security import create_token, decode_token
from app.services.activity_service import scrub_context
from app.utils.crypto import TokenVault
from tests.conftest import auth_headers

TEST_KEY = "8sT2Yb0Vc9kQpLmXnZaWdEfGhIjKlMnOpQrStUvWxYz="


async def test_login_and_wrong_password(client, owner):
    ok = await client.post(
        "/auth/login", json={"email": owner.email, "password": "geheim123"}
    )
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    bad = await client.post("/auth/login", json={"email": owner.email, "password": "fout"})
    assert bad.status_code == 401
    # Dezelfde melding als bij een onbekend adres, zodat je niets kunt aftasten.
    unknown = await client.post(
        "/auth/login", json={"email": "niemand@example.com", "password": "fout"}
    )
    assert bad.json()["detail"] == unknown.json()["detail"]


def test_an_access_token_is_not_a_confirmation_token():
    token = create_token(1, "access")
    assert decode_token(token, "access") is not None
    assert decode_token(token, "confirmation") is None


async def test_confirmation_token_requires_the_password(client, owner):
    wrong = await client.post(
        "/auth/confirm", json={"password": "fout"}, headers=auth_headers(owner)
    )
    assert wrong.status_code == 401
    right = await client.post(
        "/auth/confirm", json={"password": "geheim123"}, headers=auth_headers(owner)
    )
    assert right.status_code == 200
    assert right.json()["confirmation_token"]


def test_tier_rules_match_the_specification():
    assert tier_allows(1, "finance.read")
    assert not tier_allows(2, "finance.read")
    assert tier_allows(1, "upload.execute")
    assert not tier_allows(2, "upload.execute")
    assert tier_allows(3, "todo.read")
    assert not tier_allows(3, "todo.write")
    assert "finance.manage" not in permissions_for_tier(2)


def test_sensitive_permissions_are_marked():
    sensitive = {perm.key for perm in PERMISSIONS if perm.sensitive}
    assert {"finance.manage", "social.manage", "upload.execute"} <= sensitive


def test_secrets_are_stripped_from_the_activity_log():
    cleaned = scrub_context(
        {
            "provider": "manual",
            "api_key": "sk-123",
            "nested": {"access_token": "abc", "balance": 4200, "name": "Rekening"},
            "list": [{"pin": "0000"}],
        }
    )
    assert cleaned["provider"] == "manual"
    assert cleaned["api_key"] == "[verwijderd]"
    assert cleaned["nested"]["access_token"] == "[verwijderd]"
    assert cleaned["nested"]["balance"] == "[verwijderd]"
    assert cleaned["nested"]["name"] == "Rekening"
    assert cleaned["list"][0]["pin"] == "[verwijderd]"


def test_tokens_are_encrypted_at_rest():
    vault = TokenVault(TEST_KEY)
    blob = vault.encrypt({"access_token": "supergeheim"})
    assert blob is not None
    assert "supergeheim" not in blob
    assert vault.decrypt(blob) == {"access_token": "supergeheim"}


def test_an_unreadable_token_does_not_crash():
    """Na het wisselen van de sleutel moet je opnieuw koppelen, niet herstarten."""
    assert TokenVault(TEST_KEY).decrypt("onzin") is None


def test_production_refuses_to_start_on_development_keys():
    """De ontwikkelsleutels staan in de broncode; in productie mogen ze niet blijven."""
    with pytest.raises(RuntimeError) as error:
        Settings(
            environment="production",
            secret_key=DEV_SECRET_KEY,
            encryption_key=DEV_ENCRYPTION_KEY,
        ).check_production_secrets()
    assert "GANZ_SECRET_KEY" in str(error.value)
    assert "GANZ_ENCRYPTION_KEY" in str(error.value)


def test_production_accepts_its_own_keys():
    Settings(
        environment="production", secret_key="een-echt-geheim", encryption_key=TEST_KEY
    ).check_production_secrets()


async def test_permission_registry_endpoint_shows_what_you_may_do(client, trusted):
    rows = (await client.get("/auth/permissions", headers=auth_headers(trusted))).json()
    by_key = {row["key"]: row for row in rows}
    assert by_key["finance.read"]["granted"] is False
    assert by_key["todo.write"]["granted"] is True
    assert by_key["finance.manage"]["sensitive"] is True
