import logging
from typing import Any

from fastapi import FastAPI, Request, Response, status

logger = logging.getLogger(__name__)
app = FastAPI(title="Webhook Mock", docs_url=None, redoc_url=None)


@app.post("/webhook", status_code=status.HTTP_204_NO_CONTENT)
async def receive_webhook(request: Request) -> Response:
    payload: dict[str, Any] = await request.json()
    logger.info(
        "Webhook received",
        extra={
            "payment_id": payload.get("data", {}).get("payment_id"),
            "event_id": payload.get("event_id"),
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
