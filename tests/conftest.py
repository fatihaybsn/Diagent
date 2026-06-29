"""Shared test fixtures for Diagent."""

import asyncio
from collections.abc import AsyncGenerator, Generator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from diagent.api.app import create_app
from diagent.config import settings
from diagent.database import get_session
from diagent.models.base import Base

# Import all models so metadata is fully populated
import diagent.models  # noqa: F401


# ── Sync helpers (table management) ──

def _get_sync_test_url() -> str:
    """Convert the async DATABASE_URL to the installed sync psycopg2 driver."""
    return settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"
    )


_sync_engine = create_engine(_get_sync_test_url(), poolclass=NullPool)

# Create all tables before any test runs (sync — no event loop needed)
Base.metadata.create_all(bind=_sync_engine)


# ── Test async engine ──

test_engine = create_async_engine(settings.database_url, echo=False, poolclass=NullPool)
test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)


# ── Event loop ──

@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for all tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Drop tables at end of session ──

@pytest.fixture(scope="session", autouse=True)
def _manage_tables():
    """Drop all tables at the end of the test session."""
    yield
    Base.metadata.drop_all(bind=_sync_engine)
    _sync_engine.dispose()


# ── Truncate all tables after each test ──

@pytest.fixture(autouse=True)
def _clean_tables():
    """Truncate all tables after each test to ensure isolation (sync)."""
    yield
    with _sync_engine.connect() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f'TRUNCATE TABLE "{table.name}" CASCADE'))
        conn.commit()


# ── Async DB session for direct DB access in tests ──

@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_session_factory() as session:
        yield session


# ── Override get_session dependency ──

async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_session_factory() as session:
        yield session


# ── HTTP client ──

@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client wired to the test database."""
    app = create_app()
    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Mock Celery tasks (no Redis in test) ──

@pytest.fixture(autouse=True)
def _mock_celery(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent Celery tasks from actually enqueuing during tests."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import diagent.workers.tasks as tasks_module

    async_result = SimpleNamespace(id="test-task-id")
    monkeypatch.setattr(
        tasks_module.run_anomaly_detection,
        "delay",
        MagicMock(return_value=async_result),
    )
    monkeypatch.setattr(
        tasks_module.run_rag_evaluation,
        "delay",
        MagicMock(return_value=async_result),
    )
    monkeypatch.setattr(
        tasks_module.run_diagnosis,
        "delay",
        MagicMock(return_value=async_result),
    )


# ── Sync engine for detector tests ──

@pytest.fixture
def sync_engine() -> Generator[Engine, None, None]:
    """Sync SQLAlchemy engine for testing core detector functions."""
    engine = create_engine(_get_sync_test_url())
    yield engine
    engine.dispose()
