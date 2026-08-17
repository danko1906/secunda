# Асинхронный сервис процессинга платежей

Компактная версия тестового задания, рассчитанная на реализацию за 2-3 часа. Она
показывает все обязательные механизмы без production-абстракций: FastAPI,
асинхронный SQLAlchemy, PostgreSQL, RabbitMQ/FastStream, transactional Outbox,
идемпотентность, retry, DLQ, Alembic и Docker Compose.

## Запуск

Требуется Docker с Compose v2:

```bash
docker compose up --build
```

После запуска:

- API и Swagger: <http://localhost:8000/docs>
- RabbitMQ Management: <http://localhost:15672> (`payments` / `payments`)

Создание платежа:

```bash
curl -i -X POST http://localhost:8000/api/v1/payments \
  -H "X-API-Key: local-secret-key" \
  -H "Idempotency-Key: order-42-payment" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "1250.50",
    "currency": "RUB",
    "description": "Order #42",
    "metadata": {"order_id": 42},
    "webhook_url": "https://webhook.site/replace-with-your-id"
  }'
```

Получение платежа:

```bash
curl http://localhost:8000/api/v1/payments/<payment_id> \
  -H "X-API-Key: local-secret-key"
```

Повторный POST с тем же `Idempotency-Key` возвращает созданный ранее платеж и не
создает второе Outbox-событие.

## Структура

```text
src/payment_service/
├── main.py          # FastAPI и два endpoint
├── schemas.py       # Pydantic-схемы
├── config.py        # настройки из environment
├── db.py            # async engine и session factory
├── models.py        # ORM-модели payments и outbox
├── repositories.py  # отдельный слой работы с БД
├── services.py      # создание Payment + Outbox в одной транзакции
├── broker.py        # RabbitMQ exchange, queue и DLQ
└── worker.py        # Outbox relay и единственный consumer
```

DB-слой представлен `PaymentRepository` и `OutboxRepository`. HTTP-обработчики и
consumer не содержат SQL-запросов напрямую.

## Поток обработки

1. API в одной PostgreSQL-транзакции сохраняет `payments` и `outbox`.
2. Фоновый цикл внутри процесса `consumer` читает неопубликованный Outbox через
   `FOR UPDATE SKIP LOCKED`, публикует событие и выставляет `published_at`.
3. FastStream consumer эмулирует шлюз с задержкой 2-5 секунд и вероятностью успеха 90%.
4. Consumer обновляет статус и отправляет webhook.
5. При технической ошибке выполняются три попытки с задержками 1 и 2 секунды.
6. После третьей ошибки сообщение отклоняется и RabbitMQ отправляет его в
   `payments.dlq` через dead-letter exchange.

## Проверки

```bash
python -m pip install -e ".[dev]"
pytest
ruff check .
mypy src
docker compose config --quiet
```

## Осознанные упрощения

Эта версия намеренно отражает ограничение 2-3 часа:

- Outbox relay и message handler запущены в одном процессе `consumer`;
- retry выполняется внутри handler и на время задержки удерживает consumer;
- отсутствуют domain entities, интерфейсы, Unit of Work и ORM-мапперы;
- нет processing lease и защиты от параллельной обработки одного события;
- сбой после успешного webhook до записи отметки может привести к повторному webhook;
- повторный idempotency key возвращает исходный платеж без сравнения нового payload;
- нет SSRF-защиты webhook URL, метрик и distributed tracing.

Для тестового задания эти компромиссы сохраняют читаемость и демонстрируют требуемые
технологии. Для production retry следует вынести в TTL/delayed queues, добавить
consumer idempotency/lease и защитить исходящие webhook-запросы.
