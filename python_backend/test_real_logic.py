#!/usr/bin/env python3
"""
Test the real mirai_report logic locally
"""
from datetime import date
from master_report_mirai import compute_day_kpis, get_shop_timezone
import os

# Test with a recent date
test_date = date(2026, 1, 6)
shop_tz = get_shop_timezone() or os.getenv('REPORT_TZ') or 'UTC'

print(f'Testing with date: {test_date}')
print(f'Timezone: {shop_tz}')
print('Calling compute_day_kpis...')
print()

kpis = compute_day_kpis(test_date, shop_tz)

print(f'✅ Success!')
print(f'Orders: {kpis.orders}')
print(f'Net: ${kpis.net}')
print(f'COGS: ${kpis.cogs}')
print(f'Shipping (est): ${kpis.shipping_estimated}')
print(f'Ad Spend: ${kpis.total_spend}')
print(f'Operational Profit: ${kpis.operational}')
print(f'Margin: ${kpis.margin}')
print(f'Margin %: {kpis.margin_pct}%')
print(f'AOV: ${kpis.aov}')
print(f'CPA: ${kpis.general_cpa}')
print(f'Returning Customers: {kpis.returning_count}')
