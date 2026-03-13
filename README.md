# CacheFlight

**In-process async request deduplication for Python.**

Prevent duplicate expensive async work under concurrent load. When many callers request the same key simultaneously, CacheFlight ensures the task executes **once** and shares the result with all waiters.

> **v1 scope:** single-process deduplication only. This is not a distributed lock or a persistent cache.

## How It Works

Without CacheFlight, N concurrent callers for the same resource each independently start their own task:

```
Caller A ──► task() ──► result
Caller B ──► task() ──► result   (duplicate work!)
Caller C ──► task() ──► result   (duplicate work!)
```

With CacheFlight, the first caller starts the task; all others join as waiters. All receive the same result when it resolves:

```
Caller A ──► task() ─────────────► result
Caller B ──►  (waits)  ──────────► same result   (no duplicate work)
Caller C ──►  (waits)  ──────────► same result   (no duplicate work)
```

The in-flight entry is cleaned up immediately after the task resolves or rejects — CacheFlight stores nothing at rest. It is purely a concurrency coalescer, not a cache.

## Installation

```bash
pip install cacheflight
```

## Setup & Try the Examples

### 1. Clone and install

```bash
git clone https://github.com/cacheflight/cacheflight-python.git
cd cacheflight-python

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

### 2. Run the tests

```bash
pytest -v
```

### 3. Try the FastAPI example

```bash
pip install fastapi uvicorn
uvicorn examples.fastapi_example:app --reload
```

Then fire concurrent requests to see deduplication in action:

```bash
# Linux / macOS
for i in $(seq 1 50); do curl -s http://localhost:8000/user/42 & done; wait

