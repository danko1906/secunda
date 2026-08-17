import hashlib
import json

from payment_service.application.dto import CreatePaymentCommand


def request_hash(command: CreatePaymentCommand) -> str:
    canonical_payload = {
        "amount": format(command.amount.normalize(), "f"),
        "currency": command.currency.value,
        "description": command.description,
        "metadata": command.metadata,
        "webhook_url": command.webhook_url,
    }
    encoded = json.dumps(
        canonical_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
