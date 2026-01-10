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
    message_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Push an incoming email to the Mirai Dashboard support queue.

    Returns: {"success": True, "id": email_id} or {"success": False, "error": "..."}
    """
    if not MIRAI_DASHBOARD_URL:
        return {"success": False, "error": "MIRAI_DASHBOARD_URL not configured"}

    try:
        url = f"{MIRAI_DASHBOARD_URL}/support/emails"
        payload = {
            "thread_id": thread_id,
            "message_id": message_id,
            "customer_email": customer_email,
            "customer_name": customer_name,
            "subject": subject,
            "content": content,
            "content_html": content_html
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
    priority: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update an email with AI-generated draft and classification.

    classification: 'support', 'sales', 'support_sales'
    intent: 'tracking', 'return', 'product_question', 'complaint', etc.
    priority: 'low', 'medium', 'high'
    """
    if not MIRAI_DASHBOARD_URL:
        return {"success": False, "error": "MIRAI_DASHBOARD_URL not configured"}

    try:
        url = f"{MIRAI_DASHBOARD_URL}/support/emails/{email_id}"
        payload = {"ai_draft": ai_draft}

        if classification:
            payload["classification"] = classification
        if intent:
            payload["intent"] = intent
        if priority:
            payload["priority"] = priority

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
    generate_draft: bool = True
) -> Dict[str, Any]:
    """
    Full pipeline for processing an incoming email:
    1. Push to dashboard
    2. Classify the email
    3. Generate AI draft response
    4. Update dashboard with draft and classification

    Returns: {"success": True, "email_id": id, "classification": {...}, "draft": "..."}
    """
    # Step 1: Push to dashboard
    push_result = push_email_to_dashboard(
        thread_id=thread_id,
        customer_email=customer_email,
        subject=subject,
        content=content,
        customer_name=customer_name,
        content_html=content_html,
        message_id=message_id
    )

    if not push_result.get("success"):
        return {"success": False, "error": push_result.get("error")}

    email_id = push_result.get("id")

    # Step 2: Classify
    classification = classify_email(content, subject)

    # Step 3: Generate draft (using Emma)
    ai_draft = None
    if generate_draft:
        try:
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
        except Exception as e:
            print(f"[dashboard_bridge] Emma draft generation failed: {e}")
            ai_draft = None

    # Step 4: Update dashboard
    if email_id and (ai_draft or classification):
        update_email_draft(
            email_id=email_id,
            ai_draft=ai_draft or "",
            classification=classification.get("classification"),
            intent=classification.get("intent"),
            priority=classification.get("priority")
        )

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
