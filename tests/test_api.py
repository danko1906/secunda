from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from tests.unit.fakes import FakeApiCreateService, FakeApiGetService, make_payment

from payment_service.api.dependencies import get_create_payment_service, get_payment_service
from payment_service.main import create_app


def app_with_fakes():
    app = create_app()
    payment = make_payment()
    app.dependency_overrides[get_create_payment_service] = lambda: FakeApiCreateService(payment)
    app.dependency_overrides[get_payment_service] = lambda: FakeApiGetService(payment)
    return app


@pytest.mark.asyncio
async def test_create_payment_returns_202() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_with_fakes()),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/payments",
            headers={"X-API-Key": "change-me", "Idempotency-Key": "idem-1"},
            json={
                "amount": "42.10",
                "currency": "USD",
                "description": "Order",
                "metadata": {"order_id": 1},
                "webhook_url": "https://merchant.example/hook",
            },
        )

    assert response.status_code == 202
    assert Decimal(response.json()["amount"]) == Decimal("42.10")
    assert response.headers["location"].startswith("/api/v1/payments/")


@pytest.mark.asyncio
async def test_missing_api_key_returns_401() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_with_fakes()),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/payments/00000000-0000-0000-0000-000000000001")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_missing_idempotency_key_returns_422() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_with_fakes()),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/payments",
            headers={"X-API-Key": "change-me"},
            json={
                "amount": "1.00",
                "currency": "RUB",
                "description": "Order",
                "metadata": {},
                "webhook_url": "https://merchant.example/hook",
            },
        )

    assert response.status_code == 422
