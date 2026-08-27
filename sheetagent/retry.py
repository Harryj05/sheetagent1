"""Retry with exponential backoff for flaky actions (COM startup, Sheets API 5xx)."""
from __future__ import annotations

import logging
import time
from typing import Callable, Iterable, TypeVar

log = logging.getLogger("sheetagent.retry")
T = TypeVar("T")


class RetryExhausted(RuntimeError):
    def __init__(self, attempts: int, last: BaseException):
        super().__init__(f"failed after {attempts} attempt(s): {last}")
        self.attempts = attempts
        self.last = last


def with_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    backoff: float = 2.0,
    max_delay: float = 15.0,
    retry_on: Iterable[type[BaseException]] = (Exception,),
    give_up_on: Iterable[type[BaseException]] = (),
    label: str = "operation",
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``fn`` until it succeeds or attempts run out.

    ``give_up_on`` short-circuits errors that will never fix themselves
    (a missing credentials file is not worth three tries).
    """
    retry_on = tuple(retry_on)
    give_up_on = tuple(give_up_on)
    delay = initial_delay
    last: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except give_up_on as exc:  # type: ignore[misc]
            log.error("%s: unrecoverable, not retrying", label,
                      extra={"label": label, "error": str(exc)})
            raise
        except retry_on as exc:  # type: ignore[misc]
            last = exc
            if attempt == max_attempts:
                break
            log.warning(
                "%s failed (attempt %d/%d), retrying in %.1fs: %s",
                label, attempt, max_attempts, delay, exc,
                extra={"label": label, "attempt": attempt, "delay": delay,
                       "error": str(exc)},
            )
            sleep(delay)
            delay = min(delay * backoff, max_delay)

    assert last is not None
    raise RetryExhausted(max_attempts, last)
