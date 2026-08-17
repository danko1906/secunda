from datetime import datetime
from typing import Never
from uuid import UUID

from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payment_service.domain.entities import Payment
from payment_service.domain.enums import PaymentStatus
from payment_service.domain.exceptions import (
    PaymentNotFoundError,
    PaymentProcessingClaimLostError,
)
from payment_service.infrastructure.db.mappers import payment_to_domain
from payment_service.infrastructure.db.models import PaymentModel


class SqlAlchemyPaymentProcessingStore:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def get(self, payment_id: UUID) -> Payment:
        async with self._factory() as session:
            model = await session.get(PaymentModel, payment_id)
        if model is None:
            raise PaymentNotFoundError(payment_id)
        return payment_to_domain(model)

    async def claim(
        self,
        payment_id: UUID,
        claim_token: UUID,
        now: datetime,
        lease_until: datetime,
    ) -> Payment | None:
        statement = (
            update(PaymentModel)
            .where(
                PaymentModel.id == payment_id,
                PaymentModel.webhook_delivered_at.is_(None),
                or_(
                    PaymentModel.processing_token.is_(None),
                    PaymentModel.processing_lease_until <= now,
                ),
            )
            .values(
                processing_token=claim_token,
                processing_lease_until=lease_until,
            )
            .returning(PaymentModel)
        )
        async with self._factory() as session, session.begin():
            model = await session.scalar(statement)
        return payment_to_domain(model) if model is not None else None

    async def complete_if_pending(
        self,
        payment_id: UUID,
        claim_token: UUID,
        status: PaymentStatus,
        processed_at: datetime,
    ) -> Payment:
        statement = (
            update(PaymentModel)
            .where(
                PaymentModel.id == payment_id,
                PaymentModel.status == PaymentStatus.PENDING.value,
                PaymentModel.processing_token == claim_token,
            )
            .values(status=status.value, processed_at=processed_at)
            .returning(PaymentModel)
        )
        async with self._factory() as session, session.begin():
            model = await session.scalar(statement)
        if model is None:
            await self._raise_missing_or_lost_claim(payment_id, claim_token)
        return payment_to_domain(model)

    async def mark_webhook_delivered(
        self,
        payment_id: UUID,
        claim_token: UUID,
        delivered_at: datetime,
    ) -> Payment:
        statement = (
            update(PaymentModel)
            .where(
                PaymentModel.id == payment_id,
                PaymentModel.processing_token == claim_token,
            )
            .values(
                webhook_delivered_at=delivered_at,
                processing_token=None,
                processing_lease_until=None,
            )
            .returning(PaymentModel)
        )
        async with self._factory() as session, session.begin():
            model = await session.scalar(statement)
        if model is None:
            await self._raise_missing_or_lost_claim(payment_id, claim_token)
        return payment_to_domain(model)

    async def release_claim(self, payment_id: UUID, claim_token: UUID) -> None:
        statement = (
            update(PaymentModel)
            .where(
                PaymentModel.id == payment_id,
                PaymentModel.processing_token == claim_token,
            )
            .values(processing_token=None, processing_lease_until=None)
        )
        async with self._factory() as session, session.begin():
            await session.execute(statement)

    async def record_failure(self, payment_id: UUID) -> int:
        statement = (
            update(PaymentModel)
            .where(PaymentModel.id == payment_id)
            .values(processing_failures=PaymentModel.processing_failures + 1)
            .returning(PaymentModel.processing_failures)
        )
        async with self._factory() as session, session.begin():
            failures = await session.scalar(statement)
        if failures is None:
            raise PaymentNotFoundError(payment_id)
        return failures

    async def _raise_missing_or_lost_claim(
        self,
        payment_id: UUID,
        claim_token: UUID,
    ) -> Never:
        async with self._factory() as session:
            model = await session.get(PaymentModel, payment_id)
        if model is None:
            raise PaymentNotFoundError(payment_id)
        if model.processing_token != claim_token:
            raise PaymentProcessingClaimLostError(payment_id)
        raise RuntimeError(f"Payment {payment_id} could not be updated in its current state")
