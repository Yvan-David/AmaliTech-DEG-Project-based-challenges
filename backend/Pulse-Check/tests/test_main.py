"""
tests/test_main.py

Full test coverage for the Pulse-Check API (Redis edition).

Strategy:
  - Uses FakeRedis via conftest.py — no real Redis or Upstash needed.
  - Tests only the HTTP surface (status codes, response bodies, state via GET).
    No direct inspection of svc._monitors or svc._tasks — those don't exist.
  - Timer expiry tests use timeout=1 with a 1.5s sleep for scheduling margin.
  - Email and webhook calls are mocked so no real network calls are made.
"""

import asyncio
from unittest.mock import patch, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import monitor_service as svc

# ── Shared payloads ────────────────────────────────────────────────────────────

BASE = {
    "id": "device-123",
    "timeout": 60,
    "alert_email": "admin@critmon.com",
}

SHORT = {
    "id": "device-fast",
    "timeout": 1,
    "alert_email": "admin@critmon.com",
}

WITH_WEBHOOK = {
    **BASE,
    "webhook_url": "https://hooks.example.com/alert",
}


# ── Health ─────────────────────────────────────────────────────────────────────

# ── POST /monitors ─────────────────────────────────────────────────────────────

async def test_register_returns_201(client):
    res = await client.post("/monitors", json=BASE)
    assert res.status_code == 201
    body = res.json()
    assert body["monitor_id"] == "device-123"
    assert body["status"] == "active"
    assert "expires_at" in body


async def test_register_persists_monitor(client):
    await client.post("/monitors", json=BASE)
    res = await client.get("/monitors/device-123")
    assert res.status_code == 200
    assert res.json()["id"] == "device-123"


async def test_register_stores_webhook_url(client):
    await client.post("/monitors", json=WITH_WEBHOOK)
    res = await client.get("/monitors/device-123")
    assert res.json()["webhook_url"] == "https://hooks.example.com/alert"


async def test_register_duplicate_replaces_monitor(client):
    await client.post("/monitors", json=BASE)
    res = await client.post("/monitors", json=BASE)
    assert res.status_code == 201
    assert "replaced" in res.json()["message"]


async def test_register_invalid_timeout_rejected(client):
    res = await client.post("/monitors", json={**BASE, "timeout": 0})
    assert res.status_code == 422


async def test_register_missing_fields_rejected(client):
    res = await client.post("/monitors", json={"id": "device-123"})
    assert res.status_code == 422


# ── POST /monitors/{id}/heartbeat ─────────────────────────────────────────────

async def test_heartbeat_returns_200(client):
    await client.post("/monitors", json=BASE)
    res = await client.post("/monitors/device-123/heartbeat")
    assert res.status_code == 200
    assert res.json()["status"] == "active"


async def test_heartbeat_updates_last_heartbeat(client):
    await client.post("/monitors", json=BASE)
    assert svc.get_one("device-123").last_heartbeat is None
    await client.post("/monitors/device-123/heartbeat")
    assert svc.get_one("device-123").last_heartbeat is not None


async def test_heartbeat_resets_timer(client):
    """TTL should be close to full timeout after heartbeat."""
    await client.post("/monitors", json=BASE)
    await asyncio.sleep(2)
    await client.post("/monitors/device-123/heartbeat")
    ttl = svc.get_ttl("device-123")
    # TTL should be reset to near 60, not near 58
    assert ttl > 55


async def test_heartbeat_nonexistent_returns_404(client):
    res = await client.post("/monitors/ghost/heartbeat")
    assert res.status_code == 404


# ── POST /monitors/{id}/pause ─────────────────────────────────────────────────

async def test_pause_returns_200_and_paused_status(client):
    await client.post("/monitors", json=BASE)
    res = await client.post("/monitors/device-123/pause")
    assert res.status_code == 200
    assert res.json()["status"] == "paused"


async def test_pause_persists_status(client):
    await client.post("/monitors", json=BASE)
    await client.post("/monitors/device-123/pause")
    res = await client.get("/monitors/device-123")
    assert res.json()["status"] == "paused"


async def test_pause_prevents_alert(client):
    """Timer gone but monitor paused — watcher must NOT fire alert."""
    with patch("app.watcher.send_alert_email") as mock_email:
        await client.post("/monitors", json=SHORT)
        await client.post("/monitors/device-fast/pause")
        await asyncio.sleep(1.5)
        mock_email.assert_not_called()

    res = await client.get("/monitors/device-fast")
    assert res.json()["status"] == "paused"


async def test_pause_already_paused_is_idempotent(client):
    await client.post("/monitors", json=BASE)
    await client.post("/monitors/device-123/pause")
    res = await client.post("/monitors/device-123/pause")
    assert res.status_code == 200   # no error


async def test_pause_nonexistent_returns_404(client):
    res = await client.post("/monitors/ghost/pause")
    assert res.status_code == 404


async def test_heartbeat_unpauses_monitor(client):
    """Heartbeat on a paused monitor must set it back to active."""
    await client.post("/monitors", json=BASE)
    await client.post("/monitors/device-123/pause")
    res = await client.post("/monitors/device-123/heartbeat")
    assert res.status_code == 200
    assert res.json()["status"] == "active"
    assert svc.get_one("device-123").status == "active"


# ── GET /monitors/{id} ────────────────────────────────────────────────────────

async def test_get_existing_monitor(client):
    await client.post("/monitors", json=BASE)
    res = await client.get("/monitors/device-123")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == "device-123"
    assert body["timeout"] == 60



async def test_get_nonexistent_returns_404(client):
    res = await client.get("/monitors/ghost")
    assert res.status_code == 404


# ── GET /monitors ─────────────────────────────────────────────────────────────

async def test_list_monitors_empty(client):
    res = await client.get("/monitors")
    assert res.status_code == 200
    assert res.json() == []


async def test_list_monitors_returns_all(client):
    await client.post("/monitors", json=BASE)
    await client.post("/monitors", json={**BASE, "id": "device-456"})
    res = await client.get("/monitors")
    assert len(res.json()) == 2


# ── DELETE /monitors/{id} ─────────────────────────────────────────────────────

async def test_delete_monitor(client):
    await client.post("/monitors", json=BASE)
    res = await client.delete("/monitors/device-123")
    assert res.status_code == 204
    assert svc.get_one("device-123") is None


async def test_delete_nonexistent_returns_404(client):
    res = await client.delete("/monitors/ghost")
    assert res.status_code == 404


async def test_delete_prevents_alert(client):
    """Deleting a monitor before expiry must stop the alert from firing."""
    with patch("app.watcher.send_alert_email") as mock_email:
        await client.post("/monitors", json=SHORT)
        await client.delete("/monitors/device-fast")
        await asyncio.sleep(1.5)
        mock_email.assert_not_called()


async def test_re_register_after_down_reactivates(client):
    """Re-registering a downed device resets it to active."""
    with patch("app.watcher.send_alert_email"):
        await client.post("/monitors", json=SHORT)
        await asyncio.sleep(1.5)
    res = await client.post("/monitors", json=SHORT)
    assert res.status_code == 201
    assert res.json()["status"] == "active"
