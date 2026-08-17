from datetime import datetime
from uuid import UUID

import aio_pika
from aio_pika import ExchangeType
from faststream.rabbit import RabbitExchange, RabbitQueue
from pydantic import BaseModel

PAYMENTS_EXCHANGE_NAME = "payments"
PAYMENTS_QUEUE_NAME = "payments.new"
DLX_NAME = "payments.dlx"
DLQ_NAME = "payments.dlq"
DLQ_ROUTING_KEY = "payments.dead"

PAYMENTS_EXCHANGE = RabbitExchange(PAYMENTS_EXCHANGE_NAME, durable=True)
PAYMENTS_QUEUE = RabbitQueue(
    PAYMENTS_QUEUE_NAME,
    routing_key=PAYMENTS_QUEUE_NAME,
    durable=True,
    arguments={
        "x-dead-letter-exchange": DLX_NAME,
        "x-dead-letter-routing-key": DLQ_ROUTING_KEY,
    },
)


class PaymentCreatedMessage(BaseModel):
    event_id: UUID
    event_type: str
    payment_id: UUID
    occurred_at: datetime


async def declare_topology(amqp_url: str) -> None:
    connection = await aio_pika.connect_robust(amqp_url)
    try:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            PAYMENTS_EXCHANGE_NAME, ExchangeType.DIRECT, durable=True
        )
        dlx = await channel.declare_exchange(DLX_NAME, ExchangeType.DIRECT, durable=True)
        queue = await channel.declare_queue(
            PAYMENTS_QUEUE_NAME,
            durable=True,
            arguments={
                "x-dead-letter-exchange": DLX_NAME,
                "x-dead-letter-routing-key": DLQ_ROUTING_KEY,
            },
        )
        await queue.bind(exchange, routing_key=PAYMENTS_QUEUE_NAME)
        dlq = await channel.declare_queue(DLQ_NAME, durable=True)
        await dlq.bind(dlx, routing_key=DLQ_ROUTING_KEY)
    finally:
        await connection.close()
