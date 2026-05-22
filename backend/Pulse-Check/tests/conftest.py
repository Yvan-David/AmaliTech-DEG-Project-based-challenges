"""
conftest.py — Shared fixtures for all tests.

FakeRedis replaces the real Redis/Upstash connection so tests:
  • run offline with no credentials
  • are fully isolated (each test gets a fresh store)
  • are fast (no network round-trips)

fakeredis mirrors the upstash-redis / redis-py API exactly,
so RedisStore needs zero changes to work with it.
"""

import pytest
import fakeredis
from httpx import ASGITransport, AsyncClient

from app.store.redis_store import RedisStore
from app.services import monitor_service as svc
from app.main import app


@pytest.fixture(autouse=True)
def fresh_store():
    """
    Give every test its own isolated in-memory Redis.
    autouse=True means this runs automatically for every test.
    """
    fake_client = fakeredis.FakeRedis()
    store = RedisStore(fake_client)
    svc.init(store)
    yield store
    fake_client.flushall()


@pytest.fixture
async def client():
    """ASGI test client — no real server needed."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
