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

            # Run migrations for new columns (ALTER TABLE doesn't happen with create_all)
            migrations = [
                # Add inbox_type column to support_emails if it doesn't exist
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'support_emails' AND column_name = 'inbox_type'
                    ) THEN
                        ALTER TABLE support_emails ADD COLUMN inbox_type VARCHAR(20) DEFAULT 'support';
                        CREATE INDEX IF NOT EXISTS idx_support_emails_inbox_type ON support_emails(inbox_type);
                    END IF;
                END $$;
                """,
                # Add sender_type column to support_emails if it doesn't exist
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'support_emails' AND column_name = 'sender_type'
                    ) THEN
                        ALTER TABLE support_emails ADD COLUMN sender_type VARCHAR(20) DEFAULT 'customer';
                    END IF;
                END $$;
                """,
                # Add ticket system fields to support_emails
                """
                DO $$
                BEGIN
                    -- Resolution fields
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'support_emails' AND column_name = 'resolution') THEN
                        ALTER TABLE support_emails ADD COLUMN resolution VARCHAR(50);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'support_emails' AND column_name = 'resolution_notes') THEN
                        ALTER TABLE support_emails ADD COLUMN resolution_notes TEXT;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'support_emails' AND column_name = 'resolved_by') THEN
                        ALTER TABLE support_emails ADD COLUMN resolved_by INTEGER REFERENCES users(id);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'support_emails' AND column_name = 'resolved_at') THEN
                        ALTER TABLE support_emails ADD COLUMN resolved_at TIMESTAMP;
                    END IF;
                    -- Time tracking fields
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'support_emails' AND column_name = 'first_response_at') THEN
                        ALTER TABLE support_emails ADD COLUMN first_response_at TIMESTAMP;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'support_emails' AND column_name = 'response_time_minutes') THEN
                        ALTER TABLE support_emails ADD COLUMN response_time_minutes INTEGER;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'support_emails' AND column_name = 'resolution_time_minutes') THEN
                        ALTER TABLE support_emails ADD COLUMN resolution_time_minutes INTEGER;
                    END IF;
                    -- Order & Tracking fields
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'support_emails' AND column_name = 'order_number') THEN
                        ALTER TABLE support_emails ADD COLUMN order_number VARCHAR(50);
                        CREATE INDEX IF NOT EXISTS idx_support_emails_order ON support_emails(order_number);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'support_emails' AND column_name = 'tracking_number') THEN
                        ALTER TABLE support_emails ADD COLUMN tracking_number VARCHAR(100);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'support_emails' AND column_name = 'tracking_carrier') THEN
                        ALTER TABLE support_emails ADD COLUMN tracking_carrier VARCHAR(50);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'support_emails' AND column_name = 'tracking_status') THEN
                        ALTER TABLE support_emails ADD COLUMN tracking_status VARCHAR(100);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'support_emails' AND column_name = 'tracking_last_checked') THEN
                        ALTER TABLE support_emails ADD COLUMN tracking_last_checked TIMESTAMP;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'support_emails' AND column_name = 'estimated_delivery') THEN
                        ALTER TABLE support_emails ADD COLUMN estimated_delivery TIMESTAMP;
                    END IF;
                END $$;
                """,
                # Add followup draft columns to shipment_tracking
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'shipment_tracking' AND column_name = 'followup_draft_subject') THEN
                        ALTER TABLE shipment_tracking ADD COLUMN followup_draft_subject TEXT;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'shipment_tracking' AND column_name = 'followup_draft_body') THEN
                        ALTER TABLE shipment_tracking ADD COLUMN followup_draft_body TEXT;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'shipment_tracking' AND column_name = 'followup_draft_generated_at') THEN
                        ALTER TABLE shipment_tracking ADD COLUMN followup_draft_generated_at TIMESTAMP;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'shipment_tracking' AND column_name = 'followup_status') THEN
                        ALTER TABLE shipment_tracking ADD COLUMN followup_status VARCHAR(20) DEFAULT 'none';
                    END IF;
                END $$;
                """,
                # Enrich products table with catalog fields
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'products' AND column_name = 'description') THEN
                        ALTER TABLE products ADD COLUMN description TEXT;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'products' AND column_name = 'handle') THEN
                        ALTER TABLE products ADD COLUMN handle VARCHAR(500);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'products' AND column_name = 'product_type') THEN
                        ALTER TABLE products ADD COLUMN product_type VARCHAR(255);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'products' AND column_name = 'vendor') THEN
                        ALTER TABLE products ADD COLUMN vendor VARCHAR(255);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'products' AND column_name = 'tags') THEN
                        ALTER TABLE products ADD COLUMN tags JSONB;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'products' AND column_name = 'featured_image_url') THEN
                        ALTER TABLE products ADD COLUMN featured_image_url TEXT;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'products' AND column_name = 'images') THEN
                        ALTER TABLE products ADD COLUMN images JSONB;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'products' AND column_name = 'price_min') THEN
                        ALTER TABLE products ADD COLUMN price_min NUMERIC(10,2);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'products' AND column_name = 'price_max') THEN
                        ALTER TABLE products ADD COLUMN price_max NUMERIC(10,2);
                    END IF;
                END $$;
                """,
                # Add content_briefs to social_media_strategies
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'social_media_strategies' AND column_name = 'content_briefs') THEN
                        ALTER TABLE social_media_strategies ADD COLUMN content_briefs JSONB;
                    END IF;
                END $$;
                """,
                # Add content_category to social_media_posts
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'social_media_posts' AND column_name = 'content_category') THEN
                        ALTER TABLE social_media_posts ADD COLUMN content_category VARCHAR(50);
                    END IF;
                END $$;
                """,
                # Add media storage columns to social_media_posts
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'social_media_posts' AND column_name = 'media_data') THEN
                        ALTER TABLE social_media_posts ADD COLUMN media_data TEXT;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'social_media_posts' AND column_name = 'media_data_format') THEN
                        ALTER TABLE social_media_posts ADD COLUMN media_data_format VARCHAR(10);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'social_media_posts' AND column_name = 'media_thumbnail') THEN
                        ALTER TABLE social_media_posts ADD COLUMN media_thumbnail TEXT;
                    END IF;
                END $$;
                """,
                # Add media_carousel column to social_media_posts
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'social_media_posts' AND column_name = 'media_carousel') THEN
                        ALTER TABLE social_media_posts ADD COLUMN media_carousel JSONB;
                    END IF;
                END $$;
                """,
                # Add ig_overlays column to social_media_posts
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'social_media_posts' AND column_name = 'ig_overlays') THEN
                        ALTER TABLE social_media_posts ADD COLUMN ig_overlays JSONB;
                    END IF;
                END $$;
                """,
                # Add shipping_cost column to orders (actual cost from shipping matrix)
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'shipping_cost') THEN
                        ALTER TABLE orders ADD COLUMN shipping_cost NUMERIC(10, 2) DEFAULT 0;
                    END IF;
                END $$;
                """,
                # Add content_intent column to content_assets (organic vs acquisition)
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'content_assets' AND column_name = 'content_intent'
                    ) THEN
                        ALTER TABLE content_assets ADD COLUMN content_intent VARCHAR(20);
                    END IF;
                END $$;
                """,
                # Add approval workflow columns to agent_tasks
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'agent_tasks' AND column_name = 'requires_approval') THEN
                        ALTER TABLE agent_tasks ADD COLUMN requires_approval BOOLEAN DEFAULT FALSE;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'agent_tasks' AND column_name = 'approved_by') THEN
                        ALTER TABLE agent_tasks ADD COLUMN approved_by INTEGER;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'agent_tasks' AND column_name = 'approved_at') THEN
                        ALTER TABLE agent_tasks ADD COLUMN approved_at TIMESTAMP;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'agent_tasks' AND column_name = 'decision_uuid') THEN
                        ALTER TABLE agent_tasks ADD COLUMN decision_uuid VARCHAR(50);
                        CREATE INDEX IF NOT EXISTS idx_agent_task_decision_uuid ON agent_tasks(decision_uuid);
                    END IF;
                END $$;
                """,
            ]

            for migration in migrations:
                try:
                    await conn.execute(text(migration))
                except Exception as me:
                    print(f"⚠️ Migration note: {me}")

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
