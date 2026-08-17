from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from payment_service.domain.exceptions import PaymentNotFoundError, PaymentProcessingBusyError
from payment_service.infrastructure.broker.messages import PaymentCreatedMessage
from payment_service.infrastructure.broker.topology import CONSUMER_CHANNEL, OUTBOX_CHANNEL
from payment_service.workers import consumer


class FailingService:
    async def execute(self, payment_id: UUID) -> None:
        del payment_id
        raise RuntimeError("gateway unavailable")


class BusyService:
    async def execute(self, payment_id: UUID) -> None:
        raise PaymentProcessingBusyError(payment_id)


class MissingPaymentService:
    async def execute(self, payment_id: UUID) -> None:
        raise PaymentNotFoundError(payment_id)


class FailureStore:
    def __init__(self) -> None:
        self.failures = 0

    async def record_failure(self, payment_id: UUID) -> int:
        del payment_id
        self.failures += 1
        return self.failures


class FakeMessage:
    def __init__(self, headers: dict[str, Any] | None = None) -> None:
        self.acks = 0
        self.nacks = 0
        self.rejects = 0
        self.headers = headers or {}

    async def ack(self) -> None:
        self.acks += 1

    async def nack(self) -> None:
        self.nacks += 1

    async def reject(self) -> None:
        self.rejects += 1


def message() -> PaymentCreatedMessage:
    return PaymentCreatedMessage(
        event_id=uuid4(),
        event_type="payment.created",
        payment_id=uuid4(),
        occurred_at="2026-01-02T12:00:00Z",
    )


def test_rabbit_channels_confirm_routes_and_bound_consumer_concurrency() -> None:
    assert OUTBOX_CHANNEL.publisher_confirms is True
    assert OUTBOX_CHANNEL.on_return_raises is True
    assert CONSUMER_CHANNEL.publisher_confirms is True
    assert CONSUMER_CHANNEL.on_return_raises is True
    assert CONSUMER_CHANNEL.prefetch_count == 1


@pytest.mark.parametrize("value", [0, 4, True, "not-a-number", object()])
def test_invalid_fallback_attempt_header_is_rejected(value: object) -> None:
    assert consumer.fallback_attempt({"x-attempt": value}) is None


@pytest.mark.parametrize(("value", "expected"), [(None, 1), ("2", 2), (3, 3)])
def test_fallback_attempt_header_is_bounded(value: object, expected: int) -> None:
    headers = {} if value is None else {"x-attempt": value}
    assert consumer.fallback_attempt(headers) == expected


@pytest.mark.asyncio
async def test_busy_duplicate_is_delayed_without_spending_failure_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure_store = FailureStore()
    published = 0

    async def publish(*args: object, **kwargs: Any) -> None:
        nonlocal published
        del args, kwargs
        published += 1

    monkeypatch.setattr(consumer, "service", BusyService())
    monkeypatch.setattr(consumer, "processing_store", failure_store)
    monkeypatch.setattr(consumer.broker, "publish", publish)
    delivery = FakeMessage()

    await consumer.process_payment(message(), delivery)  # type: ignore[arg-type]

    assert published == 1
    assert failure_store.failures == 0
    assert delivery.acks == 1


@pytest.mark.asyncio
async def test_missing_payment_with_invalid_attempt_header_goes_to_dlq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(consumer, "service", MissingPaymentService())
    delivery = FakeMessage(headers={"x-attempt": "corrupt"})

    await consumer.process_payment(message(), delivery)  # type: ignore[arg-type]

    assert delivery.rejects == 1
    assert delivery.acks == 0
    assert delivery.nacks == 0


@pytest.mark.asyncio
async def test_duplicate_messages_share_persistent_three_failure_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure_store = FailureStore()
    published: list[dict[str, Any]] = []

    async def publish(*args: object, **kwargs: Any) -> None:
        del args
        published.append(kwargs)

    monkeypatch.setattr(consumer, "service", FailingService())
    monkeypatch.setattr(consumer, "processing_store", failure_store)
    monkeypatch.setattr(consumer.broker, "publish", publish)
    event = message()
    deliveries = [FakeMessage(), FakeMessage(), FakeMessage()]

    for delivery in deliveries:
        await consumer.process_payment(event, delivery)  # type: ignore[arg-type]

    assert failure_store.failures == 3
    assert len(published) == 2
    assert [delivery.acks for delivery in deliveries] == [1, 1, 0]
    assert [delivery.rejects for delivery in deliveries] == [0, 0, 1]
