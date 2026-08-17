from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from datetime import UTC, datetime
from uuid import UUID

import httpx
from faststream import AckPolicy
from faststream.rabbit import RabbitBroker
from faststream.rabbit.annotations import RabbitMessage
from faststream.rabbit.schemas import Channel

from payment_service.broker import (
    PAYMENTS_EXCHANGE,
    PAYMENTS_QUEUE,
    PAYMENTS_QUEUE_NAME,
    PaymentCreatedMessage,
    declare_topology,
)
from payment_service.config import get_settings
from payment_service.db import session_factory
from payment_service.models import OutboxModel, PaymentModel
from payment_service.repositories import OutboxRepository, PaymentRepository

logger = logging.getLogger(__name__)
settings = get_settings()
broker = RabbitBroker(settings.rabbitmq_url, default_channel=Channel(prefetch_count=1))
http_client = httpx.AsyncClient(timeout=settings.webhook_timeout_seconds)


@broker.subscriber(PAYMENTS_QUEUE, exchange=PAYMENTS_EXCHANGE, ack_policy=AckPolicy.MANUAL)
async def consume(event: PaymentCreatedMessage, message: RabbitMessage) -> None:
    """One handler performs gateway processing, DB update and webhook delivery."""
    for attempt in range(1, settings.retry_attempts + 1):
        try:
            await process_one(event.payment_id)
        except Exception:
            logger.exception("Payment processing attempt %s failed", attempt)
            if attempt == settings.retry_attempts:
                await message.reject()
                return
            delay = settings.retry_base_delay_seconds * 2 ** (attempt - 1)
            await asyncio.sleep(delay)
        else:
            await message.ack()
            return


async def process_one(payment_id: UUID) -> None:
    async with session_factory() as session:
        payment = await PaymentRepository(session).get(payment_id)
    if payment is None:
        raise LookupError(f"Payment {payment_id} not found")
    if payment.webhook_delivered_at is not None:
        return

    if payment.status == "pending":
        await asyncio.sleep(
            random.uniform(
                settings.gateway_min_delay_seconds,
                settings.gateway_max_delay_seconds,
            )
        )
        status = "succeeded" if random.random() < settings.gateway_success_rate else "failed"
        async with session_factory() as session, session.begin():
            payment = await PaymentRepository(session).set_status(
                payment.id, status, datetime.now(UTC)
            )

    response = await http_client.post(payment.webhook_url, json=webhook_payload(payment))
    response.raise_for_status()
    async with session_factory() as session, session.begin():
        await PaymentRepository(session).mark_webhook_delivered(payment.id, datetime.now(UTC))


def webhook_payload(payment: PaymentModel) -> dict[str, object]:
    return {
        "event_type": "payment.processed",
        "payment_id": str(payment.id),
        "amount": str(payment.amount),
        "currency": payment.currency,
        "status": payment.status,
        "metadata": payment.metadata_,
        "processed_at": payment.processed_at.isoformat() if payment.processed_at else None,
    }


async def publish_event(event: OutboxModel) -> None:
    await broker.publish(
        event.payload,
        queue=PAYMENTS_QUEUE_NAME,
        exchange=PAYMENTS_EXCHANGE,
        routing_key=PAYMENTS_QUEUE_NAME,
        message_id=str(event.id),
        persist=True,
    )


async def publish_batch() -> int:
    async with session_factory() as session, session.begin():
        repository = OutboxRepository(session)
        events = await repository.lock_unpublished(settings.outbox_batch_size)
        for event in events:
            await publish_event(event)
            repository.mark_published(event, datetime.now(UTC))
    return len(events)


async def outbox_loop() -> None:
    while True:
        try:
            published = await publish_batch()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Outbox publication failed")
            published = 0
        if published == 0:
            await asyncio.sleep(settings.outbox_poll_interval_seconds)


async def run() -> None:
    logging.basicConfig(level=logging.INFO)
    await declare_topology(settings.rabbitmq_url)
    await broker.start()
    relay = asyncio.create_task(outbox_loop())
    try:
        await asyncio.Event().wait()
    finally:
        relay.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await relay
        await http_client.aclose()
        await broker.stop()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
