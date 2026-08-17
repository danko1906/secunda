from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from faststream.rabbit import RabbitBroker
from sqlalchemy import or_, select

from payment_service.application.clock import UtcClock
from payment_service.core.config import get_settings
from payment_service.core.logging import configure_logging
from payment_service.infrastructure.broker.topology import (
    OUTBOX_CHANNEL,
    PAYMENTS_EXCHANGE,
    PAYMENTS_QUEUE_NAME,
    declare_topology,
)
from payment_service.infrastructure.db.models import OutboxModel
from payment_service.infrastructure.db.session import session_factory

logger = logging.getLogger(__name__)
settings = get_settings()
clock = UtcClock()
broker = RabbitBroker(settings.rabbitmq_url, default_channel=OUTBOX_CHANNEL)


async def publish_event(event: OutboxModel) -> None:
    await broker.publish(
        event.payload,
        queue=PAYMENTS_QUEUE_NAME,
        exchange=PAYMENTS_EXCHANGE,
        routing_key=PAYMENTS_QUEUE_NAME,
        message_id=str(event.id),
        message_type=event.event_type,
        persist=True,
        mandatory=True,
    )


async def publish_batch() -> int:
    now = clock.now()
    statement = (
        select(OutboxModel)
        .where(
            OutboxModel.published_at.is_(None),
            or_(OutboxModel.next_attempt_at.is_(None), OutboxModel.next_attempt_at <= now),
        )
        .order_by(OutboxModel.created_at)
        .limit(settings.outbox_batch_size)
        .with_for_update(skip_locked=True)
    )
    published = 0
    async with session_factory() as session, session.begin():
        events = list((await session.scalars(statement)).all())
        for event in events:
            try:
                await publish_event(event)
            except Exception as exc:
                event.attempts += 1
                delay = min(2 ** min(event.attempts, 6), 60)
                event.next_attempt_at = now + timedelta(seconds=delay)
                event.last_error = str(exc)[:2000]
                logger.exception(
                    "Outbox publication failed",
                    extra={"event_id": str(event.id), "attempt": event.attempts},
                )
                continue
            event.published_at = now
            event.last_error = None
            published += 1
            logger.info(
                "Outbox event published",
                extra={"event_id": str(event.id), "payment_id": str(event.aggregate_id)},
            )
    return published


async def run() -> None:
    configure_logging(settings.log_level)
    await declare_topology(settings.rabbitmq_url)
    await broker.start()
    logger.info("Outbox relay started")
    try:
        while True:
            published = await publish_batch()
            if published == 0:
                await asyncio.sleep(settings.outbox_poll_interval_seconds)
    finally:
        await broker.stop()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
