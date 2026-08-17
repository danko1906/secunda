from functools import lru_cache
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Payment Processing Service"
    app_environment: str = "development"
    log_level: str = "INFO"
    api_key: SecretStr = SecretStr("change-me")
    database_url: str = "postgresql+asyncpg://payments:payments@localhost:5432/payments"
    rabbitmq_url: str = "amqp://payments:payments@localhost:5672/"
    outbox_poll_interval_seconds: float = Field(default=0.5, gt=0)
    outbox_batch_size: int = Field(default=50, ge=1, le=500)
    gateway_min_delay_seconds: float = Field(default=2.0, ge=0)
    gateway_max_delay_seconds: float = Field(default=5.0, ge=0)
    gateway_success_rate: float = Field(default=0.9, ge=0, le=1)
    webhook_timeout_seconds: float = Field(default=5.0, gt=0)
    processing_lease_seconds: int = Field(default=30, ge=10, le=300)
    consumer_prefetch_count: int = Field(default=1, ge=1, le=100)
    retry_delay_1_seconds: int = Field(default=2, gt=0)
    retry_delay_2_seconds: int = Field(default=4, gt=0)

    @model_validator(mode="after")
    def validate_processing_timings(self) -> Self:
        if self.gateway_min_delay_seconds > self.gateway_max_delay_seconds:
            raise ValueError("Gateway minimum delay cannot exceed maximum delay")
        minimum_lease = self.gateway_max_delay_seconds + self.webhook_timeout_seconds
        if self.processing_lease_seconds <= minimum_lease:
            raise ValueError(
                "Processing lease must exceed the maximum gateway delay plus webhook timeout"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
