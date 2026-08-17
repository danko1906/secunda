from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from payment_service.db import session_factory
from payment_service.models import OutboxModel, PaymentModel
from payment_service.repositories import OutboxRepository, PaymentRepository
from payment_service.schemas import PaymentCreate


class PaymentNotFoundError(Exception):
    pass


async def create_payment(payload: PaymentCreate, idempotency_key: str) -> PaymentModel:
    """Create Payment and Outbox rows atomically, or return the idempotent result."""
    now = datetime.now(UTC)
    payment_id = uuid4()
    payment = PaymentModel(
        id=payment_id,
        amount=payload.amount,
        currency=payload.currency,
        description=payload.description,
        metadata_=dict(payload.metadata),
        status="pending",
        idempotency_key=idempotency_key,
        webhook_url=str(payload.webhook_url),
        created_at=now,
    )
    event_id = uuid4()
    event = OutboxModel(
        id=event_id,
        payment_id=payment_id,
        event_type="payment.created",
        payload={
            "event_id": str(event_id),
            "event_type": "payment.created",
            "payment_id": str(payment_id),
            "occurred_at": now.isoformat(),
        },
        created_at=now,
    )

    try:
        async with session_factory() as session, session.begin():
            payments = PaymentRepository(session)
            existing = await payments.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing
            payments.add(payment)
            OutboxRepository(session).add(event)
        return payment
    except IntegrityError:
        # A concurrent request may win the unique-key race.
        async with session_factory() as session:
            existing = await PaymentRepository(session).get_by_idempotency_key(idempotency_key)
        if existing is None:
            raise
        return existing


async def get_payment(payment_id: UUID) -> PaymentModel:
    async with session_factory() as session:
        payment = await PaymentRepository(session).get(payment_id)
    if payment is None:
        raise PaymentNotFoundError(f"Payment {payment_id} not found")
    return payment
