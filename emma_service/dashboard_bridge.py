"""
dashboard_bridge.py - Bridge to Mirai Dashboard for shared database access

This module connects the Emma agent to the Mirai Dashboard PostgreSQL database,
allowing access to:
- Products and variants with prices
- Orders and customer history
- Support email queue

Environment variables:
- MIRAI_DATABASE_URL: PostgreSQL connection string
- MIRAI_DASHBOARD_URL: Dashboard API URL (for pushing emails)
- MIRAI_API_TOKEN: JWT token for API authentication (optional)
"""

import os
import requests
from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal

try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

# Configuration
MIRAI_DATABASE_URL = os.getenv("MIRAI_DATABASE_URL", "").strip()
MIRAI_DASHBOARD_URL = os.getenv("MIRAI_DASHBOARD_URL", "https://mirai-managment-dashboard.onrender.com").strip()
MIRAI_API_TOKEN = os.getenv("MIRAI_API_TOKEN", "").strip()

# Known supplier/non-customer email patterns (skip AI draft for these)
SUPPLIER_EMAIL_PATTERNS = [
    # Suppliers
    "@korealy.com",
    "@korealy.co",

    # Generic automated
    "noreply@",
    "no-reply@",
    "donotreply@",
    "do-not-reply@",
    "notifications@",
    "notification@",
    "alert@",
    "alerts@",
    "automated@",
    "system@",
    "mailer-daemon@",
    "postmaster@",

    # Social Media (NOT customers)
    "@pinterest.com",
    "@pin.pinterest.com",
    "@facebookmail.com",
    "@facebook.com",
    "@instagram.com",
    "@tiktok.com",
    "@twitter.com",
    "@x.com",
    "@linkedin.com",
    "@youtube.com",

    # Marketing platforms
    "@klaviyo.com",
    "@mailchimp.com",
    "@sendgrid.net",
    "@mailgun.net",
    "@constantcontact.com",
    "@hubspot.com",
    "@salesforce.com",

    # E-commerce platforms
    "support@shopify.com",
    "@shopify.com",
    "@bigcommerce.com",
    "@wix.com",

    # Payment processors
    "@paypal.com",
    "@stripe.com",
    "@square.com",

    # Google services
    "@google.com",
    "@googlemail.com",
    "@googlecommerce.com",
    "calendar-notification@",

    # Other automated services
    "@zendesk.com",
    "@intercom.com",
    "@freshdesk.com",
    "@helpscout.com",
]
SUPPLIER_EMAIL_PATTERNS = [p for p in SUPPLIER_EMAIL_PATTERNS if p]  # Remove None

# Keywords that indicate supplier/business email (not customer)
SUPPLIER_SUBJECT_KEYWORDS = [
    # Supplier/B2B
    "invoice",
    "payment received",
    "order confirmation from",  # From suppliers, not TO customers
    "shipping notification from",
    "wholesale",
    "b2b",
    "supplier",
    "vendor",
    "inventory update",
    "stock update",
    "price list",
    "catalog",

    # Social media notifications
    "someone saved your pin",
    "your pin was saved",
    "new follower",
    "mentioned you",
    "tagged you",
    "commented on your",
    "liked your",
    "shared your",
    "new message on facebook",
    "new connection",

    # Marketing/Platform
    "your weekly stats",
    "your monthly report",
    "analytics report",
    "performance report",
    "verify your email",
    "confirm your email",
    "password reset",
    "security alert",
    "sign-in attempt",
    "two-factor",
    "2fa code",
]

def is_customer_email(email_address: str, subject: str = "", content: str = "") -> dict:
    """
    Determine if an email is from a real customer vs supplier/automated.

    Returns: {
        'is_customer': bool,
        'sender_type': 'customer' | 'supplier' | 'automated' | 'internal',
        'reason': str
    }
    """
    email_lower = email_address.lower()
    subject_lower = subject.lower()

    # Check against known supplier patterns
    for pattern in SUPPLIER_EMAIL_PATTERNS:
        if pattern.lower() in email_lower:
            return {
                'is_customer': False,
                'sender_type': 'supplier' if 'korealy' in pattern.lower() else 'automated',
                'reason': f'Matched pattern: {pattern}'
            }

    # Check subject for supplier keywords
    for keyword in SUPPLIER_SUBJECT_KEYWORDS:
        if keyword.lower() in subject_lower:
            return {
                'is_customer': False,
                'sender_type': 'supplier',
                'reason': f'Subject contains: {keyword}'
            }

    # Check if it's an internal email (from our own domain)
    # Be specific to avoid matching unintended domains
    if '@miraiskin.com' in email_lower or '@miraiskin.co' in email_lower:
        return {
            'is_customer': False,
            'sender_type': 'internal',
            'reason': 'Internal email'
        }

    # Default: assume it's a customer
    return {
        'is_customer': True,
        'sender_type': 'customer',
        'reason': 'No supplier patterns matched'
    }

