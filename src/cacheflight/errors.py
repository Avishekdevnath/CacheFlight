"""CacheFlight exception hierarchy."""


class CacheFlightError(Exception):
    """Base exception for CacheFlight."""


class TimeoutError(CacheFlightError):
    """Raised when a task exceeds its allowed execution time."""

    def __init__(self, key: str, timeout_ms: float) -> None:
        self.key = key
        self.timeout_ms = timeout_ms
        super().__init__(f"CacheFlight task for key '{key}' timed out after {timeout_ms}ms")


class MaxKeysError(CacheFlightError):
    """Raised when the in-flight registry has reached its ``max_keys`` cap."""

    def __init__(self, key: str, max_keys: int) -> None:
        self.key = key
        self.max_keys = max_keys
        super().__init__(
            f"CacheFlight max_keys limit ({max_keys}) reached; rejecting key '{key}'"
        )


class CancelledError(CacheFlightError):
    """Raised when an in-flight task is cancelled."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"CacheFlight task for key '{key}' was cancelled")
