from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status

from payment_service.api.dependencies import (
    get_create_payment_service,
    get_payment_service,
    verify_api_key,
)
from payment_service.api.schemas import PaymentAccepted, PaymentCreate, PaymentRead
from payment_service.application.dto import CreatePaymentCommand
from payment_service.application.services import CreatePaymentService, GetPaymentService

router = APIRouter(
    prefix="/api/v1/payments",
    tags=["payments"],
    dependencies=[Depends(verify_api_key)],
)


@router.post("", response_model=PaymentAccepted, status_code=status.HTTP_202_ACCEPTED)
async def create_payment(
    payload: PaymentCreate,
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    service: Annotated[CreatePaymentService, Depends(get_create_payment_service)],
) -> PaymentAccepted:
    command = CreatePaymentCommand(
        amount=payload.amount,
        currency=payload.currency,
        description=payload.description,
        metadata=dict(payload.metadata),
        webhook_url=str(payload.webhook_url),
        idempotency_key=idempotency_key,
    )
    payment = await service.execute(command)
    response.headers["Location"] = f"/api/v1/payments/{payment.id}"
    return PaymentAccepted.from_domain(payment)


@router.get("/{payment_id}", response_model=PaymentRead)
async def get_payment(
    payment_id: UUID,
    service: Annotated[GetPaymentService, Depends(get_payment_service)],
) -> PaymentRead:
    payment = await service.execute(payment_id)
    return PaymentRead.from_domain(payment)
