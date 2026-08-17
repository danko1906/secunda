from __future__ import annotations

from dataclasses import replace

import httpx
import pytest
from tests.unit.fakes import FakeClock, make_payment

from payment_service.domain.enums import PaymentStatus
from payment_service.domain.exceptions import WebhookDeliveryError
from payment_service.infrastructure.webhook import HttpWebhookSender, webhook_event_id


@pytest.mark.asyncio
async def test_webhook_has_stable_event_id_and_payment_result() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    payment = replace(
        make_payment(),
        status=PaymentStatus.SUCCEEDED,
        processed_at=FakeClock.NOW,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sender = HttpWebhookSender(client)
        await sender.send(payment)
        await sender.send(payment)

    assert len(requests) == 2
    expected_id = webhook_event_id(payment)
    assert requests[0].headers["X-Webhook-Event-Id"] == expected_id
    assert requests[1].headers["X-Webhook-Event-Id"] == expected_id
    assert b'"status":"succeeded"' in requests[0].content


@pytest.mark.asyncio
async def test_non_2xx_webhook_response_is_retriable_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sender = HttpWebhookSender(client)
        with pytest.raises(WebhookDeliveryError):
            await sender.send(make_payment())
