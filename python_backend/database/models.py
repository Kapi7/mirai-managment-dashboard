"""
SQLAlchemy models for Mirai Dashboard database
"""
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, DateTime, Date, Boolean,
    ForeignKey, Text, Numeric, JSON, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from .connection import Base


class Store(Base):
    """Multi-store support"""
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True)
    key = Column(String(50), unique=True, nullable=False)  # 'skin', 'cosmetics'
    label = Column(String(100), nullable=False)            # 'Mirai Skin'
    shopify_domain = Column(String(255))
    timezone = Column(String(50), default='UTC')
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    products = relationship("Product", back_populates="store")
    variants = relationship("Variant", back_populates="store")
    orders = relationship("Order", back_populates="store")


class Product(Base):
    """Shopify products"""
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    shopify_gid = Column(String(100), unique=True, nullable=False)
    store_id = Column(Integer, ForeignKey("stores.id"))
    title = Column(String(500), nullable=False)
    status = Column(String(50))  # active, archived, draft
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    store = relationship("Store", back_populates="products")
    variants = relationship("Variant", back_populates="product")


class Variant(Base):
    """Shopify product variants"""
    __tablename__ = "variants"

    id = Column(Integer, primary_key=True)
    shopify_gid = Column(String(100), unique=True, nullable=False)
    variant_id = Column(String(50), nullable=False, index=True)  # numeric ID
    product_id = Column(Integer, ForeignKey("products.id"))
    store_id = Column(Integer, ForeignKey("stores.id"))
    sku = Column(String(100), index=True)
    title = Column(String(500))
    price = Column(Numeric(10, 2))
    compare_at_price = Column(Numeric(10, 2))
    cogs = Column(Numeric(10, 2))  # from inventory item
    weight_g = Column(Integer)
    inventory_item_gid = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    product = relationship("Product", back_populates="variants")
    store = relationship("Store", back_populates="variants")
    line_items = relationship("OrderLineItem", back_populates="variant")
    competitor_scans = relationship("CompetitorScan", back_populates="variant")
    price_updates = relationship("PriceUpdate", back_populates="variant")


class Customer(Base):
    """Shopify customers"""
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True)
    shopify_gid = Column(String(100), unique=True)
    email = Column(String(255), index=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    order_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    orders = relationship("Order", back_populates="customer")


class Order(Base):
    """Shopify orders"""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    shopify_gid = Column(String(100), unique=True, nullable=False)
    order_name = Column(String(50), nullable=False)  # #1234
    store_id = Column(Integer, ForeignKey("stores.id"))
    customer_id = Column(Integer, ForeignKey("customers.id"))

    # Timestamps
    created_at = Column(DateTime, nullable=False, index=True)
    processed_at = Column(DateTime)
    cancelled_at = Column(DateTime)

    # Financials
    gross = Column(Numeric(10, 2), default=0)
    discounts = Column(Numeric(10, 2), default=0)
    refunds = Column(Numeric(10, 2), default=0)
    net = Column(Numeric(10, 2), default=0)
    cogs = Column(Numeric(10, 2), default=0)
    shipping_charged = Column(Numeric(10, 2), default=0)

    # Location
    country = Column(String(100))
    country_code = Column(String(10), index=True)
    total_weight_g = Column(Integer)

    # Attribution
    utm_source = Column(String(255))
    utm_medium = Column(String(255))
    utm_campaign = Column(String(255))
    referrer_url = Column(Text)
    source_name = Column(String(100))
    channel = Column(String(50), index=True)  # google, meta, organic, klaviyo, direct

    # Flags
    is_returning = Column(Boolean, default=False)
    is_test = Column(Boolean, default=False)

    # Relationships
    store = relationship("Store", back_populates="orders")
    customer = relationship("Customer", back_populates="orders")
    line_items = relationship("OrderLineItem", back_populates="order", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_order_date_store', 'created_at', 'store_id'),
    )


class OrderLineItem(Base):
    """Order line items"""
    __tablename__ = "order_line_items"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"))
    variant_id = Column(Integer, ForeignKey("variants.id"))
    quantity = Column(Integer, nullable=False)
    gross = Column(Numeric(10, 2))
    unit_cogs = Column(Numeric(10, 2))
    sku = Column(String(100))

    # Relationships
    order = relationship("Order", back_populates="line_items")
    variant = relationship("Variant", back_populates="line_items")


class AdSpend(Base):
    """Google & Meta ad spend"""
    __tablename__ = "ad_spend"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"))
    platform = Column(String(20), nullable=False)  # 'google', 'meta'
    account_id = Column(String(100))
    spend_usd = Column(Numeric(10, 2), nullable=False)
    spend_original = Column(Numeric(10, 2))
    currency = Column(String(10))
    purchases = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('date', 'store_id', 'platform', 'account_id', name='uq_ad_spend'),
    )


