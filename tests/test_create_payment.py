from __future__ import annotations

from decimal import Decimal

import pytest
from tests.unit.fakes import FakeClock, FakeUnitOfWorkFactory

from payment_service.application.dto import CreatePaymentCommand
from payment_service.application.services import CreatePaymentService
from payment_service.domain.enums import Currency
from payment_service.domain.exceptions import IdempotencyConflictError


def command(*, description: str = "Order #42") -> CreatePaymentCommand:
    return CreatePaymentCommand(
        amount=Decimal("1250.50"),
        currency=Currency.RUB,
        description=description,
        metadata={"order_id": "42"},
        webhook_url="https://merchant.example/webhooks/payments",
        idempotency_key="idem-42",
    )


@pytest.mark.asyncio
async def test_create_payment_stores_payment_and_outbox_in_one_unit_of_work() -> None:
    factory = FakeUnitOfWorkFactory()
    service = CreatePaymentService(factory, clock=FakeClock())

    payment = await service.execute(command())

    assert payment.status.value == "pending"
    assert factory.state.payments[payment.id] == payment
    events = list(factory.state.outbox.values())
    assert len(events) == 1
    assert events[0].aggregate_id == payment.id
    assert events[0].payload["payment_id"] == str(payment.id)


@pytest.mark.asyncio
async def test_create_payment_rolls_back_when_outbox_insert_fails() -> None:
    factory = FakeUnitOfWorkFactory(fail_outbox=True)
    service = CreatePaymentService(factory, clock=FakeClock())

    with pytest.raises(RuntimeError, match="outbox insert failed"):
        await service.execute(command())

    assert factory.state.payments == {}
    assert factory.state.outbox == {}


@pytest.mark.asyncio
async def test_same_idempotency_key_and_payload_returns_original_payment() -> None:
    factory = FakeUnitOfWorkFactory()
    service = CreatePaymentService(factory, clock=FakeClock())

    first = await service.execute(command())
    second = await service.execute(command())

    assert second == first
    assert len(factory.state.payments) == 1
    assert len(factory.state.outbox) == 1


@pytest.mark.asyncio
async def test_same_idempotency_key_with_different_payload_returns_conflict() -> None:
    factory = FakeUnitOfWorkFactory()
    service = CreatePaymentService(factory, clock=FakeClock())
    await service.execute(command())

    with pytest.raises(IdempotencyConflictError):
        await service.execute(command(description="A different order"))
