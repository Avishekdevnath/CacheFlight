"""Load test script — demonstrates CacheFlight deduplication.

Fires many concurrent requests for the same cities and shows that
only a few actual API calls were made.

Usage:
    1. Start the server:  uvicorn server:app --port 8000
    2. Run this script:   python load_test.py
"""

from __future__ import annotations

import asyncio
import time

try:
    import httpx
except ImportError:
    raise ImportError("Install httpx first: pip install httpx")


BASE_URL = "http://localhost:8000"
CITIES = ["london", "tokyo", "new-york", "paris", "sydney", "mumbai"]
REQUESTS_PER_CITY = 10  # 10 concurrent requests per city = 60 total


async def fetch(client: httpx.AsyncClient, city: str, req_id: int) -> dict:
    resp = await client.get(f"{BASE_URL}/weather/{city}")
    resp.raise_for_status()
    return {"city": city, "req_id": req_id, "data": resp.json()}


async def main() -> None:
    print("=" * 60)
    print("CacheFlight Load Test")
    print("=" * 60)
    print(f"\nFiring {len(CITIES) * REQUESTS_PER_CITY} concurrent requests")
    print(f"  {len(CITIES)} cities x {REQUESTS_PER_CITY} requests each\n")

    async with httpx.AsyncClient(timeout=30) as client:
        # Build all tasks — all cities, multiple concurrent requests each
        tasks = [
            fetch(client, city, i)
            for city in CITIES
            for i in range(REQUESTS_PER_CITY)
        ]

        start = time.perf_counter()
        results = await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - start

    # Gather results per city
    by_city: dict[str, list[dict]] = {}
    for r in results:
        by_city.setdefault(r["city"], []).append(r["data"])

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    for city, responses in sorted(by_city.items()):
        api_calls = {r["api_call_number"] for r in responses}
        print(f"\n  {city}:")
        print(f"    Requests sent:  {len(responses)}")
        print(f"    API calls used: {len(api_calls)} (call #{', #'.join(str(c) for c in sorted(api_calls))})")
        print(f"    All got same result: {len(set(r['fetched_at'] for r in responses)) == 1}")

    # Fetch metrics
    async with httpx.AsyncClient() as client:
        metrics = (await client.get(f"{BASE_URL}/metrics")).json()

    print(f"\n{'=' * 60}")
    print("SERVER METRICS")
    print(f"{'=' * 60}")
    print(f"  Total requests served:    {metrics['total_requests_served']}")
    print(f"  Actual API calls made:    {metrics['actual_api_calls']}")
    print(f"  Deduplicated (free):      {metrics['deduplicated_requests']}")
    print(f"  Latency saved:            {metrics['estimated_latency_saved_ms']:.0f}ms")
    print(f"  Wall-clock time:          {elapsed * 1000:.0f}ms")
    print(f"\n  Deduplication ratio:      {metrics['deduplicated_requests']}/{metrics['total_requests_served']} requests shared results")
    print()


if __name__ == "__main__":
    asyncio.run(main())