# SQLAlchemy setup (only if DATABASE_URL is provided)
_engine = None
_Session = None

def _init_db():
    """Initialize database connection"""
    global _engine, _Session
    if not MIRAI_DATABASE_URL:
        print("[dashboard_bridge] MIRAI_DATABASE_URL not set - database features disabled")
        return False

    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        db_url = MIRAI_DATABASE_URL
        # Convert postgres:// to postgresql://
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)

        _engine = create_engine(db_url, pool_pre_ping=True)
        _Session = sessionmaker(bind=_engine)
        print("[dashboard_bridge] Database connection initialized")
        return True
    except Exception as e:
        print(f"[dashboard_bridge] Database init failed: {e}")
        return False


def get_db_session():
    """Get a database session"""
    global _Session
    if _Session is None:
        if not _init_db():
            return None
    return _Session()


# ==================== PRODUCT QUERIES ====================

def get_products(limit: int = 100) -> List[Dict[str, Any]]:
    """Get all active products with variants"""
    session = get_db_session()
    if not session:
        return []

    try:
        from sqlalchemy import text

        query = text("""
            SELECT
                p.id, p.title as product_title, p.status,
                v.id as variant_id, v.variant_id as shopify_variant_id,
                v.sku, v.title as variant_title,
                v.price, v.compare_at_price, v.cogs
            FROM products p
            JOIN variants v ON v.product_id = p.id
            WHERE p.status = 'active'
            ORDER BY p.title, v.title
            LIMIT :limit
        """)

        result = session.execute(query, {"limit": limit})
        products = []

        for row in result:
            products.append({
                "product_id": row.id,
                "product_title": row.product_title,
                "variant_id": row.variant_id,
                "shopify_variant_id": row.shopify_variant_id,
                "sku": row.sku,
                "variant_title": row.variant_title,
                "price": float(row.price) if row.price else None,
                "compare_at_price": float(row.compare_at_price) if row.compare_at_price else None,
                "cogs": float(row.cogs) if row.cogs else None,
                "discount_pct": round((1 - float(row.price) / float(row.compare_at_price)) * 100, 0) if row.compare_at_price and row.price else None
            })

        return products
    except Exception as e:
        print(f"[dashboard_bridge] get_products error: {e}")
        return []
    finally:
        session.close()


