from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import httpx
from faststream import AckPolicy
from faststream.rabbit import RabbitBroker
from faststream.rabbit.annotations import RabbitMessage

from payment_service.application.clock import UtcClock
from payment_service.application.retry import RetryDecision, RetryPolicy
from payment_service.application.services import ProcessPaymentService
from payment_service.core.config import get_settings
from payment_service.core.logging import configure_logging
from payment_service.domain.exceptions import PaymentNotFoundError, PaymentProcessingBusyError
from payment_service.infrastructure.broker.messages import PaymentCreatedMessage
from payment_service.infrastructure.broker.topology import (
    ATTEMPT_HEADER,
    CONSUMER_CHANNEL,
    PAYMENTS_EXCHANGE,
    PAYMENTS_QUEUE,
    RETRY_EXCHANGE,
    RETRY_QUEUES,
    declare_topology,
)
from payment_service.infrastructure.db.payment_store import SqlAlchemyPaymentProcessingStore
from payment_service.infrastructure.db.session import session_factory
from payment_service.infrastructure.gateway import SimulatedPaymentGateway
from payment_service.infrastructure.webhook import HttpWebhookSender

logger = logging.getLogger(__name__)
settings = get_settings()
broker = RabbitBroker(settings.rabbitmq_url, default_channel=CONSUMER_CHANNEL)
http_client = httpx.AsyncClient(timeout=settings.webhook_timeout_seconds)
retry_policy = RetryPolicy((settings.retry_delay_1_seconds, settings.retry_delay_2_seconds))
processing_store = SqlAlchemyPaymentProcessingStore(session_factory)
service = ProcessPaymentService(
    processing_store,
    SimulatedPaymentGateway(
        min_delay_seconds=settings.gateway_min_delay_seconds,
        max_delay_seconds=settings.gateway_max_delay_seconds,
        success_rate=settings.gateway_success_rate,
    ),
    HttpWebhookSender(http_client),
    UtcClock(),
    processing_lease_seconds=settings.processing_lease_seconds,
)


@broker.subscriber(
    PAYMENTS_QUEUE,
    exchange=PAYMENTS_EXCHANGE,
    ack_policy=AckPolicy.MANUAL,
)
async def process_payment(event: PaymentCreatedMessage, message: RabbitMessage) -> None:
    try:
        payment = await service.execute(event.payment_id)
    except PaymentProcessingBusyError:
        logger.info(
            "Payment is already claimed; redelivery was delayed",
            extra={"payment_id": str(event.payment_id), "event_id": str(event.event_id)},
        )
        await schedule_retry(
            event,
            message,
            delay_seconds=settings.retry_delay_1_seconds,
            next_attempt=None,
        )
        return
    except Exception as exc:
        logger.exception(
            "Payment message processing failed",
            extra={
                "payment_id": str(event.payment_id),
                "event_id": str(event.event_id),
            },
        )
        if isinstance(exc, PaymentNotFoundError):
            attempt = fallback_attempt(message.headers)
            if attempt is None:
                logger.error(
                    "Message has an invalid retry header and will be dead-lettered",
                    extra={"payment_id": str(event.payment_id), "event_id": str(event.event_id)},
                )
                await message.reject()
                return
        else:
            try:
                attempt = await processing_store.record_failure(event.payment_id)
            except Exception:
                logger.exception(
                    "Could not persist processing failure; original message will be requeued",
                    extra={"payment_id": str(event.payment_id), "event_id": str(event.event_id)},
                )
                await message.nack()
                return
        await handle_failure(event, message, attempt)
        return

    await message.ack()
    logger.info(
        "Payment message processed",
        extra={
            "payment_id": str(payment.id),
            "event_id": str(event.event_id),
        },
    )


def fallback_attempt(headers: Mapping[str, Any]) -> int | None:
    raw_attempt = headers.get(ATTEMPT_HEADER, 1)
    if isinstance(raw_attempt, bool):
        return None
    try:
        attempt = int(raw_attempt)
    except (TypeError, ValueError):
        return None
    if not 1 <= attempt <= retry_policy.max_attempts:
        return None
    return attempt


async def handle_failure(
    event: PaymentCreatedMessage,
    message: RabbitMessage,
    attempt: int,
) -> None:
    result = retry_policy.after_failure(attempt)
    if result.decision is RetryDecision.DEAD_LETTER:
        await message.reject()
        logger.error(
            "Payment message moved to DLQ",
            extra={
                "payment_id": str(event.payment_id),
                "event_id": str(event.event_id),
                "attempt": attempt,
            },
        )
        return

    if result.delay_seconds is None:
        raise RuntimeError("Retry policy returned no delay for a retry decision")
    await schedule_retry(
        event,
        message,
        delay_seconds=result.delay_seconds,
        next_attempt=attempt + 1,
    )


async def schedule_retry(
    event: PaymentCreatedMessage,
    message: RabbitMessage,
    *,
    delay_seconds: int,
    next_attempt: int | None,
) -> None:
    retry_queue = RETRY_QUEUES[delay_seconds]
    headers: dict[str, Any] | None = (
        {ATTEMPT_HEADER: next_attempt} if next_attempt is not None else None
    )
    try:
        await broker.publish(
            event.model_dump(mode="json"),
            queue=retry_queue,
            exchange=RETRY_EXCHANGE,
            routing_key=retry_queue,
            headers=headers,
            message_id=str(event.event_id),
            message_type=event.event_type,
            persist=True,
            mandatory=True,
        )
    except Exception:
        logger.exception(
            "Could not schedule retry; original message will be requeued",
            extra={"event_id": str(event.event_id), "attempt": next_attempt},
        )
        await message.nack()
        return
    await message.ack()
    logger.warning(
        "Payment message scheduled for retry",
        extra={
            "payment_id": str(event.payment_id),
            "event_id": str(event.event_id),
            "attempt": next_attempt,
        },
    )


async def run() -> None:
    configure_logging(settings.log_level)
    await declare_topology(settings.rabbitmq_url)
    await broker.start()
    logger.info("Payment consumer started")
    try:
        await asyncio.Event().wait()
    finally:
        await http_client.aclose()
        await broker.stop()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
