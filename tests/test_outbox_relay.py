from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from payment_service.infrastructure.db.models import OutboxModel
from payment_service.workers import outbox_relay


@pytest.mark.asyncio
async def test_outbox_publish_is_persistent_mandatory_and_identified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, dict[str, Any]]] = []

    async def publish(payload: object, **kwargs: Any) -> None:
        calls.append((payload, kwargs))

    monkeypatch.setattr(outbox_relay.broker, "publish", publish)
    event = OutboxModel(
        id=uuid4(),
        aggregate_id=uuid4(),
        event_type="payment.created",
        payload={"payment_id": str(uuid4())},
    )

    await outbox_relay.publish_event(event)

    assert calls == [
        (
            event.payload,
            {
                "queue": "payments.new",
                "exchange": outbox_relay.PAYMENTS_EXCHANGE,
                "routing_key": "payments.new",
                "message_id": str(event.id),
                "message_type": "payment.created",
                "persist": True,
                "mandatory": True,
            },
        )
    ]


@pytest.mark.asyncio
async def test_outbox_publish_propagates_broker_confirmation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def publish(*args: object, **kwargs: Any) -> None:
        del args, kwargs
        raise RuntimeError("message was returned")

    monkeypatch.setattr(outbox_relay.broker, "publish", publish)
    event = OutboxModel(
        id=uuid4(),
        aggregate_id=uuid4(),
        event_type="payment.created",
        payload={},
    )

    with pytest.raises(RuntimeError, match="message was returned"):
        await outbox_relay.publish_event(event)
