from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from payment_service.domain.enums import Currency, PaymentStatus


@dataclass(frozen=True, slots=True)
class Payment:
    id: UUID
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, Any]
    status: PaymentStatus
    idempotency_key: str
    request_hash: str
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None = None
    webhook_delivered_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    id: UUID
    aggregate_id: UUID
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