class ShippingRate(Base):
    """Shipping rate matrix"""
    __tablename__ = "shipping_rates"

    id = Column(Integer, primary_key=True)
    country = Column(String(100), nullable=False)
    country_code = Column(String(10))
    weight_tier_kg = Column(Numeric(5, 2), nullable=False)
    rate_usd = Column(Numeric(10, 2), nullable=False)
    carrier = Column(String(100))

    __table_args__ = (
        UniqueConstraint('country_code', 'weight_tier_kg', name='uq_shipping_rate'),
        Index('idx_shipping_lookup', 'country_code', 'weight_tier_kg'),
    )


class KorealyProduct(Base):
    """Korealy COGS data"""
    __tablename__ = "korealy_products"

    id = Column(Integer, primary_key=True)
    korealy_product_id = Column(String(100))
    shop_pid = Column(String(100), index=True)  # Shopify variant ID
    title = Column(String(500))
    cogs = Column(Numeric(10, 2))
    currency = Column(String(10), default='USD')
    supplier = Column(String(255))
    imported_at = Column(DateTime, default=datetime.utcnow)


class CompetitorScan(Base):
    """Competitor price scan results"""
    __tablename__ = "competitor_scans"

    id = Column(Integer, primary_key=True)
    variant_id = Column(Integer, ForeignKey("variants.id"), index=True)
    scanned_at = Column(DateTime, default=datetime.utcnow)
    country = Column(String(10), default='US')

    # Prices
    comp_low = Column(Numeric(10, 2))
    comp_avg = Column(Numeric(10, 2))
    comp_high = Column(Numeric(10, 2))

    # Counts
    raw_count = Column(Integer)
    trusted_count = Column(Integer)
    filtered_count = Column(Integer)

    # Top sellers (JSON array)
    top_sellers = Column(JSON)

    # Relationships
    variant = relationship("Variant", back_populates="competitor_scans")

    __table_args__ = (
        Index('idx_variant_scan', 'variant_id', 'scanned_at'),
    )


class PriceUpdate(Base):
    """Price update history"""
    __tablename__ = "price_updates"

    id = Column(Integer, primary_key=True)
    variant_id = Column(Integer, ForeignKey("variants.id"))
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    update_type = Column(String(50), nullable=False)  # 'price', 'compare_at', 'cogs'
    market = Column(String(10), default='US')
    old_price = Column(Numeric(10, 2))
    new_price = Column(Numeric(10, 2))
    old_compare_at = Column(Numeric(10, 2))
    new_compare_at = Column(Numeric(10, 2))
    change_pct = Column(Numeric(5, 2))
    status = Column(String(20), default='success')
    notes = Column(Text)
    source = Column(String(50))  # 'manual', 'korealy', 'bulk'

    # Relationships
    variant = relationship("Variant", back_populates="price_updates")


class DailyKPI(Base):
    """Pre-aggregated daily KPIs"""
    __tablename__ = "daily_kpis"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"))

    # Orders
    orders = Column(Integer, default=0)
    returning_orders = Column(Integer, default=0)

    # Financials
    gross = Column(Numeric(12, 2), default=0)
    discounts = Column(Numeric(12, 2), default=0)
    refunds = Column(Numeric(12, 2), default=0)
    net = Column(Numeric(12, 2), default=0)
    cogs = Column(Numeric(12, 2), default=0)
    shipping_charged = Column(Numeric(12, 2), default=0)
    shipping_cost = Column(Numeric(12, 2), default=0)
    psp_fee = Column(Numeric(12, 2), default=0)

    # Ad Spend
    google_spend = Column(Numeric(12, 2), default=0)
    meta_spend = Column(Numeric(12, 2), default=0)

    # Calculated
    operational_profit = Column(Numeric(12, 2), default=0)
    margin_pct = Column(Numeric(5, 2))
    aov = Column(Numeric(10, 2))

    # Attribution
    google_purchases = Column(Integer, default=0)
    meta_purchases = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint('date', 'store_id', name='uq_daily_kpi'),
    )


class SyncStatus(Base):
    """Track sync job status"""
    __tablename__ = "sync_status"

    id = Column(Integer, primary_key=True)
    sync_type = Column(String(50), nullable=False)  # orders, products, google_ads, etc.
    store_id = Column(Integer, ForeignKey("stores.id"))
    last_sync_at = Column(DateTime)
    last_sync_status = Column(String(20))  # success, failed
    records_synced = Column(Integer)
    error_message = Column(Text)

    __table_args__ = (
        UniqueConstraint('sync_type', 'store_id', name='uq_sync_status'),
    )


class DailyPspFee(Base):
    """Daily PSP (Payment Service Provider) fees from Shopify"""
    __tablename__ = "daily_psp_fees"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"))
    fee_amount = Column(Numeric(12, 2), nullable=False)  # In store currency (usually USD)
    currency = Column(String(10), default='USD')
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('date', 'store_id', name='uq_daily_psp_fee'),
    )


class User(Base):
    """Users with Google Login"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255))
    picture = Column(String(500))  # Google profile picture URL
    google_id = Column(String(100), unique=True)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)
