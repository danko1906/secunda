from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from payment_service.application.dto import CreatePaymentCommand
from payment_service.domain.entities import OutboxEvent, Payment
from payment_service.domain.enums import Currency, PaymentStatus
from payment_service.domain.exceptions import PaymentNotFoundError


class FakeClock:
    NOW = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.NOW


@dataclass
class FakeState:
    payments: dict[UUID, Payment] = field(default_factory=dict)
    outbox: dict[UUID, OutboxEvent] = field(default_factory=dict)


class FakePaymentRepository:
    def __init__(self, state: FakeState) -> None:
        self.state = state

    async def get(self, payment_id: UUID) -> Payment | None:
        return self.state.payments.get(payment_id)

    async def get_by_idempotency_key(self, key: str) -> Payment | None:
        return next((p for p in self.state.payments.values() if p.idempotency_key == key), None)

    async def add(self, payment: Payment) -> None:
        self.state.payments[payment.id] = payment


class FakeOutboxRepository:
    def __init__(self, state: FakeState, *, fail_on_add: bool = False) -> None:
        self.state = state
        self.fail_on_add = fail_on_add

    async def add(self, event: OutboxEvent) -> None:
        if self.fail_on_add:
            raise RuntimeError("outbox insert failed")
        self.state.outbox[event.id] = event


class FakeUnitOfWork:
    def __init__(self, state: FakeState, *, fail_outbox: bool = False) -> None:
        self._target = state
        self._working = FakeState(dict(state.payments), dict(state.outbox))
        self.payments = FakePaymentRepository(self._working)
        self.outbox = FakeOutboxRepository(self._working, fail_on_add=fail_outbox)

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def commit(self) -> None:
        self._target.payments = dict(self._working.payments)
        self._target.outbox = dict(self._working.outbox)

    async def rollback(self) -> None:
        return None


class FakeUnitOfWorkFactory:
    def __init__(self, *, fail_outbox: bool = False) -> None:
        self.state = FakeState()
        self.fail_outbox = fail_outbox

    def __call__(self) -> FakeUnitOfWork:
        return FakeUnitOfWork(self.state, fail_outbox=self.fail_outbox)


class FakeGateway:
    def __init__(self, result: PaymentStatus) -> None:
        self.result = result
        self.calls = 0

    async def process(self, payment: Payment) -> PaymentStatus:
        self.calls += 1
        return self.result


class FakeWebhookSender:
    def __init__(self) -> None:
        self.calls = 0
        self.payloads: list[dict[str, Any]] = []

    async def send(self, payment: Payment) -> None:
        self.calls += 1
        self.payloads.append({"payment_id": str(payment.id), "status": payment.status.value})


class FakePaymentStore:
    def __init__(self, payment: Payment) -> None:
        self.payment = payment
        self.claim_token: UUID | None = None
        self.processing_failures = 0

    async def get(self, payment_id: UUID) -> Payment:
        if payment_id != self.payment.id:
            raise PaymentNotFoundError(payment_id)
        return self.payment

    async def claim(
        self,
        payment_id: UUID,
        claim_token: UUID,
        now: datetime,
        lease_until: datetime,
    ) -> Payment | None:
        del now, lease_until
        if payment_id != self.payment.id:
            raise PaymentNotFoundError(payment_id)
        if self.payment.webhook_delivered_at is not None or self.claim_token is not None:
            return None
        self.claim_token = claim_token
        return self.payment

    async def complete_if_pending(
        self,
        payment_id: UUID,
        claim_token: UUID,
        status: PaymentStatus,
        processed_at: datetime,
    ) -> Payment:
        assert claim_token == self.claim_token
        if self.payment.status is PaymentStatus.PENDING:
            self.payment = replace(
                self.payment,
                status=status,
                processed_at=processed_at,
            )
        return self.payment

    async def mark_webhook_delivered(
        self,
        payment_id: UUID,
        claim_token: UUID,
        delivered_at: datetime,
    ) -> Payment:
        assert claim_token == self.claim_token
        self.payment = replace(self.payment, webhook_delivered_at=delivered_at)
        self.claim_token = None
        return self.payment

    async def release_claim(self, payment_id: UUID, claim_token: UUID) -> None:
        if payment_id == self.payment.id and claim_token == self.claim_token:
            self.claim_token = None

    async def record_failure(self, payment_id: UUID) -> int:
        if payment_id != self.payment.id:
            raise PaymentNotFoundError(payment_id)
        self.processing_failures += 1
        return self.processing_failures


class FakeApiCreateService:
    def __init__(self, payment: Payment) -> None:
        self.payment = payment

    async def execute(self, command: CreatePaymentCommand) -> Payment:
        return replace(
            self.payment,
            amount=command.amount,
            currency=command.currency,
            description=command.description,
            metadata=command.metadata,
            webhook_url=command.webhook_url,
            idempotency_key=command.idempotency_key,
        )


class FakeApiGetService:
    def __init__(self, payment: Payment) -> None:
        self.payment = payment

    async def execute(self, payment_id: UUID) -> Payment:
        return replace(self.payment, id=payment_id)


def make_payment() -> Payment:
    return Payment(
        id=uuid4(),
        amount=Decimal("42.10"),
        currency=Currency.USD,
        description="Order",
        metadata={},
        status=PaymentStatus.PENDING,
        idempotency_key="idem-1",
        request_hash="hash",
        webhook_url="https://merchant.example/hook",
        created_at=FakeClock.NOW,
    )
