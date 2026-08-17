import pytest

from payment_service.application.retry import RetryDecision, RetryPolicy


@pytest.mark.parametrize(
    ("attempt", "decision", "delay"),
    [
        (1, RetryDecision.RETRY, 2),
        (2, RetryDecision.RETRY, 4),
        (3, RetryDecision.DEAD_LETTER, None),
    ],
)
def test_retry_policy_has_three_total_attempts(
    attempt: int, decision: RetryDecision, delay: int | None
) -> None:
    result = RetryPolicy((2, 4)).after_failure(attempt)

    assert result.decision is decision
    assert result.delay_seconds == delay
