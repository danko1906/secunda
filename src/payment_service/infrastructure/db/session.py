from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from payment_service.core.config import get_settings

settings = get_settings()
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=300,
)
session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
