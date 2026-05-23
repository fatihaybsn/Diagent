"""Shared test fixtures for Diagent."""

import asyncio
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from diagent.api.app import create_app
from diagent.config import settings
from diagent.database import get_session
from diagent.models.base import Base

import diagent.models

def _get_sync_test_url() -> str:
    return settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"
    )

_sync_engine = create_engine(_get_sync_test_url(), poolclass=NullPool)
Base.metadata.create_all(bind=_sync_engine)

test_engine = create_async_engine(settings.database_url, echo=False, poolclass=NullPool)
test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session", autouse=True)
def _manage_tables():
    yield
    Base.metadata.drop_all(bind=_sync_engine)
    _sync_engine.dispose()

@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    with _sync_engine.connect() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f'TRUNCATE TABLE "{table.name}" CASCADE'))
        conn.commit()

@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_session_factory() as session:
        yield session

async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_session_factory() as session:
        yield session

@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app()
    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
