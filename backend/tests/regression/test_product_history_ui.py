"""Read-only product history and Mississauga inventory regression checks."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('product_history_ui_under_test',ROOT/'backend/product_history.py')
history=importlib.util.module_from_spec(spec)
deps=types.ModuleType('deps')
async def auth():return {'id':'tester'}
deps.get_current_user=auth;deps.pool=None
with patch.dict(sys.modules,{'deps':deps}):spec.loader.exec_module(history)
sys.path.insert(0,str(ROOT/'backend'))

class Conn:
    def __init__(self,tables=(),missing=False):self.tables=set(tables);self.calls=[];self.missing=missing
    async def fetchrow(self,sql,*args):
        self.calls.append((sql,args))
        return None if self.missing else {'id':'product-a','supplier_id':'supplier-a','supplier_sku':' STYLE-A '}
    async def fetchval(self,sql,*args):
        self.calls.append((sql,args))
        if 'to_regclass' in sql:return next((name for name in self.tables if name in sql),None)
        if 'lightspeed_store_id' in sql:return ' Test-Store '
        return 1
    async def fetch(self,sql,*args):
        self.calls.append((sql,args))
        if 'SELECT variant_sku' in sql:return [{'variant_sku':'PART-1'},{'variant_sku':'part-1'},{'variant_sku':None}]
        return [{'key':'supplier:job:inventory:STYLE-A','recorded_at':'2026-11-07T01:00:00Z','data':json.dumps({'operation':'inventory','sku':'STYLE-A','status':'succeeded','result':{'message':'Imported'}})}]
class Pool:
    def __init__(self,conn):self.conn=conn
    def acquire(self):return self
    async def __aenter__(self):return self.conn
    async def __aexit__(self,*args):pass

class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_product_and_supplier_scope_and_pagination(self):
        conn=Conn(['supplier_sync_items','lightspeed_sync_items','lightspeed_review_jobs'])
        with patch.object(deps,'pool',Pool(conn)):
            result=await history.product_history('product-a',direction='outbound',search='SKU',page=2,user={})
        self.assertEqual(result['items'][0]['result']['message'],'Imported')
        sql,args=next((q,a) for q,a in conn.calls if 'OFFSET $8' in q)
        self.assertEqual(args[0],'supplier-a');self.assertEqual(set(args[1]),{'style-a','part-1'})
        self.assertEqual(args[2:6],('product-a','outbound','test-store',' STYLE-A '))
        self.assertEqual(args[-2:],('%SKU%',25))
        self.assertIn('l.supplier_id=$1',sql);self.assertIn('LOWER(BTRIM(i.sku))=ANY($2::text[])',sql)
        self.assertIn('i.product_id=$3',sql);self.assertIn('j.product_id=$3',sql)
        self.assertEqual(sql.count('LOWER(BTRIM('),3)
        self.assertTrue(all(not any(word in q.upper() for word in ['INSERT ','UPDATE ','DELETE ','CREATE ']) for q,_ in conn.calls))
    async def test_all_optional_source_combinations_parse(self):
        try:from pglast import parse_sql
        except ImportError:parse_sql=None
        names=['supplier_sync_items','lightspeed_sync_items','lightspeed_review_jobs']
        for bits in range(8):
            conn=Conn([name for i,name in enumerate(names) if bits&(1<<i)])
            with patch.object(deps,'pool',Pool(conn)):
                await history.product_history('product-a',direction='inbound',search='',page=1,user={})
            queries=[q for q,a in conn.calls if 'WITH scope' in q]
            self.assertEqual(len(queries),2)
            for sql in queries:
                for n in range(1,8):self.assertIn('$'+str(n),sql)
                if parse_sql:parse_sql(sql)
    async def test_missing_product_is_404(self):
        with patch.object(deps,'pool',Pool(Conn(missing=True))):
            with self.assertRaises(history.HTTPException) as caught:await history.product_history('missing',direction='inbound',page=1,user={})
        self.assertEqual(caught.exception.status_code,404)
    def test_route_is_authenticated(self):
        route=next(r for r in history.router.routes if r.path.endswith('/history'))
        self.assertTrue(route.dependant.dependencies)

class InventoryTests(unittest.TestCase):
    def test_only_mississauga_quantity_is_displayed(self):
        source=[{'variant_sku':'a','inventory':90,'warehouse_inventory':[{'name':'Vancouver/BC','quantity':90},{'name':'MISSISSAUGA/ON','quantity':4}]}]
        self.assertEqual(history.mississauga_inventory(source,'Vancouver/BC')[0]['inventory'],4)
        self.assertEqual(source[0]['inventory'],90)
    def test_other_or_unknown_warehouse_total_is_not_relabelled(self):
        for warehouse in ['',None,'Vancouver/BC']:
            self.assertIsNone(history.mississauga_inventory([{'inventory':90}],warehouse)[0]['inventory'])
    def test_known_mississauga_saved_stock_preserves_zero(self):
        self.assertEqual(history.mississauga_inventory([{'inventory':0}],'MISSISSAUGA/ON')[0]['inventory'],0)
    def test_missing_or_duplicate_warehouse_is_unknown(self):
        for warehouses in [[{'name':'Vancouver/BC','quantity':9}],[{'name':'MISSISSAUGA/ON','quantity':4}]*2]:
            self.assertIsNone(history.mississauga_inventory([{'inventory':90,'warehouse_inventory':warehouses}],'MISSISSAUGA/ON')[0]['inventory'])
    def test_invalid_warehouse_json_is_unknown(self):
        self.assertIsNone(history.mississauga_inventory([{'inventory':90,'warehouse_inventory':'broken'}],'MISSISSAUGA/ON')[0]['inventory'])
if __name__=='__main__':unittest.main()
