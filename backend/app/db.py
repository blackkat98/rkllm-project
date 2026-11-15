from collections.abc import AsyncIterator
from datetime import datetime, timezone

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_db(url: str) -> AsyncEngine:
    global _engine, _sessionmaker
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs = {}
    _engine = create_async_engine(url, **kwargs)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    assert _engine is not None, "init_db() not called"
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    assert _sessionmaker is not None, "init_db() not called"
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as session:
        yield session
