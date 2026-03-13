"""Unit tests for CacheFlight core behaviour."""

from __future__ import annotations

import asyncio

import pytest

from cacheflight import (
    CacheFlight,
    CacheFlightEvent,
    CacheFlightOptions,
    MaxKeysError,
    RunOptions,
    TimeoutError,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _collector() -> tuple[list[CacheFlightEvent], CacheFlightOptions]:
    """Return an event list and options wired to append to it."""
    events: list[CacheFlightEvent] = []
    opts = CacheFlightOptions(on_event=events.append)
    return events, opts


# ── Basic deduplication ───────────────────────────────────────────────────────

class TestDeduplication:
    async def test_same_key_returns_same_result(self) -> None:
        call_count = 0

        async def task() -> str:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return "value"

        flight = CacheFlight()
        results = await asyncio.gather(
            flight.run("k", task),
            flight.run("k", task),
            flight.run("k", task),
        )

        assert results == ["value", "value", "value"]
        assert call_count == 1

    async def test_different_keys_run_independently(self) -> None:
        calls: dict[str, int] = {}

        async def task(name: str) -> str:
            calls[name] = calls.get(name, 0) + 1
            await asyncio.sleep(0.02)
            return name

        flight = CacheFlight()
        a, b = await asyncio.gather(
            flight.run("a", lambda: task("a")),
            flight.run("b", lambda: task("b")),
        )

        assert a == "a" and b == "b"
        assert calls == {"a": 1, "b": 1}

    async def test_sequential_calls_execute_separately(self) -> None:
        call_count = 0

        async def task() -> int:
            nonlocal call_count
            call_count += 1
            return call_count

        flight = CacheFlight()
        first = await flight.run("k", task)
        second = await flight.run("k", task)

        assert first == 1
        assert second == 2
        assert call_count == 2


# ── Registry cleanup ─────────────────────────────────────────────────────────

class TestRegistryCleanup:
    async def test_cleanup_on_resolve(self) -> None:
        flight = CacheFlight()
        await flight.run("k", asyncio.coroutine(lambda: "ok")() if False else self._ok)
        assert not flight.has("k")
        assert flight.size == 0

    async def test_cleanup_on_reject(self) -> None:
        flight = CacheFlight()

        async def failing() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await flight.run("k", failing)

        assert not flight.has("k")
        assert flight.size == 0

    async def test_cleanup_on_timeout(self) -> None:
        flight = CacheFlight()

        async def slow() -> None:
            await asyncio.sleep(10)

        with pytest.raises(TimeoutError):
            await flight.run("k", slow, RunOptions(timeout_ms=50))

        assert not flight.has("k")

    @staticmethod
    async def _ok() -> str:
        return "ok"


# ── Timeout behaviour ────────────────────────────────────────────────────────

class TestTimeout:
    async def test_run_option_overrides_default(self) -> None:
        events, opts = _collector()
        opts = CacheFlightOptions(default_timeout_ms=5000, on_event=events.append)
        flight = CacheFlight(opts)

        async def slow() -> None:
            await asyncio.sleep(10)

        with pytest.raises(TimeoutError):
            await flight.run("k", slow, RunOptions(timeout_ms=50))

        timeout_events = [e for e in events if e.type == "task_timed_out"]
        assert len(timeout_events) == 1

    async def test_default_timeout_applies(self) -> None:
        flight = CacheFlight(CacheFlightOptions(default_timeout_ms=50))

        async def slow() -> None:
            await asyncio.sleep(10)

        with pytest.raises(TimeoutError):
            await flight.run("k", slow)

    async def test_no_timeout_when_unset(self) -> None:
        flight = CacheFlight()

        async def fast() -> str:
            await asyncio.sleep(0.01)
            return "done"

        result = await flight.run("k", fast)
        assert result == "done"


# ── max_keys ──────────────────────────────────────────────────────────────────

class TestMaxKeys:
    async def test_rejects_when_at_capacity(self) -> None:
        events, _ = _collector()
        flight = CacheFlight(CacheFlightOptions(max_keys=1, on_event=events.append))

        blocker = asyncio.Event()

        async def blocking() -> str:
            await blocker.wait()
            return "done"

        # First call occupies the slot
        t = asyncio.ensure_future(flight.run("a", blocking))
        await asyncio.sleep(0.01)  # let it register

        with pytest.raises(MaxKeysError):
            await flight.run("b", blocking)

        blocker.set()
        await t

        rejected = [e for e in events if e.type == "max_keys_rejected"]
        assert len(rejected) == 1


# ── Events ────────────────────────────────────────────────────────────────────

class TestEvents:
    async def test_hit_and_miss_events(self) -> None:
        events, opts = _collector()
        flight = CacheFlight(opts)

        async def task() -> str:
            await asyncio.sleep(0.03)
            return "v"

        await asyncio.gather(
            flight.run("k", task),
            flight.run("k", task),
        )

        types = [e.type for e in events]
        assert types.count("miss") == 1
        assert types.count("hit") == 1
        assert "task_started" in types
        assert "task_resolved" in types

    async def test_rejected_event_on_error(self) -> None:
        events, opts = _collector()
        flight = CacheFlight(opts)

        async def bad() -> None:
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            await flight.run("k", bad)

        types = [e.type for e in events]
        assert "task_rejected" in types


# ── has / size / clear ────────────────────────────────────────────────────────

class TestDiagnostics:
    async def test_has_and_size(self) -> None:
        flight = CacheFlight()
        blocker = asyncio.Event()

        async def blocking() -> str:
            await blocker.wait()
            return "x"

        t = asyncio.ensure_future(flight.run("k", blocking))
        await asyncio.sleep(0.01)

        assert flight.has("k")
        assert flight.size == 1

        blocker.set()
        await t

        assert not flight.has("k")
        assert flight.size == 0

    async def test_clear_cancels_waiters(self) -> None:
        flight = CacheFlight()

        async def forever() -> None:
            await asyncio.sleep(999)

        t = asyncio.ensure_future(flight.run("k", forever))
        await asyncio.sleep(0.01)

        flight.clear()
        assert flight.size == 0

        with pytest.raises(asyncio.CancelledError):
            await t

