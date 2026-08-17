import secrets
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.security import APIKeyHeader

from payment_service.config import get_settings
from payment_service.models import PaymentModel
from payment_service.schemas import PaymentAccepted, PaymentCreate, PaymentRead
from payment_service.services import (
    PaymentNotFoundError,
)
from payment_service.services import (
    create_payment as create_payment_record,
)
from payment_service.services import (
    get_payment as get_payment_record,
)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(provided: Annotated[str | None, Depends(api_key_header)]) -> None:
    expected = get_settings().api_key.get_secret_value()
    if provided is None or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def accepted(payment: PaymentModel) -> PaymentAccepted:
    return PaymentAccepted(
        payment_id=payment.id,
        status=payment.status,
        created_at=payment.created_at,
    )


def detailed(payment: PaymentModel) -> PaymentRead:
    return PaymentRead(
        payment_id=payment.id,
        amount=payment.amount,
        currency=payment.currency,
        description=payment.description,
        metadata=payment.metadata_,
        status=payment.status,
        webhook_url=payment.webhook_url,
        created_at=payment.created_at,
        processed_at=payment.processed_at,
    )


def create_app() -> FastAPI:
    app = FastAPI(title="Payment Processing Service", version="1.0.0")

    @app.post(
        "/api/v1/payments",
        response_model=PaymentAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(verify_api_key)],
    )
    async def create_payment(
        payload: PaymentCreate,
        response: Response,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=255)
        ],
    ) -> PaymentAccepted:
        payment = await create_payment_record(payload, idempotency_key)
        response.headers["Location"] = f"/api/v1/payments/{payment.id}"
        return accepted(payment)

    @app.get(
        "/api/v1/payments/{payment_id}",
        response_model=PaymentRead,
        dependencies=[Depends(verify_api_key)],
    )
    async def get_payment(payment_id: UUID) -> PaymentRead:
        try:
            payment = await get_payment_record(payment_id)
        except PaymentNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return detailed(payment)

    @app.get("/health/live", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
