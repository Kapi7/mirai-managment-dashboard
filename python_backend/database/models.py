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


# ============================================================
# BLOG CONTENT SYSTEM
# ============================================================

# ============================================================
# SOCIAL MEDIA CONTENT SYSTEM
# ============================================================

class SocialMediaStrategy(Base):
    """Social media strategy plans that require approval before content creation"""
    __tablename__ = "social_media_strategies"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(50), unique=True, nullable=False, index=True)
    title = Column(Text, nullable=False)
    description = Column(Text)
    goals = Column(JSON)  # List of goals (audience growth, engagement, sales)
    content_mix = Column(JSON)  # Ratio plan: {reels: 40, photos: 40, product: 20}
    posting_frequency = Column(JSON)  # Posts per week, best times
    hashtag_strategy = Column(JSON)  # Core + rotating hashtags
    date_range_start = Column(Date)
    date_range_end = Column(Date)
    status = Column(String(50), default='draft', index=True)  # draft, pending_review, approved, rejected, active, completed
    created_by = Column(String(255))  # User email
    approved_by = Column(Integer, ForeignKey("users.id"))
    approved_at = Column(DateTime)
    rejection_reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    posts = relationship("SocialMediaPost", back_populates="strategy", cascade="all, delete-orphan")
    approver = relationship("User", foreign_keys=[approved_by])

    __table_args__ = (
        Index('idx_sm_strategy_status', 'status', 'created_at'),
    )


class SocialMediaPost(Base):
    """Individual social media content pieces in the calendar"""
    __tablename__ = "social_media_posts"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(50), unique=True, nullable=False, index=True)
    strategy_id = Column(Integer, ForeignKey("social_media_strategies.id"))
    post_type = Column(String(30))  # photo, reel, carousel, product_feature
    caption = Column(Text)
    visual_direction = Column(Text)  # AI description of what the visual should be
    media_url = Column(Text)  # URL of uploaded media
    media_type = Column(String(20))  # IMAGE, VIDEO, CAROUSEL_ALBUM
    media_data = Column(Text, nullable=True)        # base64-encoded full image
    media_data_format = Column(String(10), nullable=True)  # "png", "jpeg", "mp4"
    media_thumbnail = Column(Text, nullable=True)    # base64 JPEG thumbnail (256px)
    product_ids = Column(JSON)  # Linked Shopify product GIDs
    link_url = Column(Text)  # Website link with UTM params
    utm_source = Column(String(50), default='instagram')
    utm_medium = Column(String(50), default='organic')
    utm_campaign = Column(String(100))
    scheduled_at = Column(DateTime)
    status = Column(String(50), default='draft', index=True)  # draft, pending_review, approved, scheduled, publishing, published, failed, rejected
    rejection_reason = Column(Text)
    ig_container_id = Column(String(100))
    ig_media_id = Column(String(100))
    fb_post_id = Column(String(100))
    published_at = Column(DateTime)
    approved_by = Column(Integer, ForeignKey("users.id"))
    approved_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    strategy = relationship("SocialMediaStrategy", back_populates="posts")
    approver = relationship("User", foreign_keys=[approved_by])
    insights = relationship("SocialMediaInsight", back_populates="post", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_sm_post_status', 'status', 'scheduled_at'),
        Index('idx_sm_post_schedule', 'scheduled_at'),
    )


class SocialMediaInsight(Base):
    """Post performance metrics synced from Instagram Insights API"""
    __tablename__ = "social_media_insights"

    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("social_media_posts.id", ondelete="CASCADE"))
    ig_media_id = Column(String(100))
    impressions = Column(Integer, default=0)
    reach = Column(Integer, default=0)
    engagement = Column(Integer, default=0)  # likes + comments + shares + saves
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    saves = Column(Integer, default=0)
    video_views = Column(Integer, default=0)
    profile_visits = Column(Integer, default=0)
    website_clicks = Column(Integer, default=0)
    follower_delta = Column(Integer, default=0)
    synced_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    post = relationship("SocialMediaPost", back_populates="insights")


class SocialMediaProfileCache(Base):
    """Cached Instagram profile data for brand voice analysis"""
    __tablename__ = "social_media_profile_cache"

    id = Column(Integer, primary_key=True)
    ig_account_id = Column(String(100), unique=True)
    followers_count = Column(Integer, default=0)
    media_count = Column(Integer, default=0)
    recent_captions = Column(JSON)  # Last 25 captions for voice analysis
    brand_voice_analysis = Column(Text)  # AI-generated voice/tone summary
    best_posting_times = Column(JSON)  # Data-driven optimal times
    top_hashtags = Column(JSON)  # Best performing hashtags
    synced_at = Column(DateTime, default=datetime.utcnow)


