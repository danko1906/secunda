import pytest
from pydantic import ValidationError

from payment_service.schemas import PaymentCreate


def test_payment_schema_accepts_supported_currency() -> None:
    payload = PaymentCreate(
        amount="10.50",
        currency="RUB",
        description="Order",
        metadata={},
        webhook_url="https://merchant.example/webhook",
    )

    assert str(payload.amount) == "10.50"


@pytest.mark.parametrize("amount", ["0", "-1", "1.001"])
def test_payment_schema_rejects_invalid_amount(amount: str) -> None:
    with pytest.raises(ValidationError):
        PaymentCreate(
            amount=amount,
            currency="EUR",
            description="Order",
            metadata={},
            webhook_url="https://merchant.example/webhook",
        )
