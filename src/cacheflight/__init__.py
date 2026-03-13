"""CacheFlight — In-process async request deduplication."""

from cacheflight.core import CacheFlight
from cacheflight.errors import CacheFlightError, CancelledError, MaxKeysError, TimeoutError
from cacheflight.types import CacheFlightEvent, CacheFlightOptions, RunOptions

__all__ = [
    "CacheFlight",
    "CacheFlightError",
    "CacheFlightEvent",
    "CacheFlightOptions",
    "CancelledError",
    "MaxKeysError",
    "RunOptions",
    "TimeoutError",
]

__version__ = "1.0.0"

