from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from payment_service.application.dto import CreatePaymentCommand
from payment_service.application.hashing import request_hash
from payment_service.domain.entities import OutboxEvent, Payment
from payment_service.domain.enums import Currency, PaymentStatus
from payment_service.infrastructure.db.models import PaymentModel
from payment_service.infrastructure.db.payment_store import SqlAlchemyPaymentProcessingStore
from payment_service.infrastructure.db.uow import SqlAlchemyUnitOfWork

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        TEST_DATABASE_URL is None,
        reason="TEST_DATABASE_URL is required for PostgreSQL integration tests",
    ),
]


def make_payment() -> Payment:
    command = CreatePaymentCommand(
        amount=Decimal("10.00"),
        currency=Currency.RUB,
        description="integration-test",
        metadata={},
        webhook_url="https://merchant.example/hook",
        idempotency_key=f"integration-{uuid4()}",
    )
    return Payment(
        id=uuid4(),
        amount=command.amount,
        currency=command.currency,
        description=command.description,
        metadata=command.metadata,
        status=PaymentStatus.PENDING,
        idempotency_key=command.idempotency_key,
        request_hash=request_hash(command),
        webhook_url=command.webhook_url,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
async def postgres_factory():
    assert TEST_DATABASE_URL is not None
    engine = create_async_engine(TEST_DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_payment_and_outbox_roll_back_together_on_outbox_failure(
    postgres_factory: async_sessionmaker[AsyncSession],
) -> None:
    payment = make_payment()
    event_id = uuid4()
    event = OutboxEvent(
        id=event_id,
        aggregate_id=payment.id,
        event_type="payment.created",
        payload={"event_id": str(event_id), "payment_id": str(payment.id)},
        created_at=payment.created_at,
    )

    with pytest.raises(IntegrityError):
        async with SqlAlchemyUnitOfWork(postgres_factory) as uow:
            await uow.payments.add(payment)
            await uow.outbox.add(event)
            await uow.outbox.add(event)
            await uow.commit()

    async with postgres_factory() as session:
        assert await session.get(PaymentModel, payment.id) is None


@pytest.mark.asyncio
async def test_only_one_concurrent_consumer_can_claim_payment(
    postgres_factory: async_sessionmaker[AsyncSession],
) -> None:
    payment = make_payment()
    async with postgres_factory() as session, session.begin():
        session.add(
            PaymentModel(
                id=payment.id,
                amount=payment.amount,
                currency=payment.currency.value,
                description=payment.description,
                metadata_=payment.metadata,
                status=payment.status.value,
                idempotency_key=payment.idempotency_key,
                request_hash=payment.request_hash,
                webhook_url=payment.webhook_url,
                created_at=payment.created_at,
            )
        )

    store = SqlAlchemyPaymentProcessingStore(postgres_factory)
    now = datetime.now(UTC)
    claims = await asyncio.gather(
        store.claim(payment.id, uuid4(), now, now + timedelta(seconds=30)),
        store.claim(payment.id, uuid4(), now, now + timedelta(seconds=30)),
    )

    assert sum(claim is not None for claim in claims) == 1
    async with postgres_factory() as session, session.begin():
        await session.execute(delete(PaymentModel).where(PaymentModel.id == payment.id))
