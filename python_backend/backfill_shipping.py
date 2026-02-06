#!/usr/bin/env python3
"""
Backfill shipping_cost for all historical orders using shipping matrix lookup.
Run from python_backend directory: python3 backfill_shipping.py
"""
import asyncio
from database.connection import init_db, get_db
from database.models import Order
from sqlalchemy import select
from master_report_mirai import _lookup_matrix_shipping_usd, _canonical_geo

async def backfill():
    await init_db()
    async with get_db() as db:
        result = await db.execute(select(Order))
        orders = result.scalars().all()
        updated = 0
        for order in orders:
            weight_kg = (order.total_weight_g or 0) / 1000.0
            geo = _canonical_geo(order.country or "", order.country_code or "")
            cost = round(_lookup_matrix_shipping_usd(geo, weight_kg), 2)
            order.shipping_cost = cost
            updated += 1
            if updated % 500 == 0:
                print(f"Processed {updated} orders...")
        await db.commit()
        print(f"Done! Updated {updated} orders with shipping costs")

if __name__ == "__main__":
    asyncio.run(backfill())
