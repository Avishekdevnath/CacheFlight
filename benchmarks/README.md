# CacheFlight Benchmarks

This directory contains the benchmark script and a standard format for recording results.

## Run

```bash
python -m benchmarks.benchmark
```

## Environment Metadata (Record with Results)

- CPU model
- RAM
- OS and version
- Python version (`python -V`)
- Event loop implementation (default asyncio, uvloop, etc.)

## Scenarios (Current)

- High dedupe (95% same key), 1000 requests, 40ms task latency
- Medium dedupe (50% same key), 1000 requests, 40ms task latency
- No dedupe (all unique), 500 requests, 40ms task latency
- Burst (5000 requests, 95% same key), 40ms task latency

## Output Format (Standard)

```
Scenario: High dedupe (95% same key)
Requests: 1000, Same-key ratio: 95%, Task latency: 40ms
Without CacheFlight: 1000 executions, wall=123.45ms, p50=40.12ms, p95=45.67ms
With CacheFlight:    51 executions, wall=55.67ms, p50=41.02ms, p95=44.90ms
Reduction:           94.9%
```

## Notes

- Do not publish percentage claims without capturing the environment metadata.
- Re-run benchmarks after any change that affects concurrency, cancellation, or timeouts.
