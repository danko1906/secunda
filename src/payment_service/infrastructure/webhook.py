from uuid import NAMESPACE_URL, uuid5

import httpx

from payment_service.domain.entities import Payment
from payment_service.domain.exceptions import WebhookDeliveryError


def webhook_event_id(payment: Payment) -> str:
    return str(uuid5(NAMESPACE_URL, f"payment.processed:{payment.id}"))


class HttpWebhookSender:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def send(self, payment: Payment) -> None:
        event_id = webhook_event_id(payment)
        payload = {
            "event_id": event_id,
            "event_type": "payment.processed",
            "occurred_at": (
                payment.processed_at.isoformat() if payment.processed_at is not None else None
            ),
            "data": {
                "payment_id": str(payment.id),
                "amount": str(payment.amount),
                "currency": payment.currency.value,
                "status": payment.status.value,
                "metadata": payment.metadata,
            },
        }
        try:
            response = await self._client.post(
                payment.webhook_url,
                json=payload,
                headers={"X-Webhook-Event-Id": event_id},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise WebhookDeliveryError(f"Webhook delivery failed: {exc}") from exc
