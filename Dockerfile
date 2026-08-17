FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system app && useradd --system --gid app --create-home app

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --upgrade pip && python -m pip install .

COPY alembic.ini ./
COPY alembic ./alembic

USER app

EXPOSE 8000

CMD ["uvicorn", "payment_service.main:app", "--host", "0.0.0.0", "--port", "8000"]

