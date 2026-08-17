# Асинхронный сервис процессинга платежей

Тестовый микросервис на FastAPI, SQLAlchemy 2.0, PostgreSQL, RabbitMQ и FastStream.
Создание платежа и Outbox-события происходит атомарно; доставка событий и webhook
имеет семантику at-least-once.

## Быстрый запуск

Требования: Docker Engine с Docker Compose v2.

```bash
docker compose up --build
```

После запуска доступны:

- API и Swagger: <http://localhost:8000/docs>
- RabbitMQ Management: <http://localhost:15672> (`payments` / `payments`)
- webhook mock: `http://webhook-mock:8001/webhook` из Docker-сети

Создание платежа:

```bash
curl -i -X POST http://localhost:8000/api/v1/payments \
  -H "X-API-Key: local-secret-key" \
  -H "Idempotency-Key: order-42-payment-v1" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "1250.50",
    "currency": "RUB",
    "description": "Order #42",
    "metadata": {"order_id": 42},
    "webhook_url": "http://webhook-mock:8001/webhook"
  }'
```

Получение платежа:

```bash
curl http://localhost:8000/api/v1/payments/<payment_id> \
  -H "X-API-Key: local-secret-key"
```

Повтор POST с тем же ключом и тем же телом вернет исходный платеж. Тот же ключ с
другим телом вернет `409 Conflict`.

Остановка:

```bash
docker compose down
```

Данные сохраняются в named volumes. Для полного локального сброса стенда:

```bash
docker compose down --volumes
```

## Архитектура

```text
Client -> FastAPI -> PostgreSQL (payments + outbox in one transaction)
                           |
                     Outbox relay
                           |
                     RabbitMQ payments.new
                           |
                        Consumer
                       /        \
                PostgreSQL    Webhook
                                  |
                         retry queues -> DLQ
```

Процессы разделены намеренно:

- `api` обслуживает HTTP и не публикует сообщения внутри запроса;
- `outbox-relay` блокирует пачку через `FOR UPDATE SKIP LOCKED`, публикует с
  publisher confirms и только затем выставляет `published_at`;
- `consumer` — единственный RabbitMQ-обработчик платежа и webhook;
- `migrate` выполняет Alembic перед стартом приложений.

## Гарантии и моменты отказа

Сервис дает гарантию **at-least-once**, а не exactly-once.

1. `payment` и `outbox` создаются одной PostgreSQL-транзакцией.
2. Если relay упадет после publish, но до `published_at`, событие будет отправлено
   повторно.
3. Повторное сообщение не вызывает платежный шлюз для терминального платежа.
4. После успешного webhook сохраняется `webhook_delivered_at`, поэтому обычный дубль
   сообщения не отправляет webhook повторно.
5. Перед gateway/webhook consumer атомарно получает ограниченный по времени processing
   lease. Поэтому конкурентные deliveries не выполняют внешние side effects одновременно.
6. Падение между успешным HTTP-вызовом webhook и сохранением отметки все еще может
   дать дубль. Получатель может дедуплицировать его по стабильному заголовку
   `X-Webhook-Event-Id`.

Бизнес-результат шлюза `failed` не является технической ошибкой и не ретраится. По
нему отправляется обычный webhook. Ошибка HTTP/БД/consumer запускает broker retry.

## RabbitMQ topology и retry

- direct exchange `payments` -> durable queue `payments.new`;
- direct exchange `payments.retry` -> TTL-очереди `payments.retry.2s` и
  `payments.retry.4s`;
- после TTL retry-очередь dead-letter'ит сообщение обратно в `payments.new`;
- direct exchange `payments.dlx` -> durable queue `payments.dlq`.

Считаются **три технические ошибки всего**: исходная, через 2 секунды и через 4 секунды.
Счетчик хранится в PostgreSQL, поэтому повторная публикация того же outbox-события не
сбрасывает retry budget. После третьей ошибки consumer делает reject, и сообщение
оказывается в DLQ. Конкурентный дубль, встретивший активный processing lease, откладывается
без расходования retry budget. Сначала
подтверждается публикация retry-сообщения, и только потом ACK исходного. При ошибке
публикации retry исходное сообщение остается доступным через NACK.

Publisher confirms включены вместе с `mandatory` и `on_return_raises`: unroutable
сообщение считается ошибкой и не приводит к выставлению `outbox.published_at`.

Задержки вынесены в environment variables; при их изменении на существующем RabbitMQ
нужно пересоздать локальный volume, потому что аргументы уже объявленной очереди
неизменяемы.

## API-контракт

- `POST /api/v1/payments` -> `202 Accepted`;
- `GET /api/v1/payments/{payment_id}` -> `200 OK`;
- обязательные заголовки: `X-API-Key`, а для POST также `Idempotency-Key`;
- `amount` — положительный decimal до 18 цифр и двух знаков после запятой;
- валюты: `RUB`, `USD`, `EUR`;
- отсутствующий платеж -> `404`;
- повторное использование idempotency key с другим payload -> `409`.

Health endpoint `/health/live` намеренно не защищен API-ключом, чтобы его могли
вызывать Docker/Kubernetes probes. Все бизнес-эндпоинты защищены.

## Разработка и проверки

Python 3.12+:

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
pytest
ruff check .
mypy src
```

PostgreSQL integration-тесты атомарного rollback и конкурентного claim запускаются
отдельно на уже мигрированной тестовой БД:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://payments:payments@localhost:5432/payments \
pytest -m integration
```

Проверка compose-конфигурации:

```bash
docker compose config --quiet
```

Основные тесты покрывают создание `payment + outbox`, семантику Idempotency-Key,
конкурентный processing claim, отсутствие повторного вызова шлюза/webhook, publisher
confirm contract и общий лимит трех ошибок. Атомарный rollback проверяется отдельным
PostgreSQL integration-тестом.

## Осознанные ограничения тестового решения

- webhook URL принимается от клиента. В production нужна SSRF-защита: HTTPS,
  allowlist доменов и блокировка private/link-local адресов;
- статический API key подходит только для тестового задания; production-вариант
  потребует ротации и идентификации клиента;
- Outbox relay держит короткую DB-транзакцию во время publish. Для высокой нагрузки
  стоит использовать lease/claim-поля и публиковать вне транзакции;
- DLQ требует операционного процесса: alert, анализ причины и контролируемый replay;
- метрики и distributed tracing не добавлены, но structured JSON-логи содержат
  `payment_id`, `event_id` и `attempt`.
