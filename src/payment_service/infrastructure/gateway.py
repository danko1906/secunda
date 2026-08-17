import asyncio
import random

from payment_service.domain.entities import Payment
from payment_service.domain.enums import PaymentStatus


class SimulatedPaymentGateway:
    def __init__(
        self,
        min_delay_seconds: float,
        max_delay_seconds: float,
        success_rate: float,
    ) -> None:
        if min_delay_seconds > max_delay_seconds:
            raise ValueError("Minimum gateway delay cannot exceed maximum delay")
        self._min_delay = min_delay_seconds
        self._max_delay = max_delay_seconds
        self._success_rate = success_rate

    async def process(self, payment: Payment) -> PaymentStatus:
        del payment
        await asyncio.sleep(random.uniform(self._min_delay, self._max_delay))
        if random.random() < self._success_rate:
            return PaymentStatus.SUCCEEDED
        return PaymentStatus.FAILED
