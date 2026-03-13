"""CacheFlight benchmark script.

Measures the deduplication effectiveness and overhead of CacheFlight
under various concurrency scenarios.

Usage:
    python -m benchmarks.benchmark

Methodology:
    - Each scenario fires N concurrent requests for a simulated async task.
    - "Without CacheFlight" executes every request independently.
    - "With CacheFlight" deduplicates same-key requests.
    - Metrics: total task executions, wall-clock time, per-request latency (p50/p95).

Environment should be documented alongside results:
    - CPU, RAM, OS
    - Python version
    - asyncio event loop implementation
"""

from __future__ import annotations

import asyncio
import platform
import statistics
import sys
import time


async def simulated_task(latency_sec: float = 0.04) -> str:
    """Simulate an expensive async operation (e.g., DB query)."""
    await asyncio.sleep(latency_sec)
    return "result"


# ── Without CacheFlight ──────────────────────────────────────────────────────

async def bench_without(
    num_requests: int, same_key_ratio: float, task_latency: float
) -> dict[str, object]:
    call_count = 0

    async def task() -> str:
        nonlocal call_count
        call_count += 1
        return await simulated_task(task_latency)

    timings: list[float] = []

    async def timed_call() -> None:
        start = time.monotonic()
        await task()
        timings.append((time.monotonic() - start) * 1000)

    wall_start = time.monotonic()
    await asyncio.gather(*(timed_call() for _ in range(num_requests)))
    wall_ms = (time.monotonic() - wall_start) * 1000

    timings.sort()
    return {
        "task_executions": call_count,
        "wall_clock_ms": round(wall_ms, 2),
        "p50_ms": round(statistics.median(timings), 2),
        "p95_ms": round(timings[int(len(timings) * 0.95)], 2),
    }


# ── With CacheFlight ─────────────────────────────────────────────────────────

async def bench_with(
    num_requests: int, same_key_ratio: float, task_latency: float
) -> dict[str, object]:
    from cacheflight import CacheFlight

    flight = CacheFlight()
    call_count = 0

    async def task() -> str:
        nonlocal call_count
        call_count += 1
        return await simulated_task(task_latency)

    num_same = int(num_requests * same_key_ratio)
    num_unique = num_requests - num_same

    timings: list[float] = []

    async def timed_call(key: str) -> None:
        start = time.monotonic()
        await flight.run(key, task)
        timings.append((time.monotonic() - start) * 1000)

    calls = [timed_call("shared") for _ in range(num_same)]
    calls += [timed_call(f"unique:{i}") for i in range(num_unique)]

    wall_start = time.monotonic()
    await asyncio.gather(*calls)
    wall_ms = (time.monotonic() - wall_start) * 1000

    timings.sort()
    return {
        "task_executions": call_count,
        "wall_clock_ms": round(wall_ms, 2),
        "p50_ms": round(statistics.median(timings), 2),
        "p95_ms": round(timings[int(len(timings) * 0.95)], 2),
    }


# ── Scenarios ─────────────────────────────────────────────────────────────────

SCENARIOS = [
    {"name": "High dedupe (95% same key)", "requests": 1000, "same_key_ratio": 0.95, "task_latency": 0.04},
    {"name": "Medium dedupe (50% same key)", "requests": 1000, "same_key_ratio": 0.50, "task_latency": 0.04},
    {"name": "No dedupe (all unique)", "requests": 500, "same_key_ratio": 0.0, "task_latency": 0.04},
    {"name": "Burst (5000 req, 95% same)", "requests": 5000, "same_key_ratio": 0.95, "task_latency": 0.04},
]


async def main() -> None:
    print("=" * 72)
    print("CacheFlight Benchmark")
    print("=" * 72)
    print(f"Python:   {sys.version}")
    print(f"Platform: {platform.platform()}")
    print(f"CPU:      {platform.processor() or 'N/A'}")
    print("=" * 72)

    for scenario in SCENARIOS:
        name = scenario["name"]
        n = scenario["requests"]
        ratio = scenario["same_key_ratio"]
        latency = scenario["task_latency"]

        print(f"\n--- {name} ---")
        print(f"    Requests: {n}, Same-key ratio: {ratio:.0%}, Task latency: {latency*1000:.0f}ms")

        without = await bench_without(n, ratio, latency)
        with_cf = await bench_with(n, ratio, latency)

        reduction = (
            (1 - with_cf["task_executions"] / without["task_executions"]) * 100
            if without["task_executions"] > 0
            else 0
        )

        print(f"    Without CacheFlight: {without['task_executions']} executions, "
              f"wall={without['wall_clock_ms']}ms, p50={without['p50_ms']}ms, p95={without['p95_ms']}ms")
        print(f"    With CacheFlight:    {with_cf['task_executions']} executions, "
              f"wall={with_cf['wall_clock_ms']}ms, p50={with_cf['p50_ms']}ms, p95={with_cf['p95_ms']}ms")
        print(f"    Reduction:           {reduction:.1f}%")

    print("\n" + "=" * 72)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())

