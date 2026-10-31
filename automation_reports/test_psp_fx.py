#!/usr/bin/env python3
"""PSP fee currency conversion.

Shopify Payments balance-transaction fees are denominated in that
transaction's own currency. Order 6455's fee was CAD 7.70. Treating every
fee as EUR (× FX_EUR_TO_USD ≈ 1.17) reported $9.01 and profit $9.91.
CAD 7.70 at FX_CAD_TO_USD=0.7155 is $5.51, and profit is $13.41.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from psp_fx import (
    charge_order_fee_usd,
    fee_to_usd,
    interpret_stored_daily_fee,
    sum_transaction_fees_usd,
    transaction_fee_usd,
)


# Published alert for order 6455: profit $9.91 included a PSP line of $9.01.
# The non-fee residual is what the profit formula adds back.
ORDER_6455_RESIDUAL_USD = 9.91 + 9.01  # 18.92


class PspFeeCurrency(unittest.TestCase):
    def setUp(self):
        self._saved = {
            key: os.environ.get(key)
            for key in (
                "FX_EUR_TO_USD",
                "FX_USD_TO_USD",
                "FX_CAD_TO_USD",
                "FX_AUD_TO_USD",
                "FX_GBP_TO_USD",
            )
        }
        os.environ["FX_EUR_TO_USD"] = "1.17"
        os.environ["FX_CAD_TO_USD"] = "0.7155"
        os.environ["FX_AUD_TO_USD"] = "0.66"
        os.environ.pop("FX_USD_TO_USD", None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_eur_fee_still_uses_eur_rate(self):
        self.assertEqual(fee_to_usd(7.70, "EUR"), 9.01)
        self.assertEqual(fee_to_usd(10, "eur"), 11.70)

    def test_usd_fee_is_not_treated_as_eur(self):
        os.environ["FX_USD_TO_USD"] = "1.17"
        self.assertEqual(fee_to_usd(7.70, "USD"), 7.70)
        self.assertNotEqual(fee_to_usd(7.70, "USD"), 9.01)

    def test_cad_fee_uses_cad_rate_not_eur(self):
        # 7.70 × 1.17 = 9.01 was the overstated order-6455 line.
        self.assertEqual(fee_to_usd(7.70, "CAD"), 5.51)
        self.assertNotEqual(fee_to_usd(7.70, "CAD"), 9.01)

    def test_aud_fee_uses_aud_rate_not_eur(self):
        self.assertEqual(fee_to_usd(10, "AUD"), 6.60)
        self.assertNotEqual(fee_to_usd(10, "AUD"), 11.70)

    def test_order_6455_fee_and_profit(self):
        txn = {
            "type": "charge",
            "fee": "7.70",
            "currency": "CAD",
            "order_id": 6455,
        }
        parsed = charge_order_fee_usd(txn)
        self.assertIsNotNone(parsed)
        order_id, fee_usd = parsed
        self.assertEqual(order_id, 6455)
        self.assertEqual(fee_usd, 5.51)
        profit = round(ORDER_6455_RESIDUAL_USD - fee_usd, 2)
        self.assertEqual(profit, 13.41)
        # The old alert.
        self.assertEqual(round(7.70 * 1.17, 2), 9.01)
        self.assertEqual(round(ORDER_6455_RESIDUAL_USD - 9.01, 2), 9.91)

    def test_fallback_rates_when_env_unset(self):
        os.environ.pop("FX_CAD_TO_USD", None)
        os.environ.pop("FX_AUD_TO_USD", None)
        # Fallbacks must not be the EUR rate. 7.70 × 0.72 = 5.54, not 9.01.
        self.assertEqual(fee_to_usd(7.70, "CAD"), 5.54)
        self.assertEqual(fee_to_usd(10, "AUD"), 6.50)
        self.assertEqual(fee_to_usd(7.70, "EUR"), 9.01)

    def test_unknown_currency_is_not_converted_as_eur(self):
        self.assertEqual(fee_to_usd(10, "MXN"), 10.00)
        self.assertNotEqual(fee_to_usd(10, "MXN"), 11.70)

    def test_missing_currency_keeps_historical_eur_assumption(self):
        self.assertEqual(fee_to_usd(7.70, None), 9.01)
        self.assertEqual(fee_to_usd(7.70, ""), 9.01)
        self.assertEqual(transaction_fee_usd({"fee": "7.70"}), 9.01)

    def test_invalid_env_rate_falls_back(self):
        os.environ["FX_CAD_TO_USD"] = "not-a-rate"
        self.assertEqual(fee_to_usd(7.70, "CAD"), 5.54)

    def test_daily_total_converts_each_fee_before_summing(self):
        txns = [
            {"fee": "10.00", "currency": "EUR"},
            {"fee": "7.70", "currency": "CAD"},
            {"fee": "3.00", "currency": "USD"},
            {"fee": "4.00", "currency": "AUD"},
        ]
        # 11.70 + 5.51 + 3.00 + 2.64 = 22.85
        self.assertEqual(sum_transaction_fees_usd(txns), 22.85)
        raw = 10 + 7.70 + 3 + 4
        self.assertNotEqual(sum_transaction_fees_usd(txns), round(raw * 1.17, 2))

    def test_charge_index_sums_same_order_in_each_fee_currency(self):
        first = charge_order_fee_usd(
            {"type": "payment", "fee": 4, "currency": "USD", "source_order_id": 100}
        )
        second = charge_order_fee_usd(
            {"type": "sale", "fee": 2, "currency": "EUR", "source_id": 100}
        )
        self.assertEqual(first, (100, 4.00))
        self.assertEqual(second, (100, 2.34))
        self.assertEqual(round(first[1] + second[1], 2), 6.34)

    def test_non_charge_is_excluded_from_order_index_but_not_from_daily_total(self):
        refund = {"type": "refund", "fee": "1.50", "currency": "USD", "order_id": 9}
        self.assertIsNone(charge_order_fee_usd(refund))
        self.assertEqual(transaction_fee_usd(refund), 1.50)

    def test_stored_usd_rows_are_not_converted_again(self):
        # Legacy rows were a raw sum labeled EUR and converted on read.
        self.assertEqual(interpret_stored_daily_fee(10, "EUR"), 11.70)
        self.assertEqual(interpret_stored_daily_fee(10, None), 11.70)
        # Rows written after per-currency conversion are already USD.
        self.assertEqual(interpret_stored_daily_fee(5.51, "USD"), 5.51)
        self.assertNotEqual(interpret_stored_daily_fee(5.51, "USD"), round(5.51 * 1.17, 2))

    def test_report_call_sites_use_per_transaction_currency(self):
        root = Path(__file__).resolve().parent
        backend = root.parent / "python_backend"
        monitor = (root / "monitor_orders.py").read_text()
        psp = (root / "psp_fee.py").read_text()
        report = (root / "master_report_mirai.py").read_text()
        backend_psp = (backend / "psp_fee.py").read_text()
        backend_report = (backend / "master_report_mirai.py").read_text()
        service = (backend / "database" / "service.py").read_text()

        self.assertIn("charge_order_fee_usd", monitor)
        self.assertNotIn("_eur_to_usd(", monitor.split("def _compute_alert_fields")[1])
        self.assertIn("transaction_fee_usd", psp)
        self.assertNotIn('_fx_any_to_usd(psp', report)
        self.assertNotIn(', "EUR")', report)
        self.assertIn("transaction_fee_usd", backend_psp)
        self.assertNotIn('_fx_any_to_usd(psp', backend_report)
        self.assertNotIn(', "EUR")', backend_report)
        self.assertIn("interpret_stored_daily_fee", service)
        self.assertNotIn("real_psp * _fx_eur", service)


if __name__ == "__main__":
    unittest.main()
