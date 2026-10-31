#!/usr/bin/env python3
"""PSP fee parity: skin-store writes, deterministic daily reads, backfill, per-order fees.

October 2026 acceptance numbers come from the Telegram report path
($758.89) and the dashboard's stored rows ($880.14 at FX_EUR_TO_USD=1.17).
Order #6455 is the CAD charge the Telegram alert prices at $5.51 when
FX_CAD_TO_USD=0.7155 ($5.54 on the 0.72 fallback) and profit $13.41.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

from psp_fees_logic import (
    choose_daily_psp_rows,
    order_line_profit,
    order_psp_fee_or_estimate,
    plan_daily_backfill,
    plan_order_fee_updates,
    project_daily_fees,
    resolve_skin_store,
    shopify_numeric_id,
)

# Telegram-path daily PSP (USD) for October 2026. Sums to 758.89.
TELEGRAM_OCTOBER = {
    date(2026, 10, 1): 6.53,
    date(2026, 10, 2): 28.45,
    date(2026, 10, 3): 16.31,
    date(2026, 10, 4): 51.94,
    date(2026, 10, 5): 14.75,
    date(2026, 10, 6): 30.66,
    date(2026, 10, 7): 13.36,
    date(2026, 10, 8): 18.49,
    date(2026, 10, 9): 16.86,
    date(2026, 10, 10): 16.06,
    date(2026, 10, 11): 12.51,
    date(2026, 10, 12): 7.24,
    date(2026, 10, 13): 51.26,
    date(2026, 10, 14): 33.22,
    date(2026, 10, 15): 19.17,
    date(2026, 10, 16): 27.61,
    date(2026, 10, 17): 21.62,
    date(2026, 10, 18): 43.95,
    date(2026, 10, 19): 17.85,
    date(2026, 10, 20): 19.33,
    date(2026, 10, 21): 31.26,
    date(2026, 10, 22): 15.16,
    date(2026, 10, 23): 24.37,
    date(2026, 10, 24): 19.44,
    date(2026, 10, 25): 20.51,
    date(2026, 10, 26): 36.72,
    date(2026, 10, 27): 21.84,
    date(2026, 10, 28): 50.75,
    date(2026, 10, 29): 26.51,
    date(2026, 10, 30): 26.06,
    date(2026, 10, 31): 19.10,
}

# Dashboard daily_psp_fees snapshot: store 2, EUR through the 23rd, USD after.
STORED_OCTOBER = {
    date(2026, 10, 1): (6.3, "EUR"),
    date(2026, 10, 2): (27.96, "EUR"),
    date(2026, 10, 3): (15.81, "EUR"),
    date(2026, 10, 4): (63.96, "EUR"),
    date(2026, 10, 5): (15.2, "EUR"),
    date(2026, 10, 6): (29.94, "EUR"),
    date(2026, 10, 7): (16.29, "EUR"),
    date(2026, 10, 8): (19.39, "EUR"),
    date(2026, 10, 9): (16.58, "EUR"),
    date(2026, 10, 10): (15.72, "EUR"),
    date(2026, 10, 11): (14.16, "EUR"),
    date(2026, 10, 12): (9.43, "EUR"),
    date(2026, 10, 13): (50.73, "EUR"),
    date(2026, 10, 14): (34.58, "EUR"),
    date(2026, 10, 15): (19.14, "EUR"),
    date(2026, 10, 16): (27.4, "EUR"),
    date(2026, 10, 17): (23.81, "EUR"),
    date(2026, 10, 18): (44.72, "EUR"),
    date(2026, 10, 19): (20.34, "EUR"),
    date(2026, 10, 20): (20.0, "EUR"),
    date(2026, 10, 21): (31.12, "EUR"),
    date(2026, 10, 22): (17.13, "EUR"),
    date(2026, 10, 23): (23.73, "EUR"),
    date(2026, 10, 24): (19.44, "USD"),
    date(2026, 10, 25): (20.51, "USD"),
    date(2026, 10, 26): (36.72, "USD"),
    date(2026, 10, 27): (21.84, "USD"),
    date(2026, 10, 28): (50.75, "USD"),
    date(2026, 10, 29): (26.51, "USD"),
    date(2026, 10, 30): (26.06, "USD"),
    date(2026, 10, 31): (19.1, "USD"),
}

ORDER_6455_ID = 12733562126708
# net + shipping - shipping_cost - cogs - shop_ad = 125.92 + 0 - 42 - 65 - 0
ORDER_6455_BEFORE_PSP = 18.92


class FeeRow:
    def __init__(self, id, on, store_id, fee_amount, currency="USD", created_at=None):
        self.id = id
        self.date = on
        self.store_id = store_id
        self.fee_amount = fee_amount
        self.currency = currency
        self.created_at = created_at


def _stored_rows():
    rows = []
    for index, (day, (amount, currency)) in enumerate(sorted(STORED_OCTOBER.items()), start=1):
        rows.append(FeeRow(index, day, 2, amount, currency))
    return rows


def _sum_fees(rows, skin_store_id):
    from psp_fee import interpret_stored_daily_fee
    chosen = choose_daily_psp_rows(rows, skin_store_id)
    total = 0.0
    for day in sorted(chosen):
        if day.year == 2026 and day.month == 10:
            row = chosen[day]
            total = round(total + interpret_stored_daily_fee(row.fee_amount, row.currency), 2)
    return total


class SkinStoreAndReader(unittest.TestCase):
    def test_skin_store_is_not_whichever_store_the_loop_ended_on(self):
        stores = [
            SimpleNamespace(id=1, key="skin", shopify_domain="skin.myshopify.com"),
            SimpleNamespace(id=2, key="cosmetics", shopify_domain="cosmetics.myshopify.com"),
        ]
        # The order sync walks every store and finishes on cosmetics (id 2).
        loop_store_id = stores[-1].id
        skin = resolve_skin_store(stores, "cosmetics.myshopify.com")
        self.assertEqual(skin.id, 1)
        self.assertNotEqual(skin.id, loop_store_id)

        # No key 'skin': fall back to the SHOPIFY_STORE domain.
        by_domain = [
            SimpleNamespace(id=5, key="main", shopify_domain="9dkd2w-g3.myshopify.com"),
            SimpleNamespace(id=9, key="other", shopify_domain="elsewhere.myshopify.com"),
        ]
        self.assertEqual(resolve_skin_store(by_domain, "9dkd2w-g3.myshopify.com").id, 5)
        self.assertIsNone(resolve_skin_store(by_domain, "missing.myshopify.com"))

    def test_sync_psp_fees_uses_skin_lookup(self):
        source = Path(__file__).with_name("sync_jobs").joinpath("sync_orders.py").read_text()
        body = source.split("async def _sync_psp_fees", 1)[1].split("if __name__", 1)[0]
        self.assertIn("resolve_skin_store", body)
        self.assertIn("get_order_psp_fees", body)
        self.assertNotIn("self.store_id", body)

    def test_reader_order_is_deterministic_and_prefers_skin(self):
        day = date(2026, 1, 3)
        store1 = FeeRow(7, day, 1, 5.00, "USD")
        store2 = FeeRow(260, day, 2, 99.00, "EUR")

        # Input order must not matter. Skin wins when it has the date.
        self.assertIs(choose_daily_psp_rows([store2, store1], skin_store_id=1)[day], store1)
        self.assertIs(choose_daily_psp_rows([store1, store2], skin_store_id=1)[day], store1)
        self.assertIs(choose_daily_psp_rows([store1, store2], skin_store_id=2)[day], store2)
        self.assertIs(choose_daily_psp_rows([store2, store1], skin_store_id=2)[day], store2)

        # No skin id: lowest store_id, then lowest id. Not last-write-wins.
        self.assertIs(choose_daily_psp_rows([store2, store1], None)[day], store1)
        self.assertIs(choose_daily_psp_rows([store1, store2], None)[day], store1)

        service = Path(__file__).with_name("database").joinpath("service.py").read_text()
        self.assertIn("choose_daily_psp_rows", service)
        self.assertIn(
            "order_by(DailyPspFee.date, DailyPspFee.store_id, DailyPspFee.id)",
            service,
        )

    def test_october_stored_rows_read_as_dashboard_880_14(self):
        saved = os.environ.get("FX_EUR_TO_USD")
        os.environ["FX_EUR_TO_USD"] = "1.17"
        try:
            # Skin is store 1 and has no October row, so the legacy store 2
            # row is the one the reader keeps. That is today's dashboard.
            self.assertEqual(_sum_fees(_stored_rows(), skin_store_id=1), 880.14)
        finally:
            if saved is None:
                os.environ.pop("FX_EUR_TO_USD", None)
            else:
                os.environ["FX_EUR_TO_USD"] = saved

    def test_october_telegram_rows_read_as_758_89(self):
        rows = [
            FeeRow(index, day, 1, amount, "USD")
            for index, (day, amount) in enumerate(sorted(TELEGRAM_OCTOBER.items()), start=1)
        ]
        # Store 2 still holds the old EUR amounts. Skin must win.
        rows.extend(_stored_rows())
        self.assertEqual(_sum_fees(rows, skin_store_id=1), 758.89)
        self.assertEqual(round(sum(TELEGRAM_OCTOBER.values()), 2), 758.89)


class BackfillPlan(unittest.TestCase):
    def setUp(self):
        self.saved_eur = os.environ.get("FX_EUR_TO_USD")
        os.environ["FX_EUR_TO_USD"] = "1.17"

    def tearDown(self):
        if self.saved_eur is None:
            os.environ.pop("FX_EUR_TO_USD", None)
        else:
            os.environ["FX_EUR_TO_USD"] = self.saved_eur

    def _existing(self):
        rows = _stored_rows()
        rows.append(FeeRow(900, date(2026, 1, 5), 1, 84.62, "USD"))
        rows.append(FeeRow(901, date(2026, 1, 5), 2, 84.62, "USD"))
        rows.append(FeeRow(902, date(2026, 4, 1), 2, 12.00, "EUR"))
        rows.append(FeeRow(903, date(2024, 1, 1), 2, 3.00, "USD"))
        # Skin already has this date, but Shopify did not return it. Store 2 stays.
        rows.append(FeeRow(910, date(2026, 6, 1), 1, 8.00, "USD"))
        rows.append(FeeRow(911, date(2026, 6, 1), 2, 8.00, "EUR"))
        return rows

    def _fetched(self):
        fetched = dict(TELEGRAM_OCTOBER)
        fetched[date(2026, 1, 5)] = 7.50
        fetched[date(2026, 3, 15)] = 4.20  # inside the Feb 3–Jul 5 gap
        return fetched

    def test_plan_moves_october_onto_skin_and_fills_the_gap(self):
        since, until = date(2025, 1, 29), date(2026, 10, 31)
        plan = plan_daily_backfill(self._existing(), self._fetched(), 1, since, until)
        projected = project_daily_fees(self._existing(), plan)
        self.assertEqual(_sum_fees(projected, skin_store_id=1), 758.89)
        self.assertGreaterEqual(plan["gap_inserts"], 1)
        self.assertIn("2026-03-15", {row["date"] for row in plan["inserts"]})
        deleted_ids = {row["id"] for row in plan["deletes"]}
        self.assertTrue(deleted_ids.issuperset({row.id for row in _stored_rows()}))
        self.assertIn(901, deleted_ids)  # store 2 row for a date Shopify returned
        self.assertNotIn(902, deleted_ids)  # fetch did not return this date
        self.assertNotIn(903, deleted_ids)  # outside the window
        self.assertNotIn(911, deleted_ids)  # skin already has the date, but Shopify did not return it
        jan = next(row for row in plan["updates"] if row["date"] == "2026-01-05")
        self.assertEqual(jan["id"], 900)
        self.assertEqual(jan["new_fee"], 7.50)
        self.assertEqual(jan["new_currency"], "USD")
        self.assertEqual(set(jan), {
            "id", "date", "store_id", "old_fee", "old_currency", "old_created_at",
            "new_fee", "new_currency",
        })

    def test_order_fee_plan_touches_only_psp_fee(self):
        orders = [
            SimpleNamespace(id=1, order_name="#6455", shopify_gid=f"gid://shopify/Order/{ORDER_6455_ID}",
                            psp_fee=None, shipping_cost=42, net=125.92),
            SimpleNamespace(id=2, order_name="#6454", shopify_gid="gid://shopify/Order/999",
                            psp_fee=None, shipping_cost=11, net=61.31),
            SimpleNamespace(id=3, order_name="#6453", shopify_gid="gid://shopify/Order/888",
                            psp_fee=5.51, shipping_cost=16, net=59.44),
        ]
        changes = plan_order_fee_updates(orders, {ORDER_6455_ID: 5.51, 888: 5.51})
        self.assertEqual([row["order_name"] for row in changes], ["#6455"])
        self.assertEqual(changes[0]["old"], None)
        self.assertEqual(changes[0]["new"], 5.51)
        self.assertNotIn("shipping_cost", changes[0])
        self.assertNotIn("net", changes[0])
        self.assertIsNone(shopify_numeric_id(None))
        self.assertEqual(shopify_numeric_id(f"gid://shopify/Order/{ORDER_6455_ID}"), ORDER_6455_ID)


class PerOrderFee(unittest.TestCase):
    def setUp(self):
        self.saved = os.environ.get("FX_CAD_TO_USD")

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("FX_CAD_TO_USD", None)
        else:
            os.environ["FX_CAD_TO_USD"] = self.saved

    def _charge(self):
        # Load psp_fx by file path. Putting automation_reports on sys.path
        # makes `import psp_fee` pick up that package's copy, which has no
        # order_fees_from_transactions.
        import importlib.util
        path = Path(__file__).resolve().parents[1] / "automation_reports" / "psp_fx.py"
        spec = importlib.util.spec_from_file_location("mirai_psp_fx_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.charge_order_fee_usd({
            "type": "charge",
            "fee": "7.70",
            "currency": "CAD",
            "order_id": ORDER_6455_ID,
            "processed_at": "2026-10-31T17:25:12Z",
        })

    def test_order_6455_cad_fee_and_profit(self):
        os.environ["FX_CAD_TO_USD"] = "0.7155"
        order_id, fee = self._charge()
        self.assertEqual(order_id, ORDER_6455_ID)
        self.assertEqual(fee, 5.51)
        self.assertEqual(order_psp_fee_or_estimate(fee, 125.92), 5.51)
        profit = round(order_line_profit(125.92, 0, 42, 65, fee, 0), 2)
        self.assertEqual(profit, 13.41)
        self.assertEqual(round(ORDER_6455_BEFORE_PSP - fee, 2), 13.41)

        # Missing fee is the estimate the dashboard shows today ($3.95), not 0.
        self.assertEqual(order_psp_fee_or_estimate(None, 125.92), 3.95)
        # A real zero is kept. It is not the estimate.
        self.assertEqual(order_psp_fee_or_estimate(0, 125.92), 0.0)

    def test_order_6455_default_cad_rate_is_5_54(self):
        os.environ.pop("FX_CAD_TO_USD", None)
        _order_id, fee = self._charge()
        self.assertEqual(fee, 5.54)

    def test_transaction_index_matches_the_telegram_charge_rule(self):
        import pytz
        from psp_fee import order_fees_from_transactions

        os.environ["FX_CAD_TO_USD"] = "0.7155"
        tz = pytz.UTC
        start = tz.localize(datetime(2026, 10, 31))
        end = tz.localize(datetime(2026, 11, 1))
        txns = [
            {"type": "charge", "fee": "7.70", "currency": "CAD", "order_id": ORDER_6455_ID,
             "processed_at": "2026-10-31T17:25:12Z"},
            # Refunds belong in the daily total, not on the order.
            {"type": "refund", "fee": "1.00", "currency": "USD", "order_id": ORDER_6455_ID,
             "processed_at": "2026-10-31T18:00:00Z"},
            # Outside the window.
            {"type": "charge", "fee": "3.00", "currency": "USD", "order_id": 99,
             "processed_at": "2026-10-30T12:00:00Z"},
            {"type": "payment", "fee": "1.00", "currency": "USD", "source_order_id": ORDER_6455_ID,
             "processed_at": "2026-10-31T19:00:00Z"},
        ]
        indexed = order_fees_from_transactions(txns, start, end, tz)
        self.assertEqual(indexed, {ORDER_6455_ID: 6.51})
        self.assertNotIn(99, indexed)

    def test_backend_psp_fee_is_not_shadowed(self):
        import sys
        self._charge()
        sys.modules.pop("psp_fee", None)
        import psp_fee
        loaded = Path(psp_fee.__file__).resolve().as_posix()
        self.assertIn("python_backend/psp_fee.py", loaded)
        self.assertNotIn("automation_reports", loaded)
        self.assertTrue(hasattr(psp_fee, "order_fees_from_transactions"))
        self.assertTrue(hasattr(psp_fee, "_fetch_until_for_store"))

    def test_order_report_keeps_the_last_day_in_report_tz(self):
        from psp_fees_logic import order_fee_end_exclusive
        end = date(2026, 10, 31)
        self.assertEqual(order_fee_end_exclusive(end), date(2026, 11, 1))
        report = Path(__file__).with_name("order_report_logic.py").read_text()
        self.assertIn("report_timezone_name", report)
        self.assertIn("order_fee_end_exclusive", report)
        self.assertNotIn("get_shop_timezone(", report)

    def test_readers_call_the_shared_fee_and_profit(self):
        root = Path(__file__).resolve().parent
        service = (root / "database" / "service.py").read_text()
        report = (root / "order_report_logic.py").read_text()
        for source in (service, report):
            self.assertIn("order_psp_fee_or_estimate", source)
            self.assertIn("order_line_profit", source)
        server = (root / "simple_server.py").read_text()
        self.assertIn('"/admin/backfill-psp-fees"', server)
        endpoint = server.split("async def backfill_psp_fees_endpoint", 1)[1].split("@app.post", 1)[0]
        self.assertIn("require_admin", endpoint)
        self.assertIn("run_in_threadpool", endpoint)


class BackfillDryRunAndApply(unittest.TestCase):
    def setUp(self):
        self.saved = {
            key: os.environ.get(key)
            for key in ("FX_EUR_TO_USD", "FX_CAD_TO_USD", "REPORT_TZ", "SHOPIFY_STORE")
        }
        os.environ["FX_EUR_TO_USD"] = "1.17"
        os.environ["FX_CAD_TO_USD"] = "0.7155"
        os.environ["REPORT_TZ"] = "Asia/Nicosia"
        os.environ["SHOPIFY_STORE"] = "skin.example"

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _fetched(self, since, until_exclusive, tz_name):
        fetched = dict(TELEGRAM_OCTOBER)
        fetched[date(2026, 1, 5)] = 7.50
        fetched[date(2026, 3, 15)] = 4.20
        return fetched

    def _order_fees(self, since, until_exclusive, tz_name):
        return {ORDER_6455_ID: 5.51}

    async def _session(self):
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool

        from database import models  # noqa: F401
        from database.connection import Base

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        return engine, factory

    async def _seed(self, factory):
        from database.models import DailyPspFee, Order, Store

        async with factory() as db:
            db.add(Store(id=1, key="skin", label="Mirai Skin", shopify_domain="skin.example"))
            db.add(Store(id=2, key="cosmetics", label="Mirai Cosmetics", shopify_domain="cos.example"))
            for index, (day, (amount, currency)) in enumerate(sorted(STORED_OCTOBER.items()), start=1):
                db.add(DailyPspFee(id=index, date=day, store_id=2, fee_amount=amount, currency=currency))
            db.add(DailyPspFee(id=900, date=date(2026, 1, 5), store_id=1, fee_amount=84.62, currency="USD"))
            db.add(DailyPspFee(id=901, date=date(2026, 1, 5), store_id=2, fee_amount=84.62, currency="USD"))
            db.add(DailyPspFee(id=902, date=date(2026, 4, 1), store_id=2, fee_amount=12.00, currency="EUR"))
            db.add(Order(
                id=1,
                shopify_gid=f"gid://shopify/Order/{ORDER_6455_ID}",
                order_name="#6455",
                store_id=1,
                created_at=datetime(2026, 10, 31, 12, 0, 0),
                net=125.92,
                shipping_charged=0,
                shipping_cost=42,
                cogs=65,
                gross=157.40,
                psp_fee=None,
            ))
            await db.commit()

    async def _fees(self, factory):
        from sqlalchemy import select
        from database.models import DailyPspFee
        async with factory() as db:
            rows = (await db.execute(select(DailyPspFee).order_by(DailyPspFee.id))).scalars().all()
            return [(row.id, row.date, row.store_id, round(float(row.fee_amount), 2), row.currency) for row in rows]

    async def _order(self, factory):
        from database.models import Order
        async with factory() as db:
            order = await db.get(Order, 1)
            return {
                "psp_fee": None if order.psp_fee is None else round(float(order.psp_fee), 2),
                "shipping_cost": round(float(order.shipping_cost), 2),
                "net": round(float(order.net), 2),
                "cogs": round(float(order.cogs), 2),
                "gross": round(float(order.gross), 2),
            }

    def test_dry_run_writes_nothing(self):
        asyncio.run(self._dry_run())

    async def _dry_run(self):
        from backfill_psp_fees import run_backfill

        engine, factory = await self._session()
        try:
            await self._seed(factory)
            before_fees = await self._fees(factory)
            before_order = await self._order(factory)
            snapshot = tempfile.mktemp(prefix="psp-dry-", suffix=".json")
            async with factory() as db:
                result = await run_backfill(
                    db,
                    date(2025, 1, 29),
                    date(2026, 10, 31),
                    apply=False,
                    snapshot_path=snapshot,
                    fetch_daily=self._fetched,
                    fetch_order_fees=self._order_fees,
                )
            self.assertTrue(result["dry_run"])
            self.assertFalse(result["applied"])
            self.assertFalse(os.path.exists(snapshot))
            self.assertEqual(result["october_2026_psp_usd"], 758.89)
            self.assertEqual(await self._fees(factory), before_fees)
            self.assertEqual(await self._order(factory), before_order)
            self.assertIsNone(before_order["psp_fee"])
            self.assertEqual(before_order["shipping_cost"], 42)
        finally:
            await engine.dispose()

    def test_empty_fetch_refuses_to_apply(self):
        asyncio.run(self._refuse())

    async def _refuse(self):
        from backfill_psp_fees import run_backfill

        engine, factory = await self._session()
        try:
            await self._seed(factory)
            before = await self._fees(factory)
            snapshot = tempfile.mktemp(prefix="psp-refuse-", suffix=".json")

            def empty(since, until_exclusive, tz_name):
                return {}

            async with factory() as db:
                result = await run_backfill(
                    db,
                    date(2025, 1, 29),
                    date(2026, 10, 31),
                    apply=True,
                    snapshot_path=snapshot,
                    fetch_daily=empty,
                    fetch_order_fees=empty,
                )
            self.assertTrue(result["refused"])
            self.assertFalse(os.path.exists(snapshot))
            self.assertEqual(await self._fees(factory), before)
            self.assertIsNone((await self._order(factory))["psp_fee"])
        finally:
            await engine.dispose()

    def test_apply_writes_snapshot_before_mutation_and_restore_rolls_back(self):
        asyncio.run(self._apply_and_restore())

    async def _apply_and_restore(self):
        from backfill_psp_fees import restore_snapshot, run_backfill

        engine, factory = await self._session()
        try:
            await self._seed(factory)
            before_fees = await self._fees(factory)
            snapshot = tempfile.mktemp(prefix="psp-apply-", suffix=".json")

            async def boom(db, plan):
                self.assertTrue(os.path.exists(snapshot))
                raise RuntimeError("stop before write")

            async with factory() as db:
                with self.assertRaises(RuntimeError):
                    await run_backfill(
                        db,
                        date(2025, 1, 29),
                        date(2026, 10, 31),
                        apply=True,
                        snapshot_path=snapshot,
                        fetch_daily=self._fetched,
                        fetch_order_fees=self._order_fees,
                        mutate=boom,
                    )
            self.assertTrue(os.path.exists(snapshot))
            self.assertEqual(await self._fees(factory), before_fees)
            self.assertEqual((await self._order(factory))["shipping_cost"], 42)
            self.assertIsNone((await self._order(factory))["psp_fee"])

            async with factory() as db:
                result = await run_backfill(
                    db,
                    date(2025, 1, 29),
                    date(2026, 10, 31),
                    apply=True,
                    snapshot_path=snapshot,
                    fetch_daily=self._fetched,
                    fetch_order_fees=self._order_fees,
                )
            self.assertFalse(result["dry_run"])
            self.assertEqual(result["october_2026_psp_usd"], 758.89)
            self.assertGreaterEqual(result["gap_inserts"], 1)
            order = await self._order(factory)
            self.assertEqual(order["psp_fee"], 5.51)
            self.assertEqual(order["shipping_cost"], 42)
            self.assertEqual(order["net"], 125.92)
            self.assertEqual(order["cogs"], 65)
            self.assertEqual(order["gross"], 157.40)
            fees = await self._fees(factory)
            october_skin = [
                row for row in fees
                if row[1].month == 10 and row[1].year == 2026
            ]
            self.assertTrue(all(row[2] == 1 and row[4] == "USD" for row in october_skin))
            self.assertEqual(_sum_fees([
                FeeRow(row[0], row[1], row[2], row[3], row[4]) for row in october_skin
            ], 1), 758.89)
            self.assertTrue(any(row[1] == date(2026, 3, 15) and row[2] == 1 and row[3] == 4.20 for row in fees))
            self.assertTrue(any(row[1] == date(2026, 4, 1) and row[2] == 2 for row in fees))
            self.assertFalse(any(row[1] == date(2026, 1, 5) and row[2] == 2 for row in fees))
            jan = next(row for row in fees if row[1] == date(2026, 1, 5))
            self.assertEqual((jan[2], jan[3], jan[4]), (1, 7.50, "USD"))

            import json
            from database.models import DailyPspFee
            # A cron tick after apply writes a new daily row. Restore must not delete it.
            async with factory() as db:
                db.add(DailyPspFee(
                    id=7777, date=date(2026, 5, 20), store_id=1,
                    fee_amount=10, currency="USD",
                ))
                await db.commit()
            with open(snapshot) as handle:
                saved = json.load(handle)
            self.assertTrue(saved["restore"]["inserts"])
            async with factory() as db:
                await restore_snapshot(db, saved)
            restored_fees = await self._fees(factory)
            cron = (7777, date(2026, 5, 20), 1, 10.0, "USD")
            self.assertIn(cron, restored_fees)
            for row in before_fees:
                self.assertIn(row, restored_fees)
            self.assertEqual(len(restored_fees), len(before_fees) + 1)
            restored = await self._order(factory)
            self.assertIsNone(restored["psp_fee"])
            self.assertEqual(restored["shipping_cost"], 42)
            self.assertEqual(restored["net"], 125.92)
        finally:
            await engine.dispose()

    def test_incomplete_fetch_is_flagged_and_refuses_apply(self):
        asyncio.run(self._incomplete())

    async def _incomplete(self):
        import contextlib
        from io import StringIO

        from backfill_psp_fees import _print_summary, run_backfill
        from database.models import DailyPspFee, Store

        engine, factory = await self._session()
        try:
            async with factory() as db:
                db.add(Store(id=1, key="skin", label="Mirai Skin", shopify_domain="skin.example"))
                db.add(Store(id=2, key="cosmetics", label="Cosmetics", shopify_domain="cos.example"))
                db.add(DailyPspFee(
                    id=50, date=date(2026, 10, 30), store_id=2, fee_amount=99, currency="EUR",
                ))
                await db.commit()

            def fetch_daily(since, until_exclusive, tz_name):
                return {
                    "fees": {date(2026, 10, 31): 1.0, date(2026, 10, 30): 2.0},
                    "complete": False,
                    "reason": "HTTP 429",
                }

            def fetch_orders(since, until_exclusive, tz_name):
                return {"fees": {}, "complete": True, "reason": ""}

            snapshot = tempfile.mktemp(prefix="psp-incomplete-", suffix=".json")
            async with factory() as db:
                dry = await run_backfill(
                    db, date(2026, 10, 1), date(2026, 10, 31), apply=False,
                    fetch_daily=fetch_daily, fetch_order_fees=fetch_orders,
                )
            self.assertFalse(dry["fetch_complete"])
            self.assertIn("HTTP 429", dry["fetch_reason"])
            buf = StringIO()
            with contextlib.redirect_stdout(buf):
                _print_summary(dry, dry_run=True)
            self.assertIn("INCOMPLETE SHOPIFY FETCH", buf.getvalue())

            async with factory() as db:
                applied = await run_backfill(
                    db, date(2026, 10, 1), date(2026, 10, 31), apply=True,
                    snapshot_path=snapshot,
                    fetch_daily=fetch_daily, fetch_order_fees=fetch_orders,
                )
            self.assertTrue(applied["refused"])
            self.assertFalse(applied["applied"])
            self.assertFalse(os.path.exists(snapshot))
            fees = await self._fees(factory)
            self.assertEqual(fees, [(50, date(2026, 10, 30), 2, 99.0, "EUR")])
        finally:
            await engine.dispose()


class IncompletePage(unittest.TestCase):
    def test_429_on_page_two_is_incomplete_and_keeps_the_partial_sum(self):
        import psp_fee

        saved_stores = psp_fee.SHOPIFY_STORES
        saved_sleep = psp_fee._sleep
        calls = {"n": 0}

        class Response:
            def __init__(self, status, payload, link=""):
                self.status_code = status
                self.headers = {"Link": link}
                self._payload = payload

            def json(self):
                return self._payload

        page1 = {
            "transactions": [
                {"id": 1, "fee": "1.00", "currency": "USD", "processed_at": "2026-10-31T18:00:00Z"},
                {"id": 2, "fee": "2.00", "currency": "USD", "processed_at": "2026-10-30T18:00:00Z"},
            ]
        }
        next_link = '<https://skin.example/admin/page2>; rel="next"'

        def fake_get(url, headers=None, params=None, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return Response(200, page1, next_link)
            return Response(429, {})

        psp_fee.SHOPIFY_STORES = [{
            "key": "skin", "label": "skin", "domain": "skin.example", "access_token": "tok",
        }]
        psp_fee._sleep = lambda _seconds: None
        original_get = psp_fee.requests.get
        psp_fee.requests.get = fake_get
        try:
            result = psp_fee.get_psp_fees_daily_result(
                date(2026, 10, 1), date(2026, 11, 1), tz_name="UTC",
            )
        finally:
            psp_fee.SHOPIFY_STORES = saved_stores
            psp_fee._sleep = saved_sleep
            psp_fee.requests.get = original_get

        self.assertFalse(result["complete"])
        self.assertIn("429", result["reason"])
        self.assertEqual(result["fees"], {date(2026, 10, 31): 1.0, date(2026, 10, 30): 2.0})
        self.assertGreater(calls["n"], 2)


if __name__ == "__main__":
    unittest.main()
