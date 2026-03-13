"""Core CacheFlight implementation."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Optional, TypeVar

from cacheflight.errors import CancelledError, MaxKeysError, TimeoutError
from cacheflight.types import (
    CacheFlightOptions,
    EventCallback,
    HitEvent,
    MaxKeysRejectedEvent,
    MissEvent,
    RunOptions,
    TaskCancelledEvent,
    TaskRejectedEvent,
    TaskResolvedEvent,
    TaskStartedEvent,
    TaskTimedOutEvent,
)

T = TypeVar("T")


class _InflightEntry:
    """Tracks a single in-flight key: its shared future, worker task, and waiters."""

    __slots__ = ("future", "worker", "waiters")

    def __init__(
        self,
        future: asyncio.Future[Any],
        worker: asyncio.Task[None],
        waiters: int,
    ) -> None:
        self.future = future
        self.worker = worker
        self.waiters = waiters


class CacheFlight:
    """In-process async request deduplication.

    Prevents duplicate expensive async work by sharing a single in-flight
    future per key among all concurrent callers.

    Example::

        flight = CacheFlight()

        async def get_user(user_id: str):
            return await flight.run(
                f"user:{user_id}",
                lambda: db.fetch_user(user_id),
            )
    """

    def __init__(self, options: Optional[CacheFlightOptions] = None) -> None:
        opts = options or CacheFlightOptions()
        self._max_keys: Optional[int] = opts.max_keys
        self._default_timeout_ms: Optional[float] = opts.default_timeout_ms
        self._on_event: Optional[EventCallback] = opts.on_event
        self._registry: dict[str, _InflightEntry] = {}

    # ── Public API ────────────────────────────────────────────────────────

    async def run(
        self,
        key: str,
        task: Callable[[], Awaitable[T]],
        options: Optional[RunOptions] = None,
    ) -> T:
        """Execute *task* for *key*, deduplicating concurrent calls.

        If another call for the same *key* is already in-flight, all callers
        share the same result (or exception).

        Supports caller cancellation: if all waiters cancel, the underlying
        task is also cancelled and the registry entry is cleaned up.
        """
        # HIT — return the existing in-flight future
        existing = self._registry.get(key)
        if existing is not None and existing.future.done():
            self._registry.pop(key, None)
            existing = None
        if existing is not None:
            existing.waiters += 1
            self._emit(HitEvent(key=key))
            return await self._await_entry(key, existing)

        # MISS — check capacity
        self._emit(MissEvent(key=key))

        if self._max_keys is not None and len(self._registry) >= self._max_keys:
            self._emit(MaxKeysRejectedEvent(key=key))
            raise MaxKeysError(key, self._max_keys)

        # Resolve effective timeout
        timeout_ms = (
            options.timeout_ms if options and options.timeout_ms is not None
            else self._default_timeout_ms
        )

        # Create a future that all waiters will share
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()

        self._emit(TaskStartedEvent(key=key))
        started_at = time.monotonic()

        # Schedule the actual work as a cancellable task
        worker = asyncio.ensure_future(
            self._execute(key, task, future, timeout_ms, started_at)
        )
        entry = _InflightEntry(future, worker, waiters=1)
        self._registry[key] = entry

        return await self._await_entry(key, entry)

    def has(self, key: str) -> bool:
        """Return ``True`` if *key* is currently in-flight."""
        return key in self._registry

    @property
    def size(self) -> int:
        """Return the number of in-flight keys."""
        return len(self._registry)

    def clear(self) -> None:
        """Cancel all in-flight entries and clear the registry.

        Waiters will receive an ``asyncio.CancelledError``.
        """
        for key, entry in list(self._registry.items()):
            self._cancel_entry(key, entry, cancel_future=True)

    def cancel(self, key: str) -> bool:
        """Cancel a specific in-flight key.

        Returns ``True`` if the key was found and cancelled, ``False`` otherwise.
        """
        entry = self._registry.get(key)
        if entry is None:
            return False
        self._cancel_entry(key, entry, cancel_future=False)
        return True

    # ── Internals ─────────────────────────────────────────────────────────
    async def _await_entry(self, key: str, entry: _InflightEntry) -> T:
        cancelled = False
        try:
            return await asyncio.shield(entry.future)
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            entry.waiters -= 1
            if cancelled and entry.waiters == 0 and not entry.future.done():
                self._cancel_entry(key, entry, cancel_future=False)

    def _cancel_entry(
        self, key: str, entry: _InflightEntry, *, cancel_future: bool
    ) -> None:
        entry.worker.cancel()
        if cancel_future and not entry.future.done():
            entry.future.cancel()
        self._registry.pop(key, None)

    async def _execute(
        self,
        key: str,
        task: Callable[[], Awaitable[T]],
        future: asyncio.Future[T],
        timeout_ms: Optional[float],
        started_at: float,
    ) -> None:
        """Run the task and resolve the shared future."""
        try:
            timeout_sec = timeout_ms / 1000.0 if timeout_ms is not None else None
            result = await asyncio.wait_for(task(), timeout=timeout_sec)
            duration_ms = (time.monotonic() - started_at) * 1000
            if not future.done():
                future.set_result(result)
            self._emit(TaskResolvedEvent(key=key, duration_ms=duration_ms))
        except asyncio.TimeoutError:
            duration_ms = (time.monotonic() - started_at) * 1000
            err = TimeoutError(key, timeout_ms or 0)
            if not future.done():
                future.set_exception(err)
            self._emit(TaskTimedOutEvent(key=key, duration_ms=duration_ms))
        except asyncio.CancelledError:
            duration_ms = (time.monotonic() - started_at) * 1000
            if not future.done():
                future.set_exception(CancelledError(key))
            self._emit(TaskCancelledEvent(key=key, duration_ms=duration_ms))
        except BaseException as exc:
            duration_ms = (time.monotonic() - started_at) * 1000
            if not future.done():
                future.set_exception(exc)
            self._emit(TaskRejectedEvent(key=key, duration_ms=duration_ms, error=exc))
        finally:
            self._registry.pop(key, None)

    def _emit(self, event: Any) -> None:
        if self._on_event is not None:
            self._on_event(event)

