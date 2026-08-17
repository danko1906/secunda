import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from payment_service.application.clock import UtcClock
from payment_service.application.interfaces import UnitOfWork
from payment_service.application.services import CreatePaymentService, GetPaymentService
from payment_service.core.config import Settings, get_settings
from payment_service.infrastructure.db.session import session_factory
from payment_service.infrastructure.db.uow import SqlAlchemyUnitOfWork

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def create_unit_of_work() -> UnitOfWork:
    return SqlAlchemyUnitOfWork(session_factory)


async def verify_api_key(
    provided: Annotated[str | None, Depends(api_key_header)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    expected = settings.api_key.get_secret_value()
    if provided is None or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )


def get_create_payment_service() -> CreatePaymentService:
    return CreatePaymentService(
        create_unit_of_work,
        clock=UtcClock(),
    )


def get_payment_service() -> GetPaymentService:
    return GetPaymentService(create_unit_of_work)
