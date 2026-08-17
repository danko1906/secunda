from uuid import UUID


class DomainError(Exception):
    """Base exception intentionally safe to expose at the API boundary."""


class PaymentNotFoundError(DomainError):
    def __init__(self, payment_id: UUID) -> None:
        super().__init__(f"Payment {payment_id} was not found")


class IdempotencyConflictError(DomainError):
    def __init__(self) -> None:
        super().__init__("Idempotency-Key was already used with a different request")


class DuplicateIdempotencyKeyError(Exception):
    """Persistence race detected while inserting a unique idempotency key."""


class WebhookDeliveryError(Exception):
    """A webhook could not be delivered and can be retried."""


class PaymentProcessingBusyError(Exception):
    """Another consumer owns the payment processing lease."""

    def __init__(self, payment_id: UUID) -> None:
        super().__init__(f"Payment {payment_id} is already being processed")


class PaymentProcessingClaimLostError(Exception):
    """A consumer no longer owns the payment processing lease."""

    def __init__(self, payment_id: UUID) -> None:
        super().__init__(f"Processing lease for payment {payment_id} was lost")
