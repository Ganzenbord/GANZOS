"""Tests voor het uploadschema en de aftelling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.models.social import ChannelStatus
from app.models.upload import ContentType, UploadRecurrence, UploadStatus
from app.services import social_service, upload_service
from app.utils.timeutil import next_upload_occurrence
from tests.conftest import auth_headers

NOW = datetime(2025, 9, 15, 11, 18, 21, tzinfo=timezone.utc)


async def _channel(session, owner, name: str, platform: str = "youtube"):
    channel = await social_service.create_channel(
        session,
        owner.id,
        {
            "platform": platform,
            "channel_name": name,
            "external_channel_id": None,
            "credentials": {"access_token": "x"},
        },
    )
    await session.commit()
    return channel


async def _upload(session, owner, channel, **kwargs):
    data = {
        "channel_id": channel.id,
        "title": kwargs.pop("title", "Aflevering"),
        "content_type": ContentType.VIDEO,
        "scheduled_at": kwargs.pop("scheduled_at", NOW + timedelta(hours=1, minutes=13)),
        "recurrence": kwargs.pop("recurrence", UploadRecurrence.ONCE),
        "timezone": kwargs.pop("timezone", "Europe/Amsterdam"),
        **kwargs,
    }
    upload = await upload_service.create_upload(session, owner.id, data)
    await session.commit()
    return upload


async def test_next_upload_and_countdown(session, owner):
    channel = await _channel(session, owner, "YouTube Kanaal 1")
    await _upload(session, owner, channel, scheduled_at=NOW + timedelta(hours=1, minutes=13))

    overview = await upload_service.schedule_overview(session, owner.id, NOW)
    row = overview["channels"][0]
    assert row["channel_name"] == "YouTube Kanaal 1"
    # 1 uur en 13 minuten = 4380 seconden; de frontend maakt daar "1u 13m" van.
    assert row["next_upload"]["seconds_until"] == 4380
    assert row["next_upload"]["overdue"] is False
    assert overview["server_time"] == NOW


async def test_countdown_is_not_stored(session, owner):
    channel = await _channel(session, owner, "Kanaal")
    upload = await _upload(session, owner, channel)
    assert not hasattr(upload, "seconds_until")
    assert not hasattr(upload, "countdown")


async def test_the_nearest_upload_wins(session, owner):
    channel = await _channel(session, owner, "Kanaal")
    await _upload(session, owner, channel, title="Later", scheduled_at=NOW + timedelta(hours=5))
    await _upload(session, owner, channel, title="Eerder", scheduled_at=NOW + timedelta(minutes=28))

    overview = await upload_service.schedule_overview(session, owner.id, NOW)
    assert overview["channels"][0]["next_upload"]["title"] == "Eerder"
    assert overview["channels"][0]["next_upload"]["seconds_until"] == 28 * 60


async def test_multiple_channels_sorted_by_next_moment(session, owner):
    a = await _channel(session, owner, "YouTube Kanaal 1")
    b = await _channel(session, owner, "TikTok Kanaal 1", platform="tiktok")
    c = await _channel(session, owner, "Instagram Reels", platform="instagram")
    await _upload(session, owner, a, scheduled_at=NOW + timedelta(hours=1, minutes=13))
    await _upload(session, owner, b, scheduled_at=NOW + timedelta(minutes=28))
    await _upload(session, owner, c, scheduled_at=NOW + timedelta(hours=2, minutes=4))

    overview = await upload_service.schedule_overview(session, owner.id, NOW)
    assert [row["channel_name"] for row in overview["channels"]] == [
        "TikTok Kanaal 1",
        "YouTube Kanaal 1",
        "Instagram Reels",
    ]


async def test_channel_without_upload_says_so(session, owner):
    await _channel(session, owner, "YouTube Kanaal 3")
    overview = await upload_service.schedule_overview(session, owner.id, NOW)
    assert overview["channels"][0]["next_upload"] is None


async def test_expired_one_off_upload_is_overdue(session, owner):
    channel = await _channel(session, owner, "Kanaal")
    await _upload(session, owner, channel, scheduled_at=NOW - timedelta(minutes=5))

    overview = await upload_service.schedule_overview(session, owner.id, NOW)
    next_upload = overview["channels"][0]["next_upload"]
    assert next_upload["seconds_until"] == -300
    assert next_upload["overdue"] is True


async def test_recurring_upload_rolls_forward(session, owner):
    channel = await _channel(session, owner, "Kanaal")
    await _upload(
        session,
        owner,
        channel,
        scheduled_at=NOW - timedelta(hours=2),
        recurrence=UploadRecurrence.DAILY,
    )
    overview = await upload_service.schedule_overview(session, owner.id, NOW)
    next_upload = overview["channels"][0]["next_upload"]
    assert next_upload["seconds_until"] == 22 * 3600
    assert next_upload["overdue"] is False


def test_daily_recurrence_keeps_local_time_across_dst():
    """Zomertijd: 18:00 in Amsterdam blijft 18:00, ook al verschuift de UTC-tijd."""
    zone = ZoneInfo("Europe/Amsterdam")
    # Zaterdag 25 oktober 2025 18:00 lokaal; in de nacht erna gaat de klok terug.
    start = datetime(2025, 10, 25, 18, 0, tzinfo=zone).astimezone(timezone.utc)
    after = datetime(2025, 10, 25, 20, 0, tzinfo=zone).astimezone(timezone.utc)
    nxt = next_upload_occurrence(start, UploadRecurrence.DAILY, "Europe/Amsterdam", after)
    assert nxt is not None
    assert nxt.astimezone(zone).hour == 18


def test_unknown_timezone_falls_back_instead_of_crashing():
    start = datetime(2025, 9, 15, 10, 0, tzinfo=timezone.utc)
    after = datetime(2025, 9, 16, 9, 0, tzinfo=timezone.utc)
    nxt = next_upload_occurrence(start, UploadRecurrence.DAILY, "Mars/Olympus", after)
    assert nxt == datetime(2025, 9, 16, 10, 0, tzinfo=timezone.utc)


def test_one_off_upload_has_no_next_occurrence():
    start = datetime(2025, 9, 15, 10, 0, tzinfo=timezone.utc)
    after = datetime(2025, 9, 16, 9, 0, tzinfo=timezone.utc)
    assert next_upload_occurrence(start, UploadRecurrence.ONCE, "UTC", after) is None


async def test_channel_needing_reauth_is_flagged(session, owner):
    channel = await _channel(session, owner, "TikTok Kanaal 1", platform="tiktok")
    channel.status = ChannelStatus.REAUTH_REQUIRED
    await session.commit()

    overview = await upload_service.schedule_overview(session, owner.id, NOW)
    assert overview["channels"][0]["needs_reauth"] is True


async def test_cancelled_upload_disappears_from_the_schedule(session, owner):
    channel = await _channel(session, owner, "Kanaal")
    upload = await _upload(session, owner, channel)
    await upload_service.cancel_upload(session, owner.id, upload.id)
    await session.commit()

    overview = await upload_service.schedule_overview(session, owner.id, NOW)
    assert overview["channels"][0]["next_upload"] is None


async def test_completing_a_recurring_upload_plans_the_next_one(session, owner):
    channel = await _channel(session, owner, "Kanaal")
    upload = await _upload(
        session, owner, channel, recurrence=UploadRecurrence.DAILY,
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    await upload_service.set_status(session, owner.id, upload.id, UploadStatus.COMPLETED)
    await session.commit()

    uploads = await upload_service.list_uploads(session, owner.id, channel.id)
    statuses = sorted(item["status"] for item in uploads)
    assert statuses == ["completed", "scheduled"]


async def test_executing_an_upload_needs_confirmation(client, owner, session):
    channel = await _channel(session, owner, "Kanaal")
    upload = await _upload(session, owner, channel)

    without = await client.post(
        f"/uploads/{upload.id}/status",
        json={"status": "uploading"},
        headers=auth_headers(owner),
    )
    assert without.status_code == 428

    ok = await client.post(
        f"/uploads/{upload.id}/status",
        json={"status": "uploading"},
        headers=auth_headers(owner, confirm=True),
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "uploading"


async def test_scheduling_is_blocked_for_a_limited_tier(client, limited, owner, session):
    channel = await _channel(session, owner, "Kanaal")
    response = await client.post(
        "/uploads",
        json={"channel_id": channel.id, "scheduled_at": NOW.isoformat()},
        headers=auth_headers(limited),
    )
    assert response.status_code == 403


async def test_uploads_of_other_users_are_invisible(client, owner, trusted, session):
    channel = await _channel(session, owner, "Kanaal")
    upload = await _upload(session, owner, channel)
    response = await client.patch(
        f"/uploads/{upload.id}", json={"title": "Gekaapt"}, headers=auth_headers(trusted)
    )
    assert response.status_code == 404


async def test_every_upload_response_carries_the_countdown(client, owner, session):
    """Aanmaken, wijzigen en annuleren geven dezelfde velden als het schema."""
    channel = await _channel(session, owner, "Kanaal")
    when = datetime.now(timezone.utc) + timedelta(minutes=30)

    created = await client.post(
        "/uploads",
        json={"channel_id": channel.id, "title": "Nieuw", "scheduled_at": when.isoformat()},
        headers=auth_headers(owner),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["effective_at"] is not None
    assert 1700 < body["seconds_until"] <= 1800

    patched = await client.patch(
        f"/uploads/{body['id']}", json={"title": "Gewijzigd"}, headers=auth_headers(owner)
    )
    assert patched.json()["seconds_until"] is not None

    cancelled = await client.post(
        f"/uploads/{body['id']}/cancel", headers=auth_headers(owner)
    )
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["seconds_until"] is not None


async def test_timestamps_always_carry_a_timezone(client, owner, session):
    """SQLite levert naïeve tijden; de API mag ze nooit zo doorgeven."""
    channel = await _channel(session, owner, "Kanaal")
    await _upload(session, owner, channel, scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1))

    schedule = await client.get("/uploads/schedule", headers=auth_headers(owner))
    body = schedule.json()
    assert body["server_time"].endswith("Z") or "+00:00" in body["server_time"]
    moment = body["channels"][0]["next_upload"]["scheduled_at"]
    assert moment.endswith("Z") or "+00:00" in moment
