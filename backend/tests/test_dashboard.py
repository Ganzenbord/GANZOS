"""Tests voor het dashboard-eindpunt."""

from __future__ import annotations

from tests.conftest import auth_headers


async def test_dashboard_has_all_panels_for_the_owner(client, owner):
    response = await client.get("/dashboard", headers=auth_headers(owner))
    assert response.status_code == 200
    body = response.json()
    for key in ("core", "todo", "finance", "social", "uploads", "system", "memory", "llm"):
        assert key in body, key
    assert body["user"]["tier"] == 1
    assert "finance.read" in body["user"]["permissions"]
    assert body["server_time"]


async def test_dashboard_hides_finance_for_lower_tiers(client, trusted):
    body = (await client.get("/dashboard", headers=auth_headers(trusted))).json()
    assert body["finance"] is None
    assert body["todo"] is not None
    assert body["social"] is not None
    assert "finance.read" not in body["user"]["permissions"]


async def test_dashboard_for_a_limited_tier_hides_memory_and_feed(client, limited):
    body = (await client.get("/dashboard", headers=auth_headers(limited))).json()
    assert body["finance"] is None
    assert body["memory"] is None
    assert body["feed"] == []
    assert body["todo"] is not None


async def test_dashboard_requires_a_login(client):
    assert (await client.get("/dashboard")).status_code == 401


async def test_fresh_install_shows_nothing_instead_of_example_data(client, owner):
    """Niets gekoppeld betekent lege panelen, geen voorbeeldcijfers."""
    body = (await client.get("/dashboard", headers=auth_headers(owner))).json()
    assert body["finance"]["total_eur"] == "0.00"
    assert body["finance"]["connected_accounts"] == 0
    assert body["social"]["followers"] is None
    assert body["social"]["channels_total"] == 0
    assert body["uploads"]["channels"] == []
    assert body["todo"]["tasks"] == []
    assert body["llm"] == []


async def test_system_monitor_reports_real_measurements(client, owner):
    body = (await client.get("/dashboard", headers=auth_headers(owner))).json()
    system = body["system"]
    for key in ("cpu_pct", "ram_pct", "disk_pct"):
        assert 0.0 <= system[key] <= 100.0
    assert system["status"] in ("optimal", "warning")


async def test_server_time_endpoint_is_public(client):
    response = await client.get("/time")
    assert response.status_code == 200
    assert response.json()["server_time"]
