"""Soak / long-running stress tests for CacheFlight.

These tests verify memory stability and correctness over sustained workloads.
Run separately from unit tests for CI nightly builds:

    pytest tests/test_soak.py -v --timeout=120
"""

from __future__ import annotations

import asyncio
import random

import pytest

from cacheflight import CacheFlight, CacheFlightOptions


class TestSoak:
    @pytest.mark.slow
    async def test_sustained_burst_cycles(self) -> None:
        """Run 100 burst cycles with rotating keys — no stale entries, no leaks."""
        flight = CacheFlight(CacheFlightOptions(max_keys=500))

        async def task(key: str) -> str:
            await asyncio.sleep(random.uniform(0.001, 0.01))
            return key

        for cycle in range(100):
            keys = [f"key:{cycle}:{i % 20}" for i in range(100)]
            await asyncio.gather(
                *(flight.run(k, lambda k=k: task(k)) for k in keys)
            )

        assert flight.size == 0

    @pytest.mark.slow
    async def test_mixed_success_and_failure(self) -> None:
        """Sustained mix of success/failure — registry always cleans up."""
        flight = CacheFlight()
        errors = 0

        async def maybe_fail(key: str) -> str:
            await asyncio.sleep(random.uniform(0.001, 0.005))
            if random.random() < 0.3:
                raise RuntimeError(f"fail:{key}")
            return key

        for cycle in range(50):
            keys = [f"k:{cycle}:{i % 10}" for i in range(50)]
            results = await asyncio.gather(
                *(flight.run(k, lambda k=k: maybe_fail(k)) for k in keys),
                return_exceptions=True,
            )
            errors += sum(1 for r in results if isinstance(r, Exception))

        assert flight.size == 0
        assert errors > 0  # confirms failures actually happened

    @pytest.mark.slow
    async def test_timeout_under_sustained_load(self) -> None:
        """Timeouts under sustained load don't leak registry entries."""
        flight = CacheFlight(CacheFlightOptions(default_timeout_ms=50))

        async def slow() -> str:
            await asyncio.sleep(random.uniform(0.01, 0.2))
            return "ok"

        for cycle in range(30):
            keys = [f"t:{cycle}:{i % 5}" for i in range(30)]
            await asyncio.gather(
                *(flight.run(k, slow) for k in keys),
                return_exceptions=True,
            )

        assert flight.size == 0

    @pytest.mark.slow
    async def test_high_cardinality_keys(self) -> None:
        """10k unique keys in rapid succession — all clean up."""
        flight = CacheFlight()

        async def task() -> str:
            await asyncio.sleep(0.001)
            return "v"

        # Process in batches to avoid overwhelming the event loop
        for batch in range(10):
            keys = [f"hc:{batch}:{i}" for i in range(1000)]
            await asyncio.gather(*(flight.run(k, task) for k in keys))

        assert flight.size == 0

