from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

from payment_service.application.dto import CreatePaymentCommand
from payment_service.application.hashing import request_hash
from payment_service.application.interfaces import (
    Clock,
    PaymentGateway,
    PaymentProcessingStore,
    UnitOfWorkFactory,
    WebhookSender,
)
from payment_service.domain.entities import OutboxEvent, Payment
from payment_service.domain.enums import PaymentStatus
from payment_service.domain.exceptions import (
    DuplicateIdempotencyKeyError,
    IdempotencyConflictError,
    PaymentNotFoundError,
    PaymentProcessingBusyError,
)


class CreatePaymentService:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: CreatePaymentCommand) -> Payment:
        fingerprint = request_hash(command)
        existing = await self._get_by_idempotency_key(command.idempotency_key)
        if existing is not None:
            return self._resolve_existing(existing, fingerprint)

        payment = self._new_payment(command, fingerprint)
        event_id = uuid4()
        event = OutboxEvent(
            id=event_id,
            aggregate_id=payment.id,
            event_type="payment.created",
            payload={
                "event_id": str(event_id),
                "event_type": "payment.created",
                "payment_id": str(payment.id),
                "occurred_at": payment.created_at.isoformat(),
            },
            created_at=payment.created_at,
        )

        try:
            async with self._uow_factory() as uow:
                await uow.payments.add(payment)
                await uow.outbox.add(event)
                await uow.commit()
        except DuplicateIdempotencyKeyError:
            concurrent = await self._get_by_idempotency_key(command.idempotency_key)
            if concurrent is None:
                raise
            return self._resolve_existing(concurrent, fingerprint)
        return payment

    async def _get_by_idempotency_key(self, key: str) -> Payment | None:
        async with self._uow_factory() as uow:
            return await uow.payments.get_by_idempotency_key(key)

    @staticmethod
    def _resolve_existing(existing: Payment, fingerprint: str) -> Payment:
        if existing.request_hash != fingerprint:
            raise IdempotencyConflictError
        return existing

    def _new_payment(self, command: CreatePaymentCommand, fingerprint: str) -> Payment:
        return Payment(
            id=uuid4(),
            amount=command.amount,
            currency=command.currency,
            description=command.description,
            metadata=command.metadata,
            status=PaymentStatus.PENDING,
            idempotency_key=command.idempotency_key,
            request_hash=fingerprint,
            webhook_url=command.webhook_url,
            created_at=self._clock.now(),
        )


class GetPaymentService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, payment_id: UUID) -> Payment:
        async with self._uow_factory() as uow:
            payment = await uow.payments.get(payment_id)
        if payment is None:
            raise PaymentNotFoundError(payment_id)
        return payment


class ProcessPaymentService:
    def __init__(
        self,
        store: PaymentProcessingStore,
        gateway: PaymentGateway,
        webhook_sender: WebhookSender,
        clock: Clock,
        processing_lease_seconds: int = 30,
    ) -> None:
        self._store = store
        self._gateway = gateway
        self._webhook_sender = webhook_sender
        self._clock = clock
        self._processing_lease = timedelta(seconds=processing_lease_seconds)

    async def execute(self, payment_id: UUID) -> Payment:
        claim_token = uuid4()
        claimed_at = self._clock.now()
        payment = await self._store.claim(
            payment_id,
            claim_token,
            claimed_at,
            claimed_at + self._processing_lease,
        )
        if payment is None:
            current = await self._store.get(payment_id)
            if current.webhook_delivered_at is not None:
                return current
            raise PaymentProcessingBusyError(payment_id)

        try:
            if payment.status is PaymentStatus.PENDING:
                outcome = await self._gateway.process(payment)
                if outcome is PaymentStatus.PENDING:
                    raise ValueError("Payment gateway must return a terminal status")
                payment = await self._store.complete_if_pending(
                    payment.id,
                    claim_token,
                    outcome,
                    self._clock.now(),
                )

            await self._webhook_sender.send(payment)
            return await self._store.mark_webhook_delivered(
                payment.id,
                claim_token,
                self._clock.now(),
            )
        except BaseException:
            await self._store.release_claim(payment_id, claim_token)
            raise
