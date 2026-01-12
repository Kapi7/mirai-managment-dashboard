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


class SupportEmail(Base):
    """Support email threads - Ticket System"""
    __tablename__ = "support_emails"

    id = Column(Integer, primary_key=True)
    thread_id = Column(String(255), unique=True, index=True)  # Gmail thread ID
    message_id = Column(String(255))  # Gmail message ID
    customer_email = Column(String(255), nullable=False, index=True)
    customer_name = Column(String(255))
    subject = Column(Text)

    # Inbox source
    inbox_type = Column(String(20), default='support', index=True)  # 'emma' (sales) or 'support'

    # Sender classification
    sender_type = Column(String(20), default='customer')  # 'customer', 'supplier', 'automated', 'internal'

    # Classification
    status = Column(String(50), default='pending', index=True)  # pending, draft_ready, approved, sent, rejected, resolved
    classification = Column(String(50))  # support, sales, support_sales
    intent = Column(String(100))  # tracking, return, product_question, complaint, etc.
    priority = Column(String(20), default='medium')  # low, medium, high, urgent
    sales_opportunity = Column(Boolean, default=False)

    # Ticket System - Resolution
    resolution = Column(String(50))  # resolved, escalated, refunded, replaced, waiting_customer, closed, no_action_needed
    resolution_notes = Column(Text)  # Notes about how it was resolved
    resolved_by = Column(Integer, ForeignKey("users.id"))
    resolved_at = Column(DateTime)

    # Ticket System - Time Tracking
    first_response_at = Column(DateTime)  # When first response was sent
    response_time_minutes = Column(Integer)  # Time from received to first response
    resolution_time_minutes = Column(Integer)  # Time from received to resolved

    # Order & Tracking Info (extracted from conversation)
    order_number = Column(String(50), index=True)  # Shopify order # (e.g., #2191)
    tracking_number = Column(String(100))  # Package tracking number
    tracking_carrier = Column(String(50))  # Korea Post, DHL, EMS, etc.
    tracking_status = Column(String(100))  # Latest status from AfterShip
    tracking_last_checked = Column(DateTime)  # When we last checked
    estimated_delivery = Column(DateTime)  # ETA from tracking

    # AI processing
    ai_confidence = Column(Numeric(3, 2))  # 0.00 to 1.00

    # Timestamps
    received_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    messages = relationship("SupportMessage", back_populates="email", cascade="all, delete-orphan")
    resolver = relationship("User", foreign_keys=[resolved_by])

    __table_args__ = (
        Index('idx_support_email_status', 'status', 'received_at'),
        Index('idx_support_email_resolution', 'resolution', 'resolved_at'),
        Index('idx_support_email_order', 'order_number'),
    )


class SupportMessage(Base):
    """Individual messages in a support thread"""
    __tablename__ = "support_messages"

    id = Column(Integer, primary_key=True)
    email_id = Column(Integer, ForeignKey("support_emails.id", ondelete="CASCADE"))

    # Message details
    direction = Column(String(10), nullable=False)  # inbound, outbound
    sender_email = Column(String(255))
    sender_name = Column(String(255))
    content = Column(Text, nullable=False)  # Original message content
    content_html = Column(Text)  # HTML version if available

    # AI draft (for outbound)
    ai_draft = Column(Text)  # AI-generated response
    ai_model = Column(String(50))  # Model used (gpt-4o-mini, etc.)
    ai_reasoning = Column(Text)  # AI's reasoning for the response

    # Approval workflow
    final_content = Column(Text)  # Edited/approved content
    approved_by = Column(Integer, ForeignKey("users.id"))
    approved_at = Column(DateTime)
    sent_at = Column(DateTime)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    email = relationship("SupportEmail", back_populates="messages")
    approver = relationship("User", foreign_keys=[approved_by])


class ShipmentTracking(Base):
    """Proactive shipment tracking - monitors all active shipments"""
    __tablename__ = "shipment_tracking"

    id = Column(Integer, primary_key=True)
    order_id = Column(String(50), index=True)  # Shopify order ID
    order_number = Column(String(50), index=True)  # Shopify order # (e.g., #2191)
    customer_email = Column(String(255), index=True)
    customer_name = Column(String(255))

    # Tracking details
    tracking_number = Column(String(100), unique=True, index=True)
    carrier = Column(String(50))  # Korea Post, DHL, EMS, USPS, etc.
    carrier_code = Column(String(20))  # AfterShip carrier code

    # Status from AfterShip
    status = Column(String(50), default='pending')  # pending, in_transit, out_for_delivery, delivered, exception, expired
    status_detail = Column(String(255))  # More detailed status text
    last_checkpoint = Column(Text)  # Last checkpoint description
    last_checkpoint_time = Column(DateTime)

    # Delivery info
    shipped_at = Column(DateTime)
    estimated_delivery = Column(DateTime)
    delivered_at = Column(DateTime)
    delivery_address_city = Column(String(100))
    delivery_address_country = Column(String(100))

    # Proactive outreach
    delay_detected = Column(Boolean, default=False)
    delay_days = Column(Integer)  # How many days delayed
    customer_notified_delay = Column(Boolean, default=False)
    delivery_followup_sent = Column(Boolean, default=False)  # Post-delivery sales email sent

    # Followup email draft (for approval workflow)
    followup_draft_subject = Column(Text)
    followup_draft_body = Column(Text)
    followup_draft_generated_at = Column(DateTime)
    followup_status = Column(String(20), default='none')  # none, draft_ready, approved, sent, rejected

    # Timestamps
    last_checked = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_shipment_status', 'status', 'last_checked'),
        Index('idx_shipment_delivery', 'delivered_at', 'delivery_followup_sent'),
    )


class AIConversationLog(Base):
    """Log AI interactions for learning and improvement"""
    __tablename__ = "ai_conversation_logs"

    id = Column(Integer, primary_key=True)
    email_id = Column(Integer, ForeignKey("support_emails.id"), index=True)
    message_id = Column(Integer, ForeignKey("support_messages.id"))

    # Request context
    customer_email = Column(String(255))
    customer_name = Column(String(255))
    customer_message = Column(Text)  # What customer said
    conversation_history = Column(Text)  # Previous messages (JSON)

    # Tools used
    tools_called = Column(Text)  # JSON list of tools called
    tool_results = Column(Text)  # JSON results from tools
    customer_profile = Column(Text)  # JSON customer profile retrieved

    # AI Response
    ai_response = Column(Text)  # Emma's response
    ai_model = Column(String(50))  # gpt-4o-mini, etc.
    response_time_ms = Column(Integer)  # How long it took
    tokens_used = Column(Integer)

    # Quality metrics (filled in after human review)
    was_approved = Column(Boolean)  # Did human approve as-is?
    was_edited = Column(Boolean)  # Was it edited before sending?
    edit_distance = Column(Integer)  # How much was edited (char diff)
    quality_rating = Column(Integer)  # 1-5 rating from reviewer

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