def search_products(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search products by title or SKU"""
    session = get_db_session()
    if not session:
        return []

    try:
        from sqlalchemy import text

        sql = text("""
            SELECT
                p.id, p.title as product_title,
                v.id as variant_id, v.sku, v.title as variant_title,
                v.price, v.compare_at_price
            FROM products p
            JOIN variants v ON v.product_id = p.id
            WHERE p.status = 'active'
              AND (LOWER(p.title) LIKE LOWER(:query)
                   OR LOWER(v.sku) LIKE LOWER(:query)
                   OR LOWER(v.title) LIKE LOWER(:query))
            ORDER BY p.title
            LIMIT :limit
        """)

        result = session.execute(sql, {"query": f"%{query}%", "limit": limit})
        products = []

        for row in result:
            products.append({
                "product_title": row.product_title,
                "variant_title": row.variant_title,
                "sku": row.sku,
                "price": float(row.price) if row.price else None,
                "compare_at_price": float(row.compare_at_price) if row.compare_at_price else None
            })

        return products
    except Exception as e:
        print(f"[dashboard_bridge] search_products error: {e}")
        return []
    finally:
        session.close()


def get_product_by_sku(sku: str) -> Optional[Dict[str, Any]]:
    """Get a single product by SKU"""
    session = get_db_session()
    if not session:
        return None

    try:
        from sqlalchemy import text

        sql = text("""
            SELECT
                p.title as product_title,
                v.sku, v.title as variant_title,
                v.price, v.compare_at_price, v.cogs
            FROM variants v
            JOIN products p ON v.product_id = p.id
            WHERE v.sku = :sku
            LIMIT 1
        """)

        result = session.execute(sql, {"sku": sku}).fetchone()

        if result:
            return {
                "product_title": result.product_title,
                "variant_title": result.variant_title,
                "sku": result.sku,
                "price": float(result.price) if result.price else None,
                "compare_at_price": float(result.compare_at_price) if result.compare_at_price else None,
                "cogs": float(result.cogs) if result.cogs else None
            }
        return None
    except Exception as e:
        print(f"[dashboard_bridge] get_product_by_sku error: {e}")
        return None
    finally:
        session.close()


# ==================== CUSTOMER/ORDER QUERIES ====================

def get_customer_orders(email: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Get recent orders for a customer by email"""
    session = get_db_session()
    if not session:
        return []

    try:
        from sqlalchemy import text

        sql = text("""
            SELECT
                o.order_name, o.created_at, o.net, o.gross,
                o.country, o.channel, o.is_returning
            FROM orders o
            JOIN customers c ON o.customer_id = c.id
            WHERE LOWER(c.email) = LOWER(:email)
            ORDER BY o.created_at DESC
            LIMIT :limit
        """)

        result = session.execute(sql, {"email": email, "limit": limit})
        orders = []

        for row in result:
            orders.append({
                "order_name": row.order_name,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "net": float(row.net) if row.net else 0,
                "gross": float(row.gross) if row.gross else 0,
                "country": row.country,
                "channel": row.channel,
                "is_returning": row.is_returning
            })

        return orders
    except Exception as e:
        print(f"[dashboard_bridge] get_customer_orders error: {e}")
        return []
    finally:
        session.close()


def get_order_with_tracking(order_name: str) -> Optional[Dict[str, Any]]:
    """
    Get order details including tracking info from Shopify.
    This makes a direct Shopify API call to get fulfillment/tracking data.
    """
    import os

    shopify_token = os.getenv("SHOPIFY_ACCESS_TOKEN") or os.getenv("SHOPIFY_ADMIN_TOKEN")
    shopify_store = os.getenv("SHOPIFY_STORE_URL") or os.getenv("SHOPIFY_STORE")

    if not shopify_token or not shopify_store:
        # Fall back to database lookup
        order = get_order_by_name(order_name)
        if order:
            order["tracking_info"] = None
            order["tracking_message"] = "Tracking lookup requires Shopify API configuration"
        return order

    # Clean up store URL
    store_domain = shopify_store.replace("https://", "").replace("http://", "").split("/")[0]
    if not store_domain.endswith(".myshopify.com"):
        store_domain = f"{store_domain}.myshopify.com"

    # Normalize order name
    if not order_name.startswith("#"):
        order_name = f"#{order_name}"
    order_number = order_name.replace("#", "")

    try:
        # Search for order by name
        url = f"https://{store_domain}/admin/api/2024-01/orders.json"
        params = {"name": order_name, "status": "any"}
        headers = {"X-Shopify-Access-Token": shopify_token}

        response = requests.get(url, params=params, headers=headers, timeout=15)

        if not response.ok:
            print(f"[dashboard_bridge] Shopify order lookup failed: {response.status_code}")
            return get_order_by_name(order_name)

        data = response.json()
        orders = data.get("orders", [])

        if not orders:
            return get_order_by_name(order_name)

        order = orders[0]

        # Extract tracking info from fulfillments
        fulfillments = order.get("fulfillments", [])
        tracking_info = None
        tracking_numbers = []
        tracking_urls = []

        for f in fulfillments:
            if f.get("tracking_number"):
                tracking_numbers.append(f.get("tracking_number"))
            if f.get("tracking_url"):
                tracking_urls.append(f.get("tracking_url"))
            if f.get("tracking_numbers"):
                tracking_numbers.extend(f.get("tracking_numbers", []))
            if f.get("tracking_urls"):
                tracking_urls.extend(f.get("tracking_urls", []))

        if tracking_numbers:
            tracking_info = {
                "tracking_numbers": list(set(tracking_numbers)),
                "tracking_urls": list(set(tracking_urls)),
                "carrier": fulfillments[0].get("tracking_company") if fulfillments else None,
                "fulfillment_status": order.get("fulfillment_status"),
                "shipped_at": fulfillments[0].get("created_at") if fulfillments else None
            }

        return {
            "order_name": order.get("name"),
            "order_id": order.get("id"),
            "created_at": order.get("created_at"),
            "financial_status": order.get("financial_status"),
            "fulfillment_status": order.get("fulfillment_status"),
            "total_price": order.get("total_price"),
            "currency": order.get("currency"),
            "customer_email": order.get("email"),
            "customer_name": f"{order.get('customer', {}).get('first_name', '')} {order.get('customer', {}).get('last_name', '')}".strip(),
            "shipping_address": {
                "city": order.get("shipping_address", {}).get("city"),
                "country": order.get("shipping_address", {}).get("country"),
            } if order.get("shipping_address") else None,
            "tracking_info": tracking_info,
            "line_items": [
                {"title": item.get("title"), "quantity": item.get("quantity")}
                for item in order.get("line_items", [])[:5]  # First 5 items
            ]
        }

    except Exception as e:
        print(f"[dashboard_bridge] get_order_with_tracking error: {e}")
        return get_order_by_name(order_name)


def get_order_by_name(order_name: str) -> Optional[Dict[str, Any]]:
    """Get order details by order name (e.g., #1234)"""
    session = get_db_session()
    if not session:
        return None

    try:
        from sqlalchemy import text

        # Normalize order name
        if not order_name.startswith("#"):
            order_name = f"#{order_name}"

        sql = text("""
            SELECT
                o.order_name, o.shopify_gid, o.created_at, o.processed_at,
                o.gross, o.net, o.cogs, o.country,
                c.email as customer_email, c.first_name, c.last_name
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.id
            WHERE o.order_name = :order_name
            LIMIT 1
        """)

        result = session.execute(sql, {"order_name": order_name}).fetchone()

        if result:
            return {
                "order_name": result.order_name,
                "shopify_gid": result.shopify_gid,
                "created_at": result.created_at.isoformat() if result.created_at else None,
                "processed_at": result.processed_at.isoformat() if result.processed_at else None,
                "gross": float(result.gross) if result.gross else 0,
                "net": float(result.net) if result.net else 0,
                "cogs": float(result.cogs) if result.cogs else 0,
                "country": result.country,
                "customer_email": result.customer_email,
                "customer_name": f"{result.first_name or ''} {result.last_name or ''}".strip()
            }
        return None
    except Exception as e:
        print(f"[dashboard_bridge] get_order_by_name error: {e}")
        return None
    finally:
        session.close()


# ==================== DASHBOARD API ====================

def _api_headers() -> Dict[str, str]:
    """Get headers for API requests"""
    headers = {"Content-Type": "application/json"}
    if MIRAI_API_TOKEN:
        headers["Authorization"] = f"Bearer {MIRAI_API_TOKEN}"
    return headers


def push_email_to_dashboard(
    thread_id: str,
    customer_email: str,
    subject: str,
    content: str,
    customer_name: Optional[str] = None,
    content_html: Optional[str] = None,
    message_id: Optional[str] = None,
    inbox_type: Optional[str] = "support",
    sender_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Push an incoming email to the Mirai Dashboard support queue.

    Returns: {"success": True, "id": email_id} or {"success": False, "error": "..."}
    """
    if not MIRAI_DASHBOARD_URL:
        return {"success": False, "error": "MIRAI_DASHBOARD_URL not configured"}

    try:
        url = f"{MIRAI_DASHBOARD_URL}/webhook/support-email"
        payload = {
            "thread_id": thread_id,
            "message_id": message_id,
            "customer_email": customer_email,
            "customer_name": customer_name,
            "subject": subject,
            "content": content,
            "content_html": content_html,
            "inbox_type": inbox_type,
            "sender_type": sender_type
        }

        response = requests.post(url, json=payload, headers=_api_headers(), timeout=30)

        if response.ok:
            data = response.json()
            print(f"[dashboard_bridge] Email pushed to dashboard: {data}")
            return {"success": True, "id": data.get("id")}
        else:
            error = f"HTTP {response.status_code}: {response.text[:200]}"
            print(f"[dashboard_bridge] Push failed: {error}")
            return {"success": False, "error": error}

    except Exception as e:
        print(f"[dashboard_bridge] push_email error: {e}")
        return {"success": False, "error": str(e)}


def update_email_draft(
    email_id: int,
    ai_draft: str,
    classification: Optional[str] = None,
    intent: Optional[str] = None,
    priority: Optional[str] = None,
    sender_type: Optional[str] = None,
    status: Optional[str] = None,
    draft_error: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update an email with AI-generated draft and classification.

    classification: 'support', 'sales', 'support_sales'
    intent: 'tracking', 'return', 'product_question', 'complaint', etc.
    priority: 'low', 'medium', 'high'
    sender_type: 'customer', 'supplier', 'automated', 'internal'
    status: 'pending', 'draft_ready', 'draft_failed', 'not_customer', etc.
    draft_error: Error message if draft generation failed
    """
    if not MIRAI_DASHBOARD_URL:
        return {"success": False, "error": "MIRAI_DASHBOARD_URL not configured"}

    try:
        url = f"{MIRAI_DASHBOARD_URL}/webhook/support-email/{email_id}"
        payload = {"ai_draft": ai_draft or ""}

        if classification:
            payload["classification"] = classification
        if intent:
            payload["intent"] = intent
        if priority:
            payload["priority"] = priority
        if sender_type:
            payload["sender_type"] = sender_type
        if status:
            payload["status"] = status
        if draft_error:
            payload["draft_error"] = draft_error

        response = requests.patch(url, json=payload, headers=_api_headers(), timeout=30)

        if response.ok:
            return {"success": True}
        else:
            return {"success": False, "error": f"HTTP {response.status_code}"}

    except Exception as e:
        print(f"[dashboard_bridge] update_email_draft error: {e}")
        return {"success": False, "error": str(e)}


# ==================== AI CLASSIFICATION ====================

def classify_email(content: str, subject: str = "") -> Dict[str, Any]:
    """
    Classify an email using AI.

    Returns: {
        'classification': 'support' | 'sales' | 'support_sales',
        'intent': str,
        'priority': 'low' | 'medium' | 'high',
        'sales_opportunity': bool,
        'confidence': float
    }
    """
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    prompt = f"""Analyze this customer email and classify it.

Subject: {subject}
Content: {content[:2000]}

Respond in JSON format:
{{
    "classification": "support" | "sales" | "support_sales",
    "intent": "tracking" | "return" | "refund" | "product_question" | "complaint" | "shipping" | "discount" | "general",
    "priority": "low" | "medium" | "high",
    "sales_opportunity": true | false,
    "confidence": 0.0-1.0
}}

Classification guide:
- "support": Questions about orders, tracking, returns, complaints
- "sales": Product questions, pricing, recommendations
- "support_sales": Support issue with upsell opportunity

Priority guide:
- "high": Complaints, urgent issues, unhappy customers
- "medium": Standard support questions
- "low": General inquiries, simple questions"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=200
        )

        import json
        result = json.loads(response.choices[0].message.content)

        # Ensure result is a dict with required fields
        if not isinstance(result, dict):
            print(f"[dashboard_bridge] classify_email returned non-dict: {type(result)}")
            result = {"classification": "support"}

        # Ensure required fields exist
        if "classification" not in result:
            result["classification"] = "support"
        if "intent" not in result:
            result["intent"] = "general"
        if "priority" not in result:
            result["priority"] = "medium"

        return result

    except Exception as e:
        print(f"[dashboard_bridge] classify_email error: {e}")
        return {
            "classification": "support",
            "intent": "general",
            "priority": "medium",
            "sales_opportunity": False,
            "confidence": 0.5
        }


# ==================== FULL EMAIL PROCESSING ====================

def process_incoming_email(
    thread_id: str,
    customer_email: str,
    subject: str,
    content: str,
    customer_name: Optional[str] = None,
    content_html: Optional[str] = None,
    message_id: Optional[str] = None,
    inbox_type: Optional[str] = "support",
    generate_draft: bool = True
) -> Dict[str, Any]:
    """
    Full pipeline for processing an incoming email:
    1. Check if email is from a real customer
    2. Push to dashboard
    3. Classify the email
    4. Generate AI draft response (only for customers)
    5. Update dashboard with draft and classification

    Returns: {"success": True, "email_id": id, "classification": {...}, "draft": "..."}
    """
    # Step 0: Check if this is a customer email (not supplier/automated)
    sender_check = is_customer_email(customer_email, subject, content)
    sender_type = sender_check.get('sender_type', 'customer')
    is_customer = sender_check.get('is_customer', True)

    print(f"[dashboard_bridge] Email from {customer_email}: sender_type={sender_type}, is_customer={is_customer}")
    if not is_customer:
        print(f"[dashboard_bridge] Skipping AI draft for non-customer: {sender_check.get('reason')}")

    # Step 1: Push to dashboard (always push, even for suppliers)
    # Include sender_type so it's set on creation, not just on update
    push_result = push_email_to_dashboard(
        thread_id=thread_id,
        customer_email=customer_email,
        subject=subject,
        content=content,
        customer_name=customer_name,
        content_html=content_html,
        message_id=message_id,
        inbox_type=inbox_type,
        sender_type=sender_type
    )

    if not push_result.get("success"):
        return {"success": False, "error": push_result.get("error")}

    email_id = push_result.get("id")

    # Step 2: Classify (with sender type info)
    classification = classify_email(content, subject)
    classification['sender_type'] = sender_type
    classification['is_customer'] = is_customer

    # Step 3: Generate draft (using Emma) - ONLY for real customers
    ai_draft = None
    draft_status = "pending"
    draft_error = None

    if not generate_draft:
        draft_status = "draft_skipped"
        print(f"[dashboard_bridge] Skipping draft generation (generate_draft=False)")
    elif not is_customer:
        draft_status = "not_customer"
        print(f"[dashboard_bridge] Skipping draft - not a customer email (sender_type={sender_type})")
    else:
        # Check if OpenAI API key is available
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            draft_status = "draft_failed"
            draft_error = "OPENAI_API_KEY not configured"
            print(f"[dashboard_bridge] Cannot generate draft - OPENAI_API_KEY not set")
        else:
            try:
                print(f"[dashboard_bridge] Generating Emma draft for email_id={email_id}...")
                print(f"[dashboard_bridge] Customer: {customer_email}, Subject: {subject[:50]}...")
                from emma_agent import respond_as_emma

                # Get customer context
                customer_orders = get_customer_orders(customer_email, limit=3)

                # Build history context for Emma
                history = []
                if customer_orders:
                    order_summary = f"Previous orders: {len(customer_orders)}. "
                    if customer_orders[0]:
                        order_summary += f"Last order: {customer_orders[0].get('order_name')} on {customer_orders[0].get('created_at', '')[:10]}"
                    history.append({"role": "system", "content": order_summary})
                    print(f"[dashboard_bridge] Customer has {len(customer_orders)} previous orders")

                # Extract first name from customer_name
                first_name = ""
                if customer_name:
                    first_name = customer_name.split()[0] if customer_name else ""

                ai_draft = respond_as_emma(
                    first_name=first_name,
                    cart_items=[],  # No cart items from email
                    customer_msg=content,
                    history=history,
                    first_contact=False,
                    geo=None,
                    style_mode="soft",
                    customer_email=customer_email
                )
                if ai_draft:
                    draft_status = "draft_ready"
                    print(f"[dashboard_bridge] Emma draft generated: {len(ai_draft)} chars")
                else:
                    draft_status = "draft_empty"
                    print(f"[dashboard_bridge] Emma returned empty draft")
            except Exception as e:
                import traceback
                draft_status = "draft_failed"
                draft_error = str(e)
                print(f"[dashboard_bridge] Emma draft generation failed: {e}")
                traceback.print_exc()
                ai_draft = None

    # Step 4: Update dashboard with classification and draft
    if email_id:
        print(f"[dashboard_bridge] Updating email_id={email_id} with status={draft_status}, classification={classification.get('classification')}, sender_type={sender_type}, draft={len(ai_draft) if ai_draft else 0} chars")
        update_result = update_email_draft(
            email_id=email_id,
            ai_draft=ai_draft or "",
            classification=classification.get("classification"),
            intent=classification.get("intent"),
            priority=classification.get("priority"),
            sender_type=sender_type,
            status=draft_status,
            draft_error=draft_error
        )
        print(f"[dashboard_bridge] Update result: {update_result}")

    return {
        "success": True,
        "email_id": email_id,
        "classification": classification,
        "draft": ai_draft
    }


# ==================== TEST ====================

if __name__ == "__main__":
    print("Testing dashboard bridge...")

    # Test database connection
    products = get_products(limit=5)
    print(f"Products found: {len(products)}")
    for p in products[:3]:
        print(f"  - {p['product_title']}: ${p['price']}")

    # Test email classification
    test_content = "Hi, I ordered 3 days ago and haven't received tracking info yet. Can you help?"
    classification = classify_email(test_content, "Where is my order?")
    print(f"Classification: {classification}")
