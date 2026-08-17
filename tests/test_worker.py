from typing import Any
from uuid import uuid4

import pytest

from payment_service import worker
from payment_service.broker import PaymentCreatedMessage
from payment_service.models import OutboxModel


class FakeMessage:
    def __init__(self) -> None:
        self.acks = 0
        self.rejects = 0

    async def ack(self) -> None:
        self.acks += 1

    async def reject(self) -> None:
        self.rejects += 1


def event() -> PaymentCreatedMessage:
    return PaymentCreatedMessage(
        event_id=uuid4(),
        event_type="payment.created",
        payment_id=uuid4(),
        occurred_at="2026-08-17T12:00:00Z",
    )


@pytest.mark.asyncio
async def test_consumer_acknowledges_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def success(*args: object) -> None:
        del args

    monkeypatch.setattr(worker, "process_one", success)
    message = FakeMessage()

    await worker.consume(event(), message)  # type: ignore[arg-type]

    assert message.acks == 1
    assert message.rejects == 0


@pytest.mark.asyncio
async def test_consumer_rejects_after_three_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    async def failure(*args: object) -> None:
        nonlocal attempts
        del args
        attempts += 1
        raise RuntimeError("temporary failure")

    async def no_sleep(*args: object) -> None:
        del args

    monkeypatch.setattr(worker, "process_one", failure)
    monkeypatch.setattr(worker.asyncio, "sleep", no_sleep)
    message = FakeMessage()

    await worker.consume(event(), message)  # type: ignore[arg-type]

    assert attempts == 3
    assert message.acks == 0
    assert message.rejects == 1


@pytest.mark.asyncio
async def test_outbox_event_is_published_as_persistent_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, dict[str, Any]]] = []

    async def publish(payload: object, **kwargs: Any) -> None:
        calls.append((payload, kwargs))

    monkeypatch.setattr(worker.broker, "publish", publish)
    outbox = OutboxModel(
        id=uuid4(),
        payment_id=uuid4(),
        event_type="payment.created",
        payload={"payment_id": str(uuid4())},
    )

    await worker.publish_event(outbox)

    assert calls[0][0] == outbox.payload
    assert calls[0][1]["persist"] is True
    assert calls[0][1]["routing_key"] == "payments.new"
