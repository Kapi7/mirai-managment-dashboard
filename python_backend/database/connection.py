"""
Database connection management for PostgreSQL
"""
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import text

# Get database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Convert postgres:// to postgresql+asyncpg:// for async driver
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# SQLAlchemy base for models
Base = declarative_base()

# Global engine and session factory
_engine = None
_async_session_factory = None


def get_engine():
    """Get or create the async engine"""
    global _engine
    if _engine is None and DATABASE_URL:
        _engine = create_async_engine(
            DATABASE_URL,
            echo=False,  # Set to True for SQL debugging
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True
        )
    return _engine


def get_session_factory():
    """Get or create the session factory"""
    global _async_session_factory
    if _async_session_factory is None:
        engine = get_engine()
        if engine:
            _async_session_factory = async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
    return _async_session_factory


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for database sessions.
    Usage:
        async with get_db() as db:
            result = await db.execute(query)
    """
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Database not configured. Set DATABASE_URL environment variable.")

    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """
    Initialize database - create all tables.
    Should be called on application startup.
    """
    engine = get_engine()
    if engine is None:
        print("⚠️ DATABASE_URL not set - running without database")
        return False

    try:
        async with engine.begin() as conn:
            # Import models to register them with Base
            from . import models
            await conn.run_sync(Base.metadata.create_all)
        print("✅ Database initialized successfully")
        return True
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        return False


async def close_db():
    """Close database connections"""
    global _engine, _async_session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _async_session_factory = None
        print("✅ Database connections closed")


async def check_db_connection() -> bool:
    """Check if database is accessible"""
    try:
        async with get_db() as db:
            await db.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"❌ Database connection check failed: {e}")
        return False


def is_db_configured() -> bool:
    """Check if database URL is configured"""
    return bool(DATABASE_URL)
