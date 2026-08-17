# Payment processing service

Тестовый сервис для асинхронной обработки платежей. API создает платеж со
статусом `pending`, после чего consumer эмулирует обработку и отправляет результат
на `webhook_url`.

Внутри: FastAPI, PostgreSQL, SQLAlchemy, RabbitMQ/FastStream, Alembic и Docker
Compose. Событие для RabbitMQ сначала сохраняется в таблицу `outbox` в одной
транзакции с платежом. `Idempotency-Key` защищает API от дублей. Для webhook есть
три попытки с увеличением задержки, после чего сообщение попадает в DLQ.

## Запуск

Нужен Docker с Compose v2:

```bash
docker compose up --build
```

- Swagger: <http://localhost:8000/docs>
- RabbitMQ Management: <http://localhost:15672> (`payments` / `payments`)
- API key по умолчанию: `local-secret-key`

## Примеры

Создать платеж:

```bash
curl -X POST http://localhost:8000/api/v1/payments \
  -H "X-API-Key: local-secret-key" \
  -H "Idempotency-Key: order-42" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "1250.50",
    "currency": "RUB",
    "description": "Order #42",
    "metadata": {"order_id": 42},
    "webhook_url": "https://webhook.site/your-id"
  }'
```

Получить текущее состояние:

```bash
curl http://localhost:8000/api/v1/payments/<payment_id> \
  -H "X-API-Key: local-secret-key"
```

## Проверка

```bash
python -m pip install -e ".[dev]"
pytest
ruff check .
mypy src
```

Это не production-реализация. В частности, сбой между успешной отправкой webhook и
записью результата в БД может привести к повторному уведомлению.
