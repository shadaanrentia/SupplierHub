"""Offline regressions. Uses the backend environment; never calls supplier APIs."""
import asyncio
from contextlib import asynccontextmanager
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'backend'))
import deps
import sync_history as history
import outbound_history as outbound
import category_scope as categories

class Pool:
    def __init__(self,conn):self.conn=conn
    @asynccontextmanager
    async def acquire(self):yield self.conn

class Fake:
    def __init__(self,present=None):self.present=present;self.calls=[]
    async def fetchval(self,sql,*args):
        self.calls.append((sql,args))
        if 'to_regclass' in sql:return args[0] if self.present is None or args[0].split('.')[-1] in self.present else None
        return 1
    async def fetchrow(self,sql,*args):
        self.calls.append((sql,args))
        if 'COUNT(*) total' in sql:return {'total':1,'active':0,'completed':1,'attention':0}
        if 'WHERE key=$1' in sql:return {'key':args[0],'data':{'id':'example','status':'completed','direction':'outbound'}}
        return None
    async def fetch(self,sql,*args):
        self.calls.append((sql,args))
        if 'SELECT DISTINCT s.id' in sql:return [{'id':'supplier-a','supplier_name':'Supplier A'}]
        if 'SELECT DISTINCT data' in sql:return [{'operation':'catalogue batch'}]
        if 'FROM filtered ORDER BY' in sql:return [{'key':'batch:example','data':json.dumps({'status':'completed','direction':'outbound'})}]
        if 'FROM lightspeed_sync_items WHERE' in sql:return [{'sku':'SKU-1','details_result':'{"synced":1}','images_result':'{}'}]
        return []
    async def execute(self,sql,*args):self.calls.append((sql,args));return 'UPDATE 1'

class CategoryTests(unittest.TestCase):
    def test_nested_category_names(self):
        self.assertEqual(categories.category_labels([{'id':'root','name':'Apparel','children':[{'id':'tee','name':'Tees'}]}])['tee'],'Apparel > Tees')
    def test_published_path_names(self):
        self.assertEqual(categories.category_labels([{'lightspeed_category_id':'tee','category_name':'Tees','category_path':[{'name':'Apparel'},{'name':'Tops'},{'name':'Tees'}]}])['tee'],'Apparel > Tops > Tees')
    def test_distinct_missing_ids_not_merged(self):
        rows=categories.category_rows([{'id':'a','supplier_id':'s','category':'A'},{'id':'b','supplier_id':'s','category':'B'}],{'a':{'mapped_lightspeed_category_id':'old-a'},'b':{'mapped_lightspeed_category_id':'old-b'}},{'current':'Apparel'})
        self.assertEqual(len(rows),2)
        self.assertFalse(rows[('s','old-a')]['category_available'])
        self.assertIn('old-a',rows[('s','old-a')]['category_name'])
    def test_category_scope_is_exact(self):
        self.assertTrue(categories.in_category({'mapped_lightspeed_category_id':'x'},'x'))
        self.assertFalse(categories.in_category({'mapped_lightspeed_category_id':'x'},'y'))

class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_optional_tables(self):
        sql=await history.sources(Fake(set()))
        self.assertIn('WHERE FALSE',sql)
        sql=await history.sources(Fake({'lightspeed_review_jobs'}))
        self.assertIn('recorded_at',sql)
        self.assertNotIn('FROM sync_logs',sql)
    async def test_all_sources_scoped_and_directional(self):
        sql=await history.sources(Fake())
        for value in ['supplier:','batch:','review:','outbound:','inbound','outbound','store_domain']:
            self.assertIn(value,sql)
        self.assertIn("AT TIME ZONE 'UTC'",sql)
    async def test_search_is_bound_not_interpolated(self):
        conn=Fake();search="x' OR TRUE --"
        with patch.object(deps,'pool',Pool(conn)):
            result=await history.history(direction='outbound',supplier_id='supplier-a',platform='lightspeed',state='failed',operation='',date_from='',date_to='',search=search,page=3,user={})
        query,args=next((sql,args) for sql,args in conn.calls if 'LIMIT 50 OFFSET $9' in sql)
        self.assertNotIn(search,query)
        self.assertEqual(args[-1],100)
        self.assertEqual(args[-2],'%'+search+'%')
        self.assertEqual(result['total'],1)
    async def test_invalid_dates_fail_before_database(self):
        with self.assertRaises(history.HTTPException) as error:
            await history.history(date_from='invalid',date_to='',user={})
        self.assertEqual(error.exception.status_code,400)
    async def test_reversed_dates_fail(self):
        with self.assertRaises(history.HTTPException):
            await history.history(date_from='2026-11-07',date_to='2026-11-06',user={})
    async def test_item_results_decode_and_paginate(self):
        conn=Fake()
        with patch.object(deps,'pool',Pool(conn)):
            result=await history.detail('batch:example',page=2,search='SKU',state='pending',user={})
        self.assertEqual(result['items'][0]['details_result'],{'synced':1})
        self.assertTrue(any(args[-1]==50 for sql,args in conn.calls if 'OFFSET $4' in sql))
    async def test_unknown_event_returns_404(self):
        with self.assertRaises(history.HTTPException):await history.detail('invalid',user={})
    def test_status_normalization(self):
        for raw,expected in [('pending','queued'),('images_pending','completed_with_issues'),('needs_review','completed_with_issues'),('error','failed'),('running','running')]:
            self.assertEqual(history.status(raw),expected)

class OutboundTests(unittest.IsolatedAsyncioTestCase):
    async def test_decorator_preserves_signature_response_and_scope(self):
        conn=Fake();response={'total':3,'synced':2,'failed':1}
        async def export(data=None,user=None):return response
        wrapped=outbound.record('export')(export)
        self.assertEqual(inspect.signature(wrapped),inspect.signature(export))
        with patch.object(deps,'pool',Pool(conn)):
            self.assertIs(await wrapped(data={'product_ids':['p1'],'token':'DO-NOT-STORE'},user={}),response)
        saved=' '.join(str(args) for sql,args in conn.calls)
        self.assertNotIn('DO-NOT-STORE',saved)
        self.assertIn('completed_with_issues',saved)
        self.assertIn('supplier-a',saved)
    async def test_failure_remains_failure(self):
        conn=Fake()
        async def fail(user=None):raise ValueError('bounded failure')
        with patch.object(deps,'pool',Pool(conn)):
            with self.assertRaisesRegex(ValueError,'bounded failure'):await outbound.record('export')(fail)(user={})
        self.assertTrue(any("status='failed'" in sql for sql,args in conn.calls))
    def test_missing_counts_are_not_fabricated(self):
        self.assertEqual(outbound.outcome({'message':'nothing recorded'}),('completed',None,None,None))
        self.assertEqual(outbound.outcome({'products_to_push':4,'synced':2}),('completed_with_issues',4,2,2))
        self.assertEqual(outbound.outcome({'success':False}),('failed',None,None,None))

if __name__=='__main__':unittest.main()
