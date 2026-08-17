from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.models import OutboxModel, PaymentModel


class PaymentRepository:
    """The explicit database access layer for payments."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, payment_id: UUID) -> PaymentModel | None:
        return await self.session.get(PaymentModel, payment_id)

    async def get_by_idempotency_key(self, key: str) -> PaymentModel | None:
        statement = select(PaymentModel).where(PaymentModel.idempotency_key == key)
        payment: PaymentModel | None = await self.session.scalar(statement)
        return payment

    def add(self, payment: PaymentModel) -> None:
        self.session.add(payment)

    async def set_status(
        self, payment_id: UUID, status: str, processed_at: datetime
    ) -> PaymentModel:
        statement = (
            update(PaymentModel)
            .where(PaymentModel.id == payment_id)
            .values(status=status, processed_at=processed_at)
            .returning(PaymentModel)
        )
        payment = await self.session.scalar(statement)
        if payment is None:
            raise LookupError(f"Payment {payment_id} not found")
        return payment

    async def mark_webhook_delivered(self, payment_id: UUID, delivered_at: datetime) -> None:
        statement = (
            update(PaymentModel)
            .where(PaymentModel.id == payment_id)
            .values(webhook_delivered_at=delivered_at)
        )
        await self.session.execute(statement)


class OutboxRepository:
    """The explicit database access layer for transactional events."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, event: OutboxModel) -> None:
        self.session.add(event)

    async def lock_unpublished(self, limit: int) -> list[OutboxModel]:
        statement = (
            select(OutboxModel)
            .where(OutboxModel.published_at.is_(None))
            .order_by(OutboxModel.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await self.session.scalars(statement)).all())

    @staticmethod
    def mark_published(event: OutboxModel, published_at: datetime) -> None:
        event.published_at = published_at
