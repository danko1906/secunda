from dataclasses import dataclass
from enum import StrEnum


class RetryDecision(StrEnum):
    RETRY = "retry"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True, slots=True)
class RetryResult:
    decision: RetryDecision
    delay_seconds: int | None


class RetryPolicy:
    """Three total attempts when initialized with two backoff delays."""

    def __init__(self, retry_delays_seconds: tuple[int, ...]) -> None:
        if not retry_delays_seconds or any(delay <= 0 for delay in retry_delays_seconds):
            raise ValueError("Retry delays must contain positive values")
        self._delays = retry_delays_seconds

    @property
    def max_attempts(self) -> int:
        return len(self._delays) + 1

    def after_failure(self, attempt: int) -> RetryResult:
        if attempt < 1:
            raise ValueError("Attempt number starts at 1")
        if attempt >= self.max_attempts:
            return RetryResult(RetryDecision.DEAD_LETTER, None)
        return RetryResult(RetryDecision.RETRY, self._delays[attempt - 1])
