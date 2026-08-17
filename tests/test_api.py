from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from payment_service import main
from payment_service.models import PaymentModel


def payment() -> PaymentModel:
    return PaymentModel(
        id=uuid4(),
        amount=Decimal("42.10"),
        currency="USD",
        description="Order",
        metadata_={"order_id": 1},
        status="pending",
        idempotency_key="idem-1",
        webhook_url="https://merchant.example/hook",
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_create_payment_returns_202(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = payment()

    async def fake_create(*args: object) -> PaymentModel:
        del args
        return stored

    monkeypatch.setattr(main, "create_payment_record", fake_create)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.create_app()), base_url="http://test"
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
    assert response.json()["payment_id"] == str(stored.id)
    assert response.headers["location"].endswith(str(stored.id))


@pytest.mark.asyncio
async def test_business_endpoint_requires_api_key() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.create_app()), base_url="http://test"
    ) as client:
        response = await client.get(f"/api/v1/payments/{uuid4()}")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_payment_returns_details(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = payment()

    async def fake_get(*args: object) -> PaymentModel:
        del args
        return stored

    monkeypatch.setattr(main, "get_payment_record", fake_get)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.create_app()), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/v1/payments/{stored.id}", headers={"X-API-Key": "change-me"}
        )

    assert response.status_code == 200
    assert response.json()["metadata"] == {"order_id": 1}
    assert response.json()["status"] == "pending"