class SocialMediaAccountSnapshot(Base):
    """Daily account-level Instagram metrics for historical tracking"""
    __tablename__ = "social_media_account_snapshots"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)
    ig_account_id = Column(String(100), nullable=False)

    # Account-level metrics (from IG Insights API)
    impressions = Column(Integer, default=0)
    reach = Column(Integer, default=0)
    profile_views = Column(Integer, default=0)
    website_clicks = Column(Integer, default=0)
    follower_count = Column(Integer, default=0)
    follows = Column(Integer, default=0)      # new followers gained that day
    unfollows = Column(Integer, default=0)     # followers lost that day
    email_contacts = Column(Integer, default=0)
    text_message_clicks = Column(Integer, default=0)
    get_directions_clicks = Column(Integer, default=0)
    phone_call_clicks = Column(Integer, default=0)

    # Engagement aggregates (summed from posts published in this period)
    total_likes = Column(Integer, default=0)
    total_comments = Column(Integer, default=0)
    total_shares = Column(Integer, default=0)
    total_saves = Column(Integer, default=0)

    # Content stats
    posts_published = Column(Integer, default=0)
    stories_published = Column(Integer, default=0)
    reels_published = Column(Integer, default=0)

    # Online followers distribution (JSON: {hour: count})
    online_followers = Column(JSON)

    synced_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('date', 'ig_account_id', name='uq_sm_account_snapshot'),
        Index('idx_sm_snapshot_date', 'date', 'ig_account_id'),
    )


class SocialMediaConnection(Base):
    """Stores Meta/Instagram account connection credentials"""
    __tablename__ = "social_media_connections"

    id = Column(Integer, primary_key=True)
    platform = Column(String(20), nullable=False, default="instagram")
    access_token = Column(Text, nullable=False)
    page_id = Column(String(100))
    ig_account_id = Column(String(100))
    ig_username = Column(String(100))
    ig_followers = Column(Integer, default=0)
    ig_profile_pic = Column(Text, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)
    token_type = Column(String(20), default="long_lived")
    is_active = Column(Boolean, default=True)
    connected_at = Column(DateTime, default=datetime.utcnow)
    last_validated_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index('idx_sm_connection_platform', 'platform'),
    )


# ============================================================
# BLOG CONTENT SYSTEM
# ============================================================

class BlogDraft(Base):
    """Blog article drafts - AI generated content awaiting approval"""
    __tablename__ = "blog_drafts"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(50), unique=True, nullable=False, index=True)  # UUID for API reference

    # Content
    category = Column(String(50), nullable=False, index=True)  # lifestyle, reviews, skin_concerns, ingredients
    topic = Column(Text, nullable=False)  # Original topic/prompt
    keywords = Column(JSON)  # List of SEO keywords
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)  # HTML content
    meta_description = Column(Text)
    excerpt = Column(Text)
    suggested_tags = Column(JSON)  # List of tags
    word_count = Column(Integer)

    # Status
    status = Column(String(50), default='pending_review', index=True)  # pending_review, approved, rejected, published

    # Regeneration tracking
    regeneration_count = Column(Integer, default=0)
    regeneration_hints = Column(Text)  # Last hints used

    # Creator tracking
    created_by = Column(String(255))  # User email
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Link to published article
    published_article_id = Column(Integer, ForeignKey("blog_published.id"))

    __table_args__ = (
        Index('idx_blog_draft_status', 'status', 'created_at'),
    )


class BlogPublished(Base):
    """Published blog articles - synced to Shopify"""
    __tablename__ = "blog_published"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(50), unique=True, nullable=False, index=True)
    draft_uuid = Column(String(50), index=True)  # Link to original draft

    # Shopify integration
    shopify_article_id = Column(String(100), index=True)  # Shopify GID
    shopify_blog_id = Column(String(100))  # Which Shopify blog it's in
    shopify_url = Column(Text)  # Public URL on store
    shopify_handle = Column(String(255))  # URL slug

    # Content snapshot (at time of publishing)
    title = Column(Text, nullable=False)
    category = Column(String(50), nullable=False)
    excerpt = Column(Text)

    # Stats
    views = Column(Integer, default=0)

    # Timestamps
    published_at = Column(DateTime, default=datetime.utcnow, index=True)
    published_by = Column(String(255))  # User email

    __table_args__ = (
        Index('idx_blog_published_date', 'published_at'),
    )


class BlogSuggestion(Base):
    """AI-generated content suggestions from SEO agent"""
    __tablename__ = "blog_suggestions"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(50), unique=True, nullable=False, index=True)

    # Suggestion content
    category = Column(String(50), nullable=False)
    title = Column(Text, nullable=False)
    topic = Column(Text, nullable=False)
    keywords = Column(JSON)  # List of SEO keywords
    reason = Column(Text)  # Why this was suggested
    priority = Column(String(20), default='medium')  # high, medium, low
    word_count = Column(Integer, default=1000)
    estimated_traffic = Column(String(20))  # High, Medium, Low

    # Status
    status = Column(String(50), default='suggested', index=True)  # suggested, generating, ready, dismissed, published
    draft_uuid = Column(String(50))  # Link to generated draft

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_blog_suggestion_status', 'status', 'created_at'),
    )
