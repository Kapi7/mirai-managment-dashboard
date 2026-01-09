"""
Database Service Layer
Provides data access with fallback to API-based methods if database is not available
"""
import os
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
from decimal import Decimal

from sqlalchemy import select, func, and_, desc, case
from sqlalchemy.orm import selectinload

from .connection import get_db, is_db_configured
from .models import (
    Store, Product, Variant, Order, OrderLineItem,
    AdSpend, DailyKPI, CompetitorScan, Customer
)


def _decimal_to_float(obj):
    """Convert Decimal to float for JSON serialization"""
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


class DatabaseService:
    """
    Service layer for database operations with fallback to API methods
    """

    @staticmethod
    def is_available() -> bool:
        """Check if database is configured and available"""
        return is_db_configured()

    # ==================== PRODUCTS & VARIANTS ====================

    @staticmethod
    async def get_items(store_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all product variants with pricing data

        Returns list of items with:
        - variant_id, item, weight, cogs, retail_base, compare_at_base
        """
        if not is_db_configured():
            return None  # Fallback to API

        try:
            async with get_db() as db:
                query = (
                    select(Variant, Product)
                    .join(Product, Variant.product_id == Product.id)
                    .where(Product.status == 'active')
                )

                if store_key:
                    query = query.join(Store).where(Store.key == store_key)

                result = await db.execute(query)
                rows = result.all()

                items = []
                for variant, product in rows:
                    items.append({
                        "variant_id": variant.variant_id,
                        "item": f"{product.title} — {variant.title}".strip(" — "),
                        "weight": variant.weight_g or 0,
                        "cogs": _decimal_to_float(variant.cogs) or 0,
                        "retail_base": _decimal_to_float(variant.price) or 0,
                        "compare_at_base": _decimal_to_float(variant.compare_at_price) or 0,
                        "sku": variant.sku or ""
                    })

                return items

        except Exception as e:
            print(f"❌ Database error in get_items: {e}")
            return None

    # ==================== ORDERS ====================

    @staticmethod
    async def get_orders(
        start_date: date,
        end_date: date,
        store_key: Optional[str] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get orders for date range

        Returns list with order details and analytics
        """
        if not is_db_configured():
            return None

        try:
            async with get_db() as db:
                query = (
                    select(Order)
                    .options(selectinload(Order.customer))
                    .where(
                        and_(
                            Order.created_at >= datetime.combine(start_date, datetime.min.time()),
                            Order.created_at < datetime.combine(end_date + timedelta(days=1), datetime.min.time())
                        )
                    )
                    .order_by(desc(Order.created_at))
                )

                if store_key:
                    query = query.join(Store).where(Store.key == store_key)

                result = await db.execute(query)
                orders = result.scalars().all()

                orders_data = []
                for order in orders:
                    customer_name = "Guest"
                    customer_email = ""
                    if order.customer:
                        customer_name = f"{order.customer.first_name or ''} {order.customer.last_name or ''}".strip() or "Guest"
                        customer_email = order.customer.email or ""

                    net = _decimal_to_float(order.net) or 0
                    cogs = _decimal_to_float(order.cogs) or 0
                    shipping = _decimal_to_float(order.shipping_charged) or 0
                    profit = net + shipping - cogs
                    margin_pct = (profit / (net + shipping)) * 100 if (net + shipping) > 0 else 0

                    orders_data.append({
                        "order_id": order.shopify_gid.split("/")[-1] if order.shopify_gid else "",
                        "order_name": order.order_name,
                        "created_at": order.created_at.isoformat() if order.created_at else "",
                        "date": order.created_at.strftime("%Y-%m-%d") if order.created_at else "",
                        "time": order.created_at.strftime("%H:%M") if order.created_at else "",
                        "hour": order.created_at.hour if order.created_at else 0,
                        "customer_name": customer_name,
                        "customer_email": customer_email,
                        "is_returning": order.is_returning or False,
                        "channel": order.channel or "organic",
                        "country": order.country or "Unknown",
                        "city": "",
                        "is_cancelled": order.cancelled_at is not None,
                        "gross": _decimal_to_float(order.gross) or 0,
                        "discounts": _decimal_to_float(order.discounts) or 0,
                        "refunds": _decimal_to_float(order.refunds) or 0,
                        "net": net,
                        "shipping": shipping,
                        "cogs": cogs,
                        "profit": round(profit, 2),
                        "margin_pct": round(margin_pct, 1),
                        "items_count": 0,  # Would need line items count
                        "items": [],
                        "store": ""
                    })

                return orders_data

        except Exception as e:
            print(f"❌ Database error in get_orders: {e}")
            return None

    # ==================== DAILY KPIS ====================

    @staticmethod
    async def get_daily_kpis(
        start_date: date,
        end_date: date,
        store_key: Optional[str] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get daily KPIs - aggregates from orders table directly

        Returns list with daily metrics
        """
        if not is_db_configured():
            return None

        try:
            async with get_db() as db:
                # Aggregate directly from orders table
                query = (
                    select(
                        func.date(Order.created_at).label('order_date'),
                        func.count(Order.id).label('orders'),
                        func.sum(case((Order.is_returning == True, 1), else_=0)).label('returning_orders'),
                        func.sum(Order.gross).label('gross'),
                        func.sum(Order.discounts).label('discounts'),
                        func.sum(Order.refunds).label('refunds'),
                        func.sum(Order.net).label('net'),
                        func.sum(Order.cogs).label('cogs'),
                        func.sum(Order.shipping_charged).label('shipping_charged'),
                    )
                    .where(
                        and_(
                            Order.created_at >= datetime.combine(start_date, datetime.min.time()),
                            Order.created_at < datetime.combine(end_date + timedelta(days=1), datetime.min.time()),
                            Order.cancelled_at.is_(None)
                        )
                    )
                    .group_by(func.date(Order.created_at))
                    .order_by(desc(func.date(Order.created_at)))
                )

                result = await db.execute(query)
                rows = result.all()

                kpis = []
                for row in rows:
                    orders_count = row.orders or 0
                    gross = _decimal_to_float(row.gross) or 0
                    discounts = _decimal_to_float(row.discounts) or 0
                    refunds = _decimal_to_float(row.refunds) or 0
                    net = _decimal_to_float(row.net) or 0
                    cogs = _decimal_to_float(row.cogs) or 0
                    shipping_charged = _decimal_to_float(row.shipping_charged) or 0

                    # Calculate metrics
                    aov = net / orders_count if orders_count > 0 else 0
                    net_margin = net - cogs
                    margin_pct = (net_margin / net * 100) if net > 0 else 0

                    kpis.append({
                        "date": row.order_date.isoformat() if hasattr(row.order_date, 'isoformat') else str(row.order_date),
                        "orders": orders_count,
                        "gross": gross,
                        "discounts": discounts,
                        "refunds": refunds,
                        "net": net,
                        "cogs": cogs,
                        "shipping_charged": shipping_charged,
                        "shipping_cost": 0,  # Would need shipping rates calculation
                        "psp_usd": round(net * 0.029 + 0.30 * orders_count, 2),  # Estimate PSP fees
                        "google_spend": 0,  # Would need ad_spend table
                        "meta_spend": 0,
                        "total_spend": 0,
                        "operational_profit": round(net_margin, 2),
                        "net_margin": round(net_margin, 2),
                        "margin_pct": round(margin_pct, 1),
                        "aov": round(aov, 2),
                        "returning_customers": row.returning_orders or 0,
                        "general_cpa": None,
                        "google_pur": 0,
                        "meta_pur": 0
                    })

                return kpis

        except Exception as e:
            print(f"❌ Database error in get_daily_kpis: {e}")
            import traceback
            traceback.print_exc()
            return None

    # ==================== BESTSELLERS ====================

    @staticmethod
    async def get_bestsellers(
        days: int = 30,
        store_key: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get bestsellers from database

        Returns dict with bestsellers list and analytics
        """
        if not is_db_configured():
            return None

        try:
            async with get_db() as db:
                end_date = datetime.utcnow()
                start_date = end_date - timedelta(days=days)

                # Get order line items aggregated by SKU
                # Join to variants by SKU (since variant_id FK may be NULL from orders synced before products)
                query = (
                    select(
                        OrderLineItem.sku,
                        Variant.variant_id,
                        Product.title.label('product_title'),
                        Variant.title.label('variant_title'),
                        func.sum(OrderLineItem.quantity).label('total_qty'),
                        func.sum(OrderLineItem.gross).label('total_sales'),
                        func.sum(OrderLineItem.unit_cogs * OrderLineItem.quantity).label('total_cogs'),
                        func.count(func.distinct(OrderLineItem.order_id)).label('order_count')
                    )
                    .join(Order, OrderLineItem.order_id == Order.id)
                    .outerjoin(Variant, Variant.sku == OrderLineItem.sku)  # Join by SKU instead of variant_id
                    .outerjoin(Product, Variant.product_id == Product.id)
                    .where(
                        and_(
                            Order.created_at >= start_date,
                            Order.cancelled_at.is_(None)
                        )
                    )
                    .group_by(
                        OrderLineItem.sku,
                        Variant.variant_id,
                        Product.title,
                        Variant.title
                    )
                    .order_by(desc('total_qty'))
                    .limit(100)
                )

                result = await db.execute(query)
                rows = result.all()

                bestsellers = []
                total_qty = 0
                total_revenue = 0
                total_profit = 0

                for row in rows:
                    qty = int(row.total_qty or 0)
                    sales = _decimal_to_float(row.total_sales) or 0
                    cogs = _decimal_to_float(row.total_cogs) or 0
                    profit = sales - cogs
                    margin = (profit / sales * 100) if sales > 0 else 0

                    total_qty += qty
                    total_revenue += sales
                    total_profit += profit

                    bestsellers.append({
                        "variant_id": row.variant_id or "",
                        "product_title": row.product_title or "Unknown",
                        "variant_title": row.variant_title or "",
                        "sku": row.sku or "",
                        "total_qty": qty,
                        "total_sales": round(sales, 2),
                        "total_revenue": round(sales, 2),
                        "total_cogs": round(cogs, 2),
                        "total_profit": round(profit, 2),
                        "order_count": row.order_count or 0,
                        "margin_pct": round(margin, 1)
                    })

                # Get total orders count
                order_count_query = (
                    select(func.count(Order.id))
                    .where(
                        and_(
                            Order.created_at >= start_date,
                            Order.cancelled_at.is_(None)
                        )
                    )
                )
                total_orders = (await db.execute(order_count_query)).scalar() or 0

                return {
                    "bestsellers": bestsellers,
                    "top_by_quantity": bestsellers[:10],
                    "top_by_revenue": sorted(bestsellers, key=lambda x: x["total_revenue"], reverse=True)[:10],
                    "top_by_profit": sorted(bestsellers, key=lambda x: x["total_profit"], reverse=True)[:10],
                    "analytics": {
                        "period_days": days,
                        "start_date": start_date.date().isoformat(),
                        "end_date": end_date.date().isoformat(),
                        "total_products_sold": len(bestsellers),
                        "total_units_sold": total_qty,
                        "total_revenue": round(total_revenue, 2),
                        "total_profit": round(total_profit, 2),
                        "avg_profit_per_unit": round(total_profit / total_qty, 2) if total_qty > 0 else 0,
                        "total_orders": total_orders
                    }
                }

        except Exception as e:
            print(f"❌ Database error in get_bestsellers: {e}")
            import traceback
            traceback.print_exc()
            return None

    # ==================== COMPETITOR DATA ====================

    @staticmethod
    async def get_competitor_data(variant_id: str) -> Optional[Dict[str, Any]]:
        """Get latest competitor scan data for a variant"""
        if not is_db_configured():
            return None

        try:
            async with get_db() as db:
                query = (
                    select(CompetitorScan)
                    .join(Variant)
                    .where(Variant.variant_id == variant_id)
                    .order_by(desc(CompetitorScan.scanned_at))
                    .limit(1)
                )

                result = await db.execute(query)
                scan = result.scalar_one_or_none()

                if not scan:
                    return None

                return {
                    "comp_low": _decimal_to_float(scan.comp_low),
                    "comp_avg": _decimal_to_float(scan.comp_avg),
                    "comp_high": _decimal_to_float(scan.comp_high),
                    "raw_count": scan.raw_count,
                    "trusted_count": scan.trusted_count,
                    "filtered_count": scan.filtered_count,
                    "scanned_at": scan.scanned_at.isoformat() if scan.scanned_at else None,
                    "top_sellers": scan.top_sellers
                }

        except Exception as e:
            print(f"❌ Database error in get_competitor_data: {e}")
            return None


    # ==================== UPDATE VARIANT ====================

    @staticmethod
    async def update_variant_price(
        variant_id: str,
        price: float = None,
        compare_at_price: float = None,
        cogs: float = None
    ) -> bool:
        """
        Update variant pricing in database after Shopify update
        Called automatically when prices are changed via dashboard
        """
        if not is_db_configured():
            return False

        try:
            async with get_db() as db:
                # Find variant by variant_id
                result = await db.execute(
                    select(Variant).where(Variant.variant_id == str(variant_id))
                )
                variant = result.scalar_one_or_none()

                if not variant:
                    print(f"⚠️ Variant {variant_id} not found in database")
                    return False

                # Update fields that were provided
                if price is not None:
                    variant.price = price
                if compare_at_price is not None:
                    variant.compare_at_price = compare_at_price
                if cogs is not None:
                    variant.cogs = cogs

                variant.updated_at = datetime.utcnow()
                await db.commit()

                print(f"✅ Updated variant {variant_id} in database: price={price}, compare_at={compare_at_price}, cogs={cogs}")
                return True

        except Exception as e:
            print(f"❌ Database error updating variant {variant_id}: {e}")
            return False

    # ==================== DATABASE STATS ====================

    @staticmethod
    async def get_stats() -> Dict[str, Any]:
        """Get database statistics"""
        if not is_db_configured():
            return {"configured": False, "message": "Database not configured"}

        try:
            async with get_db() as db:
                # Count records in each table
                orders_count = (await db.execute(select(func.count(Order.id)))).scalar() or 0
                variants_count = (await db.execute(select(func.count(Variant.id)))).scalar() or 0
                products_count = (await db.execute(select(func.count(Product.id)))).scalar() or 0
                customers_count = (await db.execute(select(func.count(Customer.id)))).scalar() or 0

                # Get date range of orders
                oldest_order = (await db.execute(
                    select(Order.created_at).order_by(Order.created_at.asc()).limit(1)
                )).scalar()
                newest_order = (await db.execute(
                    select(Order.created_at).order_by(Order.created_at.desc()).limit(1)
                )).scalar()

                return {
                    "configured": True,
                    "connected": True,
                    "stats": {
                        "orders": orders_count,
                        "variants": variants_count,
                        "products": products_count,
                        "customers": customers_count,
                    },
                    "order_date_range": {
                        "oldest": oldest_order.isoformat() if oldest_order else None,
                        "newest": newest_order.isoformat() if newest_order else None,
                    }
                }

        except Exception as e:
            print(f"❌ Database error in get_stats: {e}")
            return {
                "configured": True,
                "connected": False,
                "error": str(e)
            }


# Global service instance
db_service = DatabaseService()
