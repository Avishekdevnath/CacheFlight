"""Type definitions for CacheFlight."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Union

# ── Event types ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HitEvent:
    type: Literal["hit"] = field(default="hit", init=False)
    key: str = ""


@dataclass(frozen=True)
class MissEvent:
    type: Literal["miss"] = field(default="miss", init=False)
    key: str = ""


@dataclass(frozen=True)
class TaskStartedEvent:
    type: Literal["task_started"] = field(default="task_started", init=False)
    key: str = ""


@dataclass(frozen=True)
class TaskResolvedEvent:
    type: Literal["task_resolved"] = field(default="task_resolved", init=False)
    key: str = ""
    duration_ms: float = 0.0


@dataclass(frozen=True)
class TaskRejectedEvent:
    type: Literal["task_rejected"] = field(default="task_rejected", init=False)
    key: str = ""
    duration_ms: float = 0.0
    error: BaseException | None = None


@dataclass(frozen=True)
class TaskTimedOutEvent:
    type: Literal["task_timed_out"] = field(default="task_timed_out", init=False)
    key: str = ""
    duration_ms: float = 0.0


@dataclass(frozen=True)
class MaxKeysRejectedEvent:
    type: Literal["max_keys_rejected"] = field(default="max_keys_rejected", init=False)
    key: str = ""


@dataclass(frozen=True)
class TaskCancelledEvent:
    type: Literal["task_cancelled"] = field(default="task_cancelled", init=False)
    key: str = ""
    duration_ms: float = 0.0


CacheFlightEvent = Union[
    HitEvent,
    MissEvent,
    TaskStartedEvent,
    TaskResolvedEvent,
    TaskRejectedEvent,
    TaskTimedOutEvent,
    MaxKeysRejectedEvent,
    TaskCancelledEvent,
]

EventCallback = Callable[[CacheFlightEvent], None]


# ── Option containers ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CacheFlightOptions:
    """Options for the CacheFlight instance."""

    max_keys: int | None = None
    default_timeout_ms: float | None = None
    on_event: EventCallback | None = None


@dataclass(frozen=True)
class RunOptions:
    """Per-call options passed to ``CacheFlight.run()``."""

    timeout_ms: float | None = None
    metadata: dict[str, Any] | None = None

