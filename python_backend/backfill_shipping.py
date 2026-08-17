#!/usr/bin/env python3
"""
Backfill shipping_cost for all historical orders using shipping matrix lookup.

Uses the same rules as sync_orders.py:
  - weight fallback: items x DEFAULT_ITEM_WEIGHT_KG when total_weight_g is 0
  - GEO-miss fallback: 80% of shipping_charged (never $0 "free shipping")

Run from python_backend directory: python3 backfill_shipping.py
"""
import asyncio
import os
from database.connection import init_db, get_db
from database.models import Order, OrderLineItem
from sqlalchemy import select, func
from master_report_mirai import _lookup_matrix_shipping_usd, _canonical_geo

DEFAULT_ITEM_WEIGHT_KG = float(os.getenv("DEFAULT_ITEM_WEIGHT_KG", "0.25") or 0.25)


async def backfill():
    await init_db()
    async with get_db() as db:
        # item counts per order (for the weight fallback)
        qty_rows = await db.execute(
            select(OrderLineItem.order_id, func.sum(OrderLineItem.quantity))
            .group_by(OrderLineItem.order_id)
        )
        qty_by_order = {oid: int(q or 0) for oid, q in qty_rows.all()}

        result = await db.execute(select(Order))
        orders = result.scalars().all()
        updated = 0
        fallbacks = 0
        for order in orders:
            weight_kg = (order.total_weight_g or 0) / 1000.0
            if weight_kg <= 0:
                weight_kg = qty_by_order.get(order.id, 0) * DEFAULT_ITEM_WEIGHT_KG
            geo = _canonical_geo(order.country or "", order.country_code or "")
            cost = round(_lookup_matrix_shipping_usd(geo, weight_kg), 2)
            charged = float(order.shipping_charged or 0)
            if cost <= 0 and charged > 0:
                cost = round(charged * 0.8, 2)
                fallbacks += 1
            order.shipping_cost = cost
            updated += 1
            if updated % 500 == 0:
                print(f"Processed {updated} orders...")
        await db.commit()
        print(f"Done! Updated {updated} orders with shipping costs ({fallbacks} used the 80% fallback)")


if __name__ == "__main__":
    asyncio.run(backfill())
