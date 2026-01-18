from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, Optional, TypeVar

from googleapiclient.errors import HttpError

from kaiano import logger as logger_mod

log = logger_mod.get_logger()

T = TypeVar("T")


@dataclass(frozen=True)
class RetryConfig:
    """Retry/backoff settings for Google API calls.

    Notes:
    - `max_retries` is the canonical field.
    - `max_attempts` is accepted as a backward/ergonomic alias and mapped to `max_retries`.
    """

    max_retries: int = 8
    base_delay_s: float = 1.0
    max_delay_s: float = 60.0

    # Optional alias for ergonomics / backwards compatibility
    max_attempts: Optional[int] = None

    def __post_init__(self) -> None:
        # Backward/ergonomic alias: allow callers to pass max_attempts.
        if self.max_attempts is not None:
            object.__setattr__(self, "max_retries", int(self.max_attempts))

        # Defensive clamping: keep config sane and avoid surprising behavior.
        # (We clamp instead of raising to keep retry helpers low-friction.)
        if self.max_retries < 1:
            object.__setattr__(self, "max_retries", 1)

        if self.base_delay_s <= 0:
            object.__setattr__(self, "base_delay_s", 0.1)

        if self.max_delay_s <= 0:
            object.__setattr__(self, "max_delay_s", 0.1)

        # Ensure max_delay_s is not smaller than base_delay_s.
        if self.max_delay_s < self.base_delay_s:
            object.__setattr__(self, "max_delay_s", float(self.base_delay_s))


def _http_status(error: HttpError) -> Optional[int]:
    return getattr(getattr(error, "resp", None), "status", None)


def is_retryable_http_error(error: HttpError) -> bool:
    """Return True when the error is likely transient.

    We intentionally keep this conservative: retry only on transient/server
    issues and rate/quota signals.
    """

    status = _http_status(error)
    msg = str(error).lower()

    # Transient server errors
    if isinstance(status, int) and 500 <= status <= 599:
        return True

    # Too many requests
    if status == 429:
        return True

    # Timeouts
    if status == 408:
        return True

    # Some quota / rate-limit errors come back as 403 with message hints
    if status == 403 and any(
        s in msg
        for s in [
            "quota",
            "rate limit",
            "ratelimit",
            "user-rate",
            "backenderror",
        ]
    ):
        return True

    return False


def _sleep_with_backoff(
    *, delay_s: float, max_delay_s: float, attempt: int, context: str
) -> None:
    # exponential backoff with jitter (0.7x–1.3x)
    wait = min(max_delay_s, delay_s) * (0.7 + random.random() * 0.6)
    log.warning(
        f"⚠️ Retryable Google API error while {context}; retrying in {wait:.1f}s "
        f"(attempt {attempt})"
    )
    time.sleep(wait)


def execute_with_retry(
    fn: Callable[[], T],
    *,
    context: str,
    retry: RetryConfig | None = None,
) -> T:
    """Execute a Google API call with consistent retry/backoff."""

    retry = retry or RetryConfig()
    delay = retry.base_delay_s
    last_error: Exception | None = None

    for attempt in range(1, retry.max_retries + 1):
        try:
            return fn()

        except HttpError as e:
            last_error = e
            if (not is_retryable_http_error(e)) or attempt == retry.max_retries:
                log.error(
                    f"❌ Google API HttpError while {context} "
                    f"(attempt {attempt}/{retry.max_retries}): {e}"
                )
                raise

            _sleep_with_backoff(
                delay_s=delay,
                max_delay_s=retry.max_delay_s,
                attempt=attempt,
                context=context,
            )
            delay *= 2

        except Exception as e:
            # Non-HTTP exceptions: don’t retry endlessly.
            last_error = e
            log.error(f"❌ Non-HTTP error while {context}: {e}")
            raise

    # Defensive: should be unreachable
    if last_error:
        raise last_error
    raise RuntimeError(f"Unknown error while {context}")
