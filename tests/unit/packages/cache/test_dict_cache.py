import pytest

from packages.cache import DictCache


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def cache(clock):
    return DictCache(clock=clock)


async def test_set_then_get_roundtrip(cache):
    await cache.set("k", "v")
    assert await cache.get("k") == "v"


async def test_get_missing_returns_none(cache):
    assert await cache.get("nope") is None


async def test_value_without_ttl_never_expires(cache, clock):
    await cache.set("k", "v")
    clock.advance(10_000)
    assert await cache.get("k") == "v"


async def test_get_returns_none_after_ttl_expires(cache, clock):
    await cache.set("k", "v", ttl_seconds=10)
    clock.advance(9)
    assert await cache.get("k") == "v"
    clock.advance(2)
    assert await cache.get("k") is None


async def test_set_overwrites_value_and_ttl(cache, clock):
    await cache.set("k", "old", ttl_seconds=10)
    await cache.set("k", "new")
    clock.advance(100)
    assert await cache.get("k") == "new"


async def test_delete_removes_key(cache):
    await cache.set("k", "v")
    await cache.delete("k")
    assert await cache.get("k") is None


async def test_delete_is_idempotent(cache):
    await cache.delete("missing")
    await cache.delete("missing")
    assert await cache.get("missing") is None


async def test_incr_starts_at_one_and_increments(cache):
    assert await cache.incr("hits") == 1
    assert await cache.incr("hits") == 2
    assert await cache.incr("hits") == 3
    assert await cache.get("hits") == "3"


async def test_incr_with_ttl_expires_and_restarts(cache, clock):
    assert await cache.incr("rate", ttl_seconds=60) == 1
    assert await cache.incr("rate", ttl_seconds=60) == 2
    clock.advance(61)
    assert await cache.get("rate") is None
    assert await cache.incr("rate", ttl_seconds=60) == 1


async def test_incr_ttl_only_set_on_first_call(cache, clock):
    await cache.incr("rate", ttl_seconds=60)
    clock.advance(30)
    await cache.incr("rate", ttl_seconds=60)
    clock.advance(31)
    assert await cache.get("rate") is None


async def test_incr_after_plain_set(cache):
    await cache.set("k", "5")
    assert await cache.incr("k") == 6
