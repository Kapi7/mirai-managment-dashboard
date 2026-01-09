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
    AdSpend, DailyKPI, CompetitorScan, Customer, DailyPspFee
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
    async def get_items(store_key: Optional[str] = "skin") -> List[Dict[str, Any]]:
        """
        Get all product variants with pricing data
        Default to 'skin' store (Mirai Skin) for pricing items

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
                    .join(Store, Variant.store_id == Store.id)
                    .where(Product.status == 'active')
                )

                # Filter by store (default to 'skin' for Mirai Skin)
                if store_key:
                    query = query.where(Store.key == store_key)

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
        Get orders for date range with line items

        Returns list with order details, line items, and analytics
        """
        if not is_db_configured():
            return None

        try:
            async with get_db() as db:
                query = (
                    select(Order)
                    .options(
                        selectinload(Order.customer),
                        selectinload(Order.line_items).selectinload(OrderLineItem.variant).selectinload(Variant.product)
                    )
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
                    gross = _decimal_to_float(order.gross) or 0
                    discounts = _decimal_to_float(order.discounts) or 0
                    refunds = _decimal_to_float(order.refunds) or 0

                    # PSP fee estimate for this order (2.9% + $0.30)
                    psp_fee = round(net * 0.029 + 0.30, 2) if net > 0 else 0

                    # Profit = net + shipping - cogs - psp_fee
                    profit = net + shipping - cogs - psp_fee
                    margin_pct = (profit / (net + shipping)) * 100 if (net + shipping) > 0 else 0

                    # Build line items
                    items = []
                    items_count = 0
                    for line_item in order.line_items:
                        qty = line_item.quantity or 0
                        items_count += qty

                        product_title = ""
                        variant_title = ""
                        if line_item.variant:
                            variant_title = line_item.variant.title or ""
                            if line_item.variant.product:
                                product_title = line_item.variant.product.title or ""

                        item_name = f"{product_title} - {variant_title}".strip(" - ") if product_title or variant_title else "Unknown Item"

                        items.append({
                            "sku": line_item.sku or "",
                            "name": item_name,
                            "quantity": qty,
                            "gross": _decimal_to_float(line_item.gross) or 0,
                            "unit_cogs": _decimal_to_float(line_item.unit_cogs) or 0,
                            "total_cogs": round((_decimal_to_float(line_item.unit_cogs) or 0) * qty, 2)
                        })

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
                        "gross": gross,
                        "discounts": discounts,
                        "refunds": refunds,
                        "net": net,
                        "shipping": shipping,
                        "cogs": cogs,
                        "psp_fee": psp_fee,
                        "profit": round(profit, 2),
                        "margin_pct": round(margin_pct, 1),
                        "items_count": items_count,
                        "items": items,
                        "store": ""
                    })

                # Calculate analytics
                total_orders = len(orders_data)
                cancelled_count = sum(1 for o in orders_data if o.get("is_cancelled"))
                active_orders = [o for o in orders_data if not o.get("is_cancelled")]

                total_net = sum(o.get("net", 0) for o in active_orders)
                total_profit = sum(o.get("profit", 0) for o in active_orders)
                returning_count = sum(1 for o in active_orders if o.get("is_returning"))

                # Channel counts
                channels = {}
                for o in active_orders:
                    ch = o.get("channel", "organic")
                    channels[ch] = channels.get(ch, 0) + 1

                # Top countries
                country_counts = {}
                for o in active_orders:
                    country = o.get("country", "Unknown")
                    country_counts[country] = country_counts.get(country, 0) + 1
                top_countries = sorted(
                    [{"country": k, "count": v} for k, v in country_counts.items()],
                    key=lambda x: x["count"], reverse=True
                )[:10]

                # Peak hours
                hour_counts = {}
                for o in active_orders:
                    hour = o.get("hour", 0)
                    hour_counts[hour] = hour_counts.get(hour, 0) + 1
                peak_hours = sorted(
                    [{"hour": k, "count": v} for k, v in hour_counts.items()],
                    key=lambda x: x["count"], reverse=True
                )[:5]

                analytics = {
                    "total_orders": total_orders,
                    "cancelled_orders": cancelled_count,
                    "total_net": round(total_net, 2),
                    "avg_order_value": round(total_net / len(active_orders), 2) if active_orders else 0,
                    "total_profit": round(total_profit, 2),
                    "avg_margin_pct": round(sum(o.get("margin_pct", 0) for o in active_orders) / len(active_orders), 1) if active_orders else 0,
                    "returning_customers": returning_count,
                    "channels": channels,
                    "top_countries": top_countries,
                    "peak_hours": peak_hours
                }

                return {
                    "orders": orders_data,
                    "analytics": analytics
                }

        except Exception as e:
            print(f"❌ Database error in get_orders: {e}")
            import traceback
            traceback.print_exc()
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
                # Aggregate directly from orders table with channel attribution
                # Note: returning_customers counts UNIQUE customer_ids where is_returning=True
                query = (
                    select(
                        func.date(Order.created_at).label('order_date'),
                        func.count(Order.id).label('orders'),
                        # Count unique returning customers (not total returning orders)
                        func.count(func.distinct(case((Order.is_returning == True, Order.customer_id), else_=None))).label('returning_customers'),
                        func.sum(Order.gross).label('gross'),
                        func.sum(Order.discounts).label('discounts'),
                        func.sum(Order.refunds).label('refunds'),
                        func.sum(Order.net).label('net'),
                        func.sum(Order.cogs).label('cogs'),
                        func.sum(Order.shipping_charged).label('shipping_charged'),
                        # Channel-based purchase counts (like Shopify attribution)
                        func.sum(case((Order.channel == 'google', 1), else_=0)).label('google_pur'),
                        func.sum(case((Order.channel == 'meta', 1), else_=0)).label('meta_pur'),
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
                    google_pur = row.google_pur or 0
                    meta_pur = row.meta_pur or 0
                    returning_customers = row.returning_customers or 0

                    # Calculate metrics matching original formula from master_report_mirai.py
                    aov = gross / orders_count if orders_count > 0 else 0

                    # PSP fees will be fetched from database below
                    # Default to estimate: 2.9% + $0.30 per transaction
                    psp_usd = net * 0.029 + 0.30 * orders_count

                    # Shipping cost estimate (use 80% of shipping charged as estimate)
                    shipping_cost = shipping_charged * 0.8

                    # Revenue base = net + shipping charged (matches original)
                    revenue_base = net + shipping_charged

                    # Operational profit = (net + shipping_charged) - shipping_cost - cogs - psp
                    operational = revenue_base - shipping_cost - cogs - psp_usd

                    # Margin will be recalculated after ad spend is added
                    # margin = operational - total_spend
                    # margin_pct = margin / revenue_base (as decimal, not percentage)

                    # Format date for display
                    date_str = row.order_date.isoformat() if hasattr(row.order_date, 'isoformat') else str(row.order_date)
                    # Create label in DD/MM/YYYY format
                    try:
                        from datetime import datetime as dt
                        d = dt.strptime(date_str, "%Y-%m-%d")
                        label = d.strftime("%d/%m/%Y")  # DD/MM/YYYY
                    except:
                        label = date_str

                    kpis.append({
                        "date": date_str,
                        "label": label,  # Frontend expects this for display
                        "orders": orders_count,
                        "gross": round(gross, 2),
                        "discounts": round(discounts, 2),
                        "refunds": round(refunds, 2),
                        "net": round(net, 2),
                        "cogs": round(cogs, 2),
                        "shipping_charged": round(shipping_charged, 2),
                        "shipping_cost": round(shipping_cost, 2),
                        "psp_usd": round(psp_usd, 2),
                        "google_spend": 0,  # Will be filled from ad_spend table
                        "meta_spend": 0,
                        "total_spend": 0,
                        "operational": round(operational, 2),
                        "margin": round(operational, 2),  # Will be recalculated with ad spend
                        "margin_pct": round((operational / revenue_base) if revenue_base > 0 else 0, 2),
                        "revenue_base": round(revenue_base, 2),
                        "aov": round(aov, 2),
                        "returning_customers": returning_customers,
                        "general_cpa": None,
                        "google_pur": google_pur,
                        "meta_pur": meta_pur,
                        "google_cpa": None,  # Will be calculated after ad spend
                        "meta_cpa": None,
                    })

                # Fetch ad spend and PSP fees for these dates and merge
                if kpis:
                    dates = [datetime.strptime(k["date"], "%Y-%m-%d").date() for k in kpis]
                    ad_query = select(AdSpend).where(
                        and_(
                            AdSpend.date >= min(dates),
                            AdSpend.date <= max(dates)
                        )
                    )
                    ad_result = await db.execute(ad_query)
                    ad_rows = ad_result.scalars().all()

                    # Fetch PSP fees from database
                    psp_query = select(DailyPspFee).where(
                        and_(
                            DailyPspFee.date >= min(dates),
                            DailyPspFee.date <= max(dates)
                        )
                    )
                    psp_result = await db.execute(psp_query)
                    psp_rows = psp_result.scalars().all()

                    # Build PSP lookup: {date: fee}
                    psp_lookup = {}
                    for psp in psp_rows:
                        psp_lookup[psp.date.isoformat()] = _decimal_to_float(psp.fee_amount) or 0

                    # Build lookup: {date: {platform: spend}}
                    ad_lookup = {}
                    for ad in ad_rows:
                        d_key = ad.date.isoformat()
                        if d_key not in ad_lookup:
                            ad_lookup[d_key] = {"google": 0, "meta": 0}
                        if ad.platform == "google":
                            ad_lookup[d_key]["google"] += _decimal_to_float(ad.spend_usd) or 0
                        elif ad.platform == "meta":
                            ad_lookup[d_key]["meta"] += _decimal_to_float(ad.spend_usd) or 0

                    # Merge ad spend and PSP fees into KPIs
                    for kpi in kpis:
                        ad_data = ad_lookup.get(kpi["date"], {"google": 0, "meta": 0})
                        google_spend = ad_data["google"]
                        meta_spend = ad_data["meta"]
                        total_spend = google_spend + meta_spend

                        kpi["google_spend"] = round(google_spend, 2)
                        kpi["meta_spend"] = round(meta_spend, 2)
                        kpi["total_spend"] = round(total_spend, 2)

                        # Use real PSP fees from database if available, otherwise keep estimate
                        real_psp = psp_lookup.get(kpi["date"])
                        if real_psp is not None:
                            kpi["psp_usd"] = round(real_psp, 2)

                        # Recalculate operational profit with real PSP fees
                        # operational = (net + shipping_charged) - shipping_cost - cogs - psp
                        revenue_base = kpi.get("revenue_base", kpi["net"])
                        shipping_cost = kpi.get("shipping_cost", 0)
                        cogs = kpi.get("cogs", 0)
                        psp_usd = kpi.get("psp_usd", 0)
                        kpi["operational"] = round(revenue_base - shipping_cost - cogs - psp_usd, 2)

                        # Recalculate margin with ad spend (matching original formula)
                        # margin = operational - total_spend
                        kpi["margin"] = round(kpi["operational"] - total_spend, 2)

                        # margin_pct = margin / revenue_base (as decimal 0.xx, not percentage)
                        kpi["margin_pct"] = round(kpi["margin"] / revenue_base, 2) if revenue_base > 0 else 0

                        # Calculate CPAs (like Shopify attribution)
                        if kpi["orders"] > 0 and total_spend > 0:
                            kpi["general_cpa"] = round(total_spend / kpi["orders"], 2)

                        # Google CPA = google_spend / google_purchases
                        if kpi["google_pur"] > 0 and google_spend > 0:
                            kpi["google_cpa"] = round(google_spend / kpi["google_pur"], 2)

                        # Meta CPA = meta_spend / meta_purchases
                        if kpi["meta_pur"] > 0 and meta_spend > 0:
                            kpi["meta_cpa"] = round(meta_spend / kpi["meta_pur"], 2)

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
