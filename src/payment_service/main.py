from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from payment_service.api.routes import router
from payment_service.core.config import get_settings
from payment_service.core.logging import configure_logging
from payment_service.domain.exceptions import IdempotencyConflictError, PaymentNotFoundError


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    application = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="Asynchronous payments with transactional outbox and RabbitMQ",
    )
    application.include_router(router)

    @application.get("/health/live", include_in_schema=False)
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @application.exception_handler(PaymentNotFoundError)
    async def payment_not_found(
        request: Request,
        exc: PaymentNotFoundError,
    ) -> JSONResponse:
        del request
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})

    @application.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict(
        request: Request,
        exc: IdempotencyConflictError,
    ) -> JSONResponse:
        del request
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})

    return application


app = create_app()
