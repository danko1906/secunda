from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from tests.unit.fakes import FakeClock, FakeGateway, FakePaymentStore, FakeWebhookSender

from payment_service.application.services import ProcessPaymentService
from payment_service.domain.entities import Payment
from payment_service.domain.enums import Currency, PaymentStatus
from payment_service.domain.exceptions import PaymentProcessingBusyError


def pending_payment() -> Payment:
    return Payment(
        id=uuid4(),
        amount=Decimal("10.00"),
        currency=Currency.EUR,
        description="Test",
        metadata={},
        status=PaymentStatus.PENDING,
        idempotency_key="idem",
        request_hash="hash",
        webhook_url="https://merchant.example/hook",
        created_at=FakeClock.NOW,
    )


class BlockingGateway(FakeGateway):
    def __init__(self, result: PaymentStatus) -> None:
        super().__init__(result)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def process(self, payment: Payment) -> PaymentStatus:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return self.result


class FailsOnceWebhookSender(FakeWebhookSender):
    async def send(self, payment: Payment) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary webhook failure")
        self.payloads.append({"payment_id": str(payment.id), "status": payment.status.value})


@pytest.mark.asyncio
async def test_process_payment_persists_result_and_delivers_webhook() -> None:
    payment = pending_payment()
    store = FakePaymentStore(payment)
    gateway = FakeGateway(PaymentStatus.SUCCEEDED)
    webhook = FakeWebhookSender()
    service = ProcessPaymentService(store, gateway, webhook, FakeClock())

    result = await service.execute(payment.id)

    assert result.status is PaymentStatus.SUCCEEDED
    assert gateway.calls == 1
    assert webhook.calls == 1
    assert store.payment.webhook_delivered_at == FakeClock.NOW


@pytest.mark.asyncio
async def test_redelivery_does_not_process_or_send_again_after_delivery() -> None:
    payment = pending_payment()
    store = FakePaymentStore(payment)
    gateway = FakeGateway(PaymentStatus.FAILED)
    webhook = FakeWebhookSender()
    service = ProcessPaymentService(store, gateway, webhook, FakeClock())

    first = await service.execute(payment.id)
    second = await service.execute(payment.id)

    assert first.status is PaymentStatus.FAILED
    assert second.status is PaymentStatus.FAILED
    assert gateway.calls == 1
    assert webhook.calls == 1


@pytest.mark.asyncio
async def test_concurrent_redelivery_runs_external_side_effects_once() -> None:
    payment = pending_payment()
    store = FakePaymentStore(payment)
    gateway = BlockingGateway(PaymentStatus.SUCCEEDED)
    webhook = FakeWebhookSender()
    service = ProcessPaymentService(store, gateway, webhook, FakeClock())

    first = asyncio.create_task(service.execute(payment.id))
    await gateway.started.wait()
    second = asyncio.create_task(service.execute(payment.id))
    await asyncio.sleep(0)
    gateway.release.set()
    results = await asyncio.gather(first, second, return_exceptions=True)

    assert gateway.calls == 1
    assert webhook.calls == 1
    assert sum(isinstance(result, PaymentProcessingBusyError) for result in results) == 1


@pytest.mark.asyncio
async def test_failure_releases_claim_and_retry_skips_completed_gateway() -> None:
    payment = pending_payment()
    store = FakePaymentStore(payment)
    gateway = FakeGateway(PaymentStatus.SUCCEEDED)
    webhook = FailsOnceWebhookSender()
    service = ProcessPaymentService(store, gateway, webhook, FakeClock())

    with pytest.raises(RuntimeError, match="temporary webhook failure"):
        await service.execute(payment.id)
    result = await service.execute(payment.id)

    assert result.webhook_delivered_at == FakeClock.NOW
    assert gateway.calls == 1
    assert webhook.calls == 2