# PowerShell
1..50 | ForEach-Object -Parallel { Invoke-RestMethod http://localhost:8000/user/42 }
```

Check `/stats` — `total_db_calls` will be `1` regardless of how many requests were fired.

### 4. Try the aiohttp example

```bash
pip install aiohttp
python examples/aiohttp_example.py
# Server runs on http://localhost:8080
```

### 5. Run the benchmarks

```bash
python -m benchmarks.benchmark
```

## Quick Start

```python
import asyncio
from cacheflight import CacheFlight

flight = CacheFlight()

async def get_user(user_id: str) -> dict:
    return await flight.run(
        f"user:{user_id}",
        lambda: fetch_user_from_db(user_id),
    )

# 100 concurrent calls for the same user → 1 DB query
results = await asyncio.gather(*(get_user("42") for _ in range(100)))
```

## API

### `CacheFlight(options?)`

Create an instance with optional configuration:

| Option | Type | Default | Description |
|---|---|---|---|
| `max_keys` | `int \| None` | `None` | Safety cap on concurrent in-flight keys |
| `default_timeout_ms` | `float \| None` | `None` | Fallback timeout for all `run()` calls |
| `on_event` | `Callable \| None` | `None` | Callback for observability events |

```python
from cacheflight import CacheFlight, CacheFlightOptions

flight = CacheFlight(CacheFlightOptions(
    max_keys=10_000,
    default_timeout_ms=5000,
    on_event=lambda e: print(e.type, e.key),
))
```

### `await flight.run(key, task, options?)`

Execute `task` for `key`, deduplicating concurrent calls.

- **key** (`str`): Canonical identifier for the work.
- **task** (`Callable[[], Awaitable[T]]`): Async callable that does the expensive work.
- **options** (`RunOptions`): Per-call overrides (`timeout_ms`, `metadata`).

Cancellation semantics:
- If a single caller cancels, other waiters still receive the result.
- If all waiters cancel, the underlying task is cancelled and the entry is cleaned up.

```python
from cacheflight import RunOptions

result = await flight.run(
    "report:daily",
    generate_report,
    RunOptions(timeout_ms=10_000),
)
```

### `flight.has(key) -> bool`

Check if a key is currently in-flight.

### `flight.size -> int`

Number of active in-flight keys.

### `flight.clear()`

Cancel all in-flight entries. Waiters receive `asyncio.CancelledError`.

### `flight.cancel(key) -> bool`

Cancel a specific in-flight key. Returns `True` if a key was cancelled, `False` if the key was not found.

```python
import asyncio
from cacheflight import CacheFlight, CancelledError

flight = CacheFlight()

async def example():
    # Start a slow task in the background
    task = asyncio.create_task(
        flight.run("report:daily", generate_report)
    )

    await asyncio.sleep(0.1)  # let it start

    # Cancel it — all waiters will receive CancelledError
    cancelled = flight.cancel("report:daily")
    print(f"Cancelled: {cancelled}")  # True

    try:
        await task
    except CancelledError:
        print("Task was cancelled as expected")
```

## Events

Subscribe via `on_event` for observability:

| Event Type | Fields | When |
|---|---|---|
| `hit` | `key` | Caller joined existing in-flight entry |
| `miss` | `key` | New task started |
| `task_started` | `key` | Task execution began |
| `task_resolved` | `key`, `duration_ms` | Task completed successfully |
| `task_rejected` | `key`, `duration_ms`, `error` | Task raised an exception |
| `task_timed_out` | `key`, `duration_ms` | Task exceeded timeout |
| `task_cancelled` | `key`, `duration_ms` | Task was cancelled |
| `max_keys_rejected` | `key` | Key rejected due to `max_keys` cap |

## Exceptions

| Exception | When |
|---|---|
| `cacheflight.TimeoutError` | Task exceeds `timeout_ms` |
| `cacheflight.MaxKeysError` | In-flight registry at `max_keys` capacity |
| `cacheflight.CancelledError` | Underlying task cancelled (e.g., `cancel()` or all waiters cancel) |

## Key Design Guidelines

Good keys are **deterministic** and include **all parameters that affect the result**:

```python
# Good: includes all result-shaping inputs
key = f"user:{user_id}:locale:{locale}:role:{role}"

# Bad: non-deterministic or missing context
key = f"user:{user_id}"  # locale/role changes give wrong cached result
```

- Prefix with domain (`user:`, `report:`, `search:`)
- Never put secrets or PII in plain-text keys
- Hash long payloads to cap key size

## Limitations

- **Single-process only** — no cross-instance deduplication without a distributed coordination layer.
- **Not a cache** — CacheFlight deduplicates in-flight execution; it does not store results.
- **Set timeouts** for unreliable downstream dependencies.

## Observability and Metrics (Suggested)

Typical event-to-metric mapping:
- `hit` -> `cacheflight_hit_total` (counter)
- `miss` -> `cacheflight_miss_total` (counter)
- `task_rejected` -> `cacheflight_error_total` (counter)
- `task_timed_out` -> `cacheflight_timeout_total` (counter)
- `task_cancelled` -> `cacheflight_cancelled_total` (counter)
- `max_keys_rejected` -> `cacheflight_max_keys_rejected_total` (counter)
- `task_resolved` -> `cacheflight_task_duration_ms` (histogram)
- `flight.size` -> `cacheflight_active_keys` (gauge)

Alerting ideas:
- sustained `task_timed_out` ratio above baseline for 5+ minutes
- `max_keys_rejected_total` > 0 (capacity pressure)
- `cacheflight_active_keys` at or above 80% of `max_keys` for >10 minutes

## Security and Redaction

Never log raw keys or metadata that can include secrets or PII. Hash or redact before emitting.

```python
import hashlib
from cacheflight import CacheFlight, CacheFlightOptions

def on_event_safe(event):
    key_hash = hashlib.sha256(event.key.encode()).hexdigest()[:12]
    print(event.type, key_hash)

flight = CacheFlight(CacheFlightOptions(on_event=on_event_safe))
```

## Benchmarks

Run the benchmark script and record environment details as described in `benchmarks/README.md`:

```bash
python -m benchmarks.benchmark
```

## Anti-Patterns

- Using non-canonical keys (e.g., `json.dumps` on unsorted dicts)
- Treating CacheFlight as persistent cache storage
- Omitting timeout for unreliable dependencies
- Expecting cross-instance deduplication

## License

MIT

