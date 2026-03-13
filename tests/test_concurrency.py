"""Concurrency and stress tests for CacheFlight."""

from __future__ import annotations

import asyncio

from cacheflight import CacheFlight


class TestConcurrency:
    async def test_100_concurrent_same_key_single_execution(self) -> None:
        """100+ simultaneous callers for one key → task runs exactly once."""
        call_count = 0

        async def expensive() -> str:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return "result"

        flight = CacheFlight()
        results = await asyncio.gather(
            *(flight.run("shared", expensive) for _ in range(150))
        )

        assert all(r == "result" for r in results)
        assert call_count == 1

    async def test_mixed_keys_independent(self) -> None:
        """Different keys dedupe independently."""
        counts: dict[str, int] = {}

        async def work(key: str) -> str:
            counts[key] = counts.get(key, 0) + 1
            await asyncio.sleep(0.03)
            return key

        flight = CacheFlight()
        keys = ["a", "b", "c"]
        coros = []
        for key in keys:
            for _ in range(20):
                coros.append(flight.run(key, lambda k=key: work(k)))

        results = await asyncio.gather(*coros)

        for key in keys:
            assert counts[key] == 1
            assert results.count(key) == 20

    async def test_repeated_bursts_no_stale_entries(self) -> None:
        """Repeated burst cycles leave no stale registry entries."""
        flight = CacheFlight()

        async def task() -> str:
            await asyncio.sleep(0.01)
            return "ok"

        for _ in range(10):
            await asyncio.gather(*(flight.run("burst", task) for _ in range(50)))

        assert flight.size == 0

    async def test_burst_1000_requests(self) -> None:
        """1000-request burst with bounded key set completes without error."""
        call_counts: dict[str, int] = {}

        async def work(key: str) -> str:
            call_counts[key] = call_counts.get(key, 0) + 1
            await asyncio.sleep(0.02)
            return key

        flight = CacheFlight()
        keys = [f"key:{i % 10}" for i in range(1000)]
        results = await asyncio.gather(
            *(flight.run(k, lambda k=k: work(k)) for k in keys)
        )

        assert len(results) == 1000
        # Each unique key should have been executed exactly once per burst
        for key in set(keys):
            assert call_counts[key] == 1
        assert flight.size == 0

    async def test_error_propagates_to_all_waiters(self) -> None:
        """When task fails, all concurrent waiters receive the same exception."""
        flight = CacheFlight()

        async def failing() -> None:
            await asyncio.sleep(0.02)
            raise ValueError("shared failure")

        tasks = [flight.run("fail", failing) for _ in range(20)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        assert all(isinstance(r, ValueError) for r in results)
        assert flight.size == 0

