import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('supervisor', HERE / 'supervisor.py')
sup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sup)

class CutoverSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        config = self.data / 'env.json'
        config.write_text(json.dumps({'SHOPIFY_TOKEN':'reports-token'}))
        self.env = dict(REPORTS_ENV_FILE=str(config), REPORTS_DATA_DIR=str(self.data),
                        SHOPIFY_TOKEN='dashboard-token', OPENAI_API_KEY='dashboard-secret', PATH='/usr/bin')
    def test_staging_disables_jobs_and_isolates_credentials(self):
        result = sup.reports_environment(self.env)
        self.assertEqual(result['REPORTS_JOBS_ENABLED'], '0')
        self.assertEqual(result['SHOPIFY_TOKEN'], 'reports-token')
        self.assertNotIn('OPENAI_API_KEY', result)
    def snapshot(self):
        hashes = {}
        for name in sup.STATE_NAMES:
            p=self.data/name;p.write_text('{}')
            hashes[name]=hashlib.sha256(p.read_bytes()).hexdigest()
        (self.data/'cutover-manifest.json').write_text(json.dumps(dict(source_suspended=True,sha256=hashes)))
        self.env['REPORTS_JOBS_ENABLED']='1'
    def test_jobs_reject_missing_snapshot(self):
        self.env['REPORTS_JOBS_ENABLED']='1'
        with self.assertRaises(FileNotFoundError):sup.reports_environment(self.env)
    def test_jobs_reject_unverified_state(self):
        self.snapshot();(self.data/sup.STATE_NAMES[0]).write_text('{"changed":true}')
        with self.assertRaises(ValueError):sup.reports_environment(self.env)
    def test_jobs_reject_running_source(self):
        self.snapshot();p=self.data/'cutover-manifest.json'
        m=json.loads(p.read_text());m['source_suspended']=False;p.write_text(json.dumps(m))
        with self.assertRaises(ValueError):sup.reports_environment(self.env)
    def test_restart_accepts_state_updated_by_jobs(self):
        self.snapshot();sup.reports_environment(self.env)
        (self.data/sup.STATE_NAMES[0]).write_text('{"new":123}')
        self.assertEqual(sup.reports_environment(self.env)['REPORTS_JOBS_ENABLED'],'1')
    def test_restart_still_requires_state_files(self):
        self.snapshot();sup.reports_environment(self.env)
        (self.data/sup.STATE_NAMES[0]).unlink()
        with self.assertRaises(ValueError):sup.reports_environment(self.env)

class GoogleTransportLifetime(unittest.TestCase):
    def setUp(self):
        source=(HERE.parent/'automation_reports/google_ads_spend.py').read_text()
        tree=ast.parse(source)
        names={'_query_hourly_cost','_query_daily_cost','_discover_leaf_accounts','_fetch_account_meta'}
        functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
        namespace={'GoogleAdsClient':object,'List':list,'Tuple':tuple,'_QUERY_ACCOUNT_META':'query'}
        exec(compile(ast.Module(body=functions,type_ignores=[]),'<functions>','exec'),namespace)
        self.ns=namespace
        self.closed=0
        owner=self
        class Service:
            transport=types.SimpleNamespace(close=lambda: setattr(owner,'closed',owner.closed+1))
            def search(self,**kwargs):return owner.rows()
        self.svc=Service()
        self.client=types.SimpleNamespace(get_service=lambda _:self.svc,get_type=lambda _:types.SimpleNamespace())
    def rows(self):
        yield types.SimpleNamespace(metrics=types.SimpleNamespace(cost_micros=1200000),
            customer=types.SimpleNamespace(currency_code='EUR',time_zone='Europe/Nicosia'),
            customer_client=types.SimpleNamespace(hidden=False,manager=False,id=123))
    def test_pagination_consumed_before_transport_close(self):
        iterator=self.ns['_query_hourly_cost'](self.client,'123','2026-09-01','2026-09-02')
        self.assertEqual(self.closed,0)
        self.assertEqual(len(list(iterator)),1);self.assertEqual(self.closed,1)
    def test_exception_closes_transport(self):
        def error():raise RuntimeError('API failed')
        self.rows=error
        with self.assertRaises(RuntimeError):list(self.ns['_query_hourly_cost'](self.client,'123','a','b'))
        self.assertEqual(self.closed,1)
    def test_daily_amount_preserved(self):
        self.assertEqual(self.ns['_query_daily_cost'](self.client,'123','2026-09-01'),1.2)
        self.assertEqual(self.closed,1)
    def test_meta_early_return_closes_transport(self):
        self.assertEqual(self.ns['_fetch_account_meta'](self.client,'123'),('EUR','Europe/Nicosia'))
        self.assertEqual(self.closed,1)
    def test_discovery_preserved(self):
        self.assertEqual(self.ns['_discover_leaf_accounts'](self.client,'123'),['123'])
        self.assertEqual(self.closed,1)

if __name__=='__main__':unittest.main()
