from payment_service.domain.entities import Payment
from payment_service.domain.enums import Currency, PaymentStatus
from payment_service.infrastructure.db.models import PaymentModel


def payment_to_domain(model: PaymentModel) -> Payment:
    return Payment(
        id=model.id,
        amount=model.amount,
        currency=Currency(model.currency),
        description=model.description,
        metadata=dict(model.metadata_),
        status=PaymentStatus(model.status),
        idempotency_key=model.idempotency_key,
        request_hash=model.request_hash,
        webhook_url=model.webhook_url,
        created_at=model.created_at,
        processed_at=model.processed_at,
        webhook_delivered_at=model.webhook_delivered_at,
    )


def payment_to_model(payment: Payment) -> PaymentModel:
    return PaymentModel(
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
        processed_at=payment.processed_at,
        webhook_delivered_at=payment.webhook_delivered_at,
    )
