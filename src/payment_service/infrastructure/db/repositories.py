from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.domain.entities import OutboxEvent, Payment
from payment_service.infrastructure.db.mappers import payment_to_domain, payment_to_model
from payment_service.infrastructure.db.models import OutboxModel, PaymentModel


class SqlAlchemyPaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, payment_id: UUID) -> Payment | None:
        model = await self._session.get(PaymentModel, payment_id)
        return payment_to_domain(model) if model is not None else None

    async def get_by_idempotency_key(self, key: str) -> Payment | None:
        statement = select(PaymentModel).where(PaymentModel.idempotency_key == key)
        model = await self._session.scalar(statement)
        return payment_to_domain(model) if model is not None else None

    async def add(self, payment: Payment) -> None:
        self._session.add(payment_to_model(payment))


class SqlAlchemyOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: OutboxEvent) -> None:
        self._session.add(
            OutboxModel(
                id=event.id,
                aggregate_id=event.aggregate_id,
                event_type=event.event_type,
                payload=event.payload,
                created_at=event.created_at,
            )
        )
