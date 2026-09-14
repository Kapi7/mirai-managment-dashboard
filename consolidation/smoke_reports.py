"""Offline real-dependency startup check; no production credentials or requests."""
import asyncio
import os
from pathlib import Path
import sys
import tempfile

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as d:
    # Start with an allowlist so developer machine secrets cannot enter tests.
    os.environ.clear()
    os.environ.update(REPORTS_JOBS_ENABLED='0',SHIPPING_MATRIX_AUTO_REFRESH='0',
        SUMMARY_STATE_FILE=d+'/.summary.json',TELEGRAM_SEEN_ORDERS_FILE=d+'/.seen.json')
    sys.path.insert(0,str(root/'automation_reports'))
    import server
    async def check():
        before=set(asyncio.all_tasks())
        await server.startup_event()
        assert set(asyncio.all_tasks())==before,'Staging launched background tasks'
        assert (await server.health())['status']=='ok'
    asyncio.run(check())
    routes={r.path for r in server.app.routes}
    assert {'/health','/daily-report','/ad-spend','/sync-summary','/force-backfill-today'} <= routes
    print('PASS: real reports application imports, health responds, routes retained, staging launches no jobs')
