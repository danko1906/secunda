from __future__ import annotations

import aio_pika
from aio_pika import ExchangeType
from faststream.rabbit import RabbitExchange, RabbitQueue
from faststream.rabbit.schemas import Channel

from payment_service.core.config import get_settings

PAYMENTS_EXCHANGE_NAME = "payments"
RETRY_EXCHANGE_NAME = "payments.retry"
DEAD_LETTER_EXCHANGE_NAME = "payments.dlx"
PAYMENTS_QUEUE_NAME = "payments.new"
DEAD_LETTER_QUEUE_NAME = "payments.dlq"
DEAD_LETTER_ROUTING_KEY = "payments.dead"
ATTEMPT_HEADER = "x-attempt"

settings = get_settings()
OUTBOX_CHANNEL = Channel(publisher_confirms=True, on_return_raises=True)
CONSUMER_CHANNEL = Channel(
    prefetch_count=settings.consumer_prefetch_count,
    publisher_confirms=True,
    on_return_raises=True,
)
RETRY_QUEUES = {
    settings.retry_delay_1_seconds: f"payments.retry.{settings.retry_delay_1_seconds}s",
    settings.retry_delay_2_seconds: f"payments.retry.{settings.retry_delay_2_seconds}s",
}

PAYMENTS_EXCHANGE = RabbitExchange(PAYMENTS_EXCHANGE_NAME, durable=True)
RETRY_EXCHANGE = RabbitExchange(RETRY_EXCHANGE_NAME, durable=True)
PAYMENTS_QUEUE = RabbitQueue(
    PAYMENTS_QUEUE_NAME,
    routing_key=PAYMENTS_QUEUE_NAME,
    durable=True,
    arguments={
        "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE_NAME,
        "x-dead-letter-routing-key": DEAD_LETTER_ROUTING_KEY,
    },
)


async def declare_topology(amqp_url: str) -> None:
    connection = await aio_pika.connect_robust(amqp_url)
    try:
        channel = await connection.channel(publisher_confirms=True)
        payments_exchange = await channel.declare_exchange(
            PAYMENTS_EXCHANGE_NAME,
            ExchangeType.DIRECT,
            durable=True,
        )
        retry_exchange = await channel.declare_exchange(
            RETRY_EXCHANGE_NAME,
            ExchangeType.DIRECT,
            durable=True,
        )
        dead_letter_exchange = await channel.declare_exchange(
            DEAD_LETTER_EXCHANGE_NAME,
            ExchangeType.DIRECT,
            durable=True,
        )

        payments_queue = await channel.declare_queue(
            PAYMENTS_QUEUE_NAME,
            durable=True,
            arguments={
                "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE_NAME,
                "x-dead-letter-routing-key": DEAD_LETTER_ROUTING_KEY,
            },
        )
        await payments_queue.bind(payments_exchange, routing_key=PAYMENTS_QUEUE_NAME)

        for delay_seconds, queue_name in RETRY_QUEUES.items():
            retry_queue = await channel.declare_queue(
                queue_name,
                durable=True,
                arguments={
                    "x-message-ttl": delay_seconds * 1000,
                    "x-dead-letter-exchange": PAYMENTS_EXCHANGE_NAME,
                    "x-dead-letter-routing-key": PAYMENTS_QUEUE_NAME,
                },
            )
            await retry_queue.bind(retry_exchange, routing_key=queue_name)

        dead_letter_queue = await channel.declare_queue(DEAD_LETTER_QUEUE_NAME, durable=True)
        await dead_letter_queue.bind(
            dead_letter_exchange,
            routing_key=DEAD_LETTER_ROUTING_KEY,
        )
    finally:
        await connection.close()
