from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PaymentCreatedMessage(BaseModel):
    event_id: UUID
    event_type: str
    payment_id: UUID
    occurred_at: datetime
