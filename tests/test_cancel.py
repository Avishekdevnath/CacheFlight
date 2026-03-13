"""Tests for caller-abort / cancellation support."""

from __future__ import annotations

import asyncio

import pytest

from cacheflight import CacheFlight, CancelledError


class TestCallerAbort:
    async def test_cancel_specific_key(self) -> None:
        """cancel() cancels a specific in-flight key."""
        flight = CacheFlight()

        async def forever() -> None:
            await asyncio.sleep(999)

        t = asyncio.ensure_future(flight.run("k", forever))
        await asyncio.sleep(0.01)

        assert flight.cancel("k") is True
        assert flight.size == 0

        with pytest.raises(CancelledError):
            await t

    async def test_cancel_nonexistent_key(self) -> None:
        """cancel() returns False for keys not in-flight."""
        flight = CacheFlight()
        assert flight.cancel("nope") is False

    async def test_cancel_does_not_affect_other_keys(self) -> None:
        """Cancelling one key leaves others in-flight."""
        flight = CacheFlight()
        blocker = asyncio.Event()

        async def blocking() -> str:
            await blocker.wait()
            return "done"

        t_a = asyncio.ensure_future(flight.run("a", blocking))
        t_b = asyncio.ensure_future(flight.run("b", blocking))
        await asyncio.sleep(0.01)

        flight.cancel("a")
        assert not flight.has("a")
        assert flight.has("b")

        blocker.set()
        result_b = await t_b
        assert result_b == "done"

        with pytest.raises(CancelledError):
            await t_a

    async def test_one_waiter_cancel_does_not_cancel_worker(self) -> None:
        """If one waiter cancels, other waiters still get the result."""
        flight = CacheFlight()
        started = asyncio.Event()
        worker_cancelled = asyncio.Event()

        async def task() -> str:
            started.set()
            try:
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                worker_cancelled.set()
                raise
            return "ok"

        t1 = asyncio.create_task(flight.run("k", task))
        t2 = asyncio.create_task(flight.run("k", task))
        await started.wait()

        t1.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t1

        result = await t2
        assert result == "ok"
        assert not worker_cancelled.is_set()

    async def test_all_waiters_cancel_cancels_worker(self) -> None:
        """If all waiters cancel, the worker is cancelled and entry cleaned."""
        flight = CacheFlight()
        started = asyncio.Event()
        worker_cancelled = asyncio.Event()

        async def task() -> str:
            started.set()
            try:
                await asyncio.sleep(999)
            except asyncio.CancelledError:
                worker_cancelled.set()
                raise
            return "never"

        t1 = asyncio.create_task(flight.run("k", task))
        t2 = asyncio.create_task(flight.run("k", task))
        await started.wait()

        t1.cancel()
        t2.cancel()

        results = await asyncio.gather(t1, t2, return_exceptions=True)
        assert all(isinstance(r, asyncio.CancelledError) for r in results)

        await asyncio.wait_for(worker_cancelled.wait(), timeout=1.0)
        assert not flight.has("k")

    async def test_no_stale_entries_after_cancel(self) -> None:
        """Registry is clean after cancel, new calls start fresh."""
        flight = CacheFlight()
        call_count = 0

        async def task() -> str:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return "ok"

        # Start and cancel
        t = asyncio.ensure_future(flight.run("k", task))
        await asyncio.sleep(0.01)
        flight.cancel("k")
        with pytest.raises(CancelledError):
            await t

        # Fresh call should work
        result = await flight.run("k", task)
        assert result == "ok"
        assert call_count == 2
        assert flight.size == 0

    async def test_clear_cancels_all_waiters(self) -> None:
        """clear() cancels all in-flight entries."""
        flight = CacheFlight()

        async def forever() -> None:
            await asyncio.sleep(999)

        tasks = [
            asyncio.ensure_future(flight.run(f"k{i}", forever))
            for i in range(5)
        ]
        await asyncio.sleep(0.01)
        assert flight.size == 5

        flight.clear()
        assert flight.size == 0

        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(
            isinstance(r, (CancelledError, asyncio.CancelledError))
            for r in results
        )
