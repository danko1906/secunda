from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payment_service.application.interfaces import OutboxRepository, PaymentRepository
from payment_service.domain.exceptions import DuplicateIdempotencyKeyError
from payment_service.infrastructure.db.repositories import (
    SqlAlchemyOutboxRepository,
    SqlAlchemyPaymentRepository,
)


class SqlAlchemyUnitOfWork:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory
        self._session: AsyncSession | None = None
        self.payments: PaymentRepository
        self.outbox: OutboxRepository

    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        self._session = self._factory()
        self.payments = SqlAlchemyPaymentRepository(self._session)
        self.outbox = SqlAlchemyOutboxRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        if self._session is None:
            return
        if exc_type is not None:
            await self._session.rollback()
        await self._session.close()

    async def commit(self) -> None:
        session = self._require_session()
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            if "uq_payments_idempotency_key" in str(exc):
                raise DuplicateIdempotencyKeyError from exc
            raise

    async def rollback(self) -> None:
        await self._require_session().rollback()

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("Unit of work must be entered before use")
        return self._session
