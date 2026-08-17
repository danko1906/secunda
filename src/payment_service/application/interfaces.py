from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from payment_service.domain.entities import OutboxEvent, Payment
from payment_service.domain.enums import PaymentStatus


class Clock(Protocol):
    def now(self) -> datetime: ...


class PaymentRepository(Protocol):
    async def get(self, payment_id: UUID) -> Payment | None: ...

    async def get_by_idempotency_key(self, key: str) -> Payment | None: ...

    async def add(self, payment: Payment) -> None: ...


class OutboxRepository(Protocol):
    async def add(self, event: OutboxEvent) -> None: ...


class UnitOfWork(Protocol):
    payments: PaymentRepository
    outbox: OutboxRepository

    async def __aenter__(self) -> UnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...


class PaymentGateway(Protocol):
    async def process(self, payment: Payment) -> PaymentStatus: ...


class WebhookSender(Protocol):
    async def send(self, payment: Payment) -> None: ...


class PaymentProcessingStore(Protocol):
    async def get(self, payment_id: UUID) -> Payment: ...

    async def claim(
        self,
        payment_id: UUID,
        claim_token: UUID,
        now: datetime,
        lease_until: datetime,
    ) -> Payment | None: ...

    async def complete_if_pending(
        self,
        payment_id: UUID,
        claim_token: UUID,
        status: PaymentStatus,
        processed_at: datetime,
    ) -> Payment: ...

    async def mark_webhook_delivered(
        self,
        payment_id: UUID,
        claim_token: UUID,
        delivered_at: datetime,
    ) -> Payment: ...

    async def release_claim(self, payment_id: UUID, claim_token: UUID) -> None: ...

    async def record_failure(self, payment_id: UUID) -> int: ...
