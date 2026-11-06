"""Offline queue, category scope and two-stage export regressions."""
import ast
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace,ModuleType
from unittest.mock import patch
from uuid import UUID,uuid4
import sys
import unittest
ROOT=Path(__file__).resolve().parent/'backend'

def extract(file,names,ns):
    tree=ast.parse((ROOT/file).read_text(encoding='utf-8'))
    body=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
    for n in body:n.decorator_list=[]
    exec(compile(ast.Module(body=body,type_ignores=[]),file,'exec'),ns)
    return ns

def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'))
    loaded=importlib.util.module_from_spec(spec);spec.loader.exec_module(loaded);return loaded
scope=module('category_scope');media=module('media_links')
class Pool:
    def __init__(self,conn):self.conn=conn
    @asynccontextmanager
    async def acquire(self):yield self.conn
class HTTPError(Exception):
    def __init__(self,status,detail):self.status_code=status;self.detail=detail

class QueueTests(unittest.IsolatedAsyncioTestCase):
    def setup_queue(self):
        class Conn:
            def __init__(self):self.saved=None;self.active=None;self.inserts=0
            @asynccontextmanager
            async def transaction(self):yield
            async def fetchval(self,sql,*args):
                if 'lightspeed_store_id' in sql:return 'store'
                if 'pg_try_advisory' in sql:return True
                return self.active
            async def fetchrow(self,sql,*args):return self.saved
            async def execute(self,sql,*args):
                self.inserts+=1
                self.saved={'id':args[0],'selection':args[3],'status':'queued','total':0,'stage':'planning'}
        conn=Conn()
        ns=extract('lightspeed_jobs.py',{'enqueue','domain','public','decoded'},{'deps':SimpleNamespace(pool=Pool(conn)),
           'UUID':UUID,'new_id':lambda:str(uuid4()),'json':json,'HTTPException':HTTPError,
           'Depends':lambda fn:None,'get_current_user':None})
        return conn,ns['enqueue']
    async def test_sync_all_returns_before_planning_or_external_io(self):
        conn,enqueue=self.setup_queue()
        result=await enqueue({'sync_all':True,'category_id':'polos'},{})
        self.assertEqual(result['status'],'queued');self.assertEqual(result['total'],0)
        self.assertEqual(json.loads(conn.saved['selection'])['category_id'],'polos')
        self.assertEqual(conn.inserts,1)
    async def test_same_request_key_does_not_enqueue_twice(self):
        conn,enqueue=self.setup_queue();body={'sync_all':True,'request_id':str(uuid4())}
        first=await enqueue(body,{});second=await enqueue(body,{})
        self.assertEqual(first['id'],second['id']);self.assertEqual(conn.inserts,1)
    async def test_another_active_batch_is_reported(self):
        conn,enqueue=self.setup_queue();conn.active='other'
        with self.assertRaises(HTTPError) as exc:await enqueue({'sync_all':True},{})
        self.assertEqual(exc.exception.status_code,409);self.assertEqual(exc.exception.detail['job_id'],'other')
    async def test_invalid_category_type_rejected(self):
        conn,enqueue=self.setup_queue()
        with self.assertRaises(HTTPError):await enqueue({'sync_all':True,'category_id':['x']},{})
        self.assertEqual(conn.inserts,0)

class StageTests(unittest.IsolatedAsyncioTestCase):
    async def sample(self,core_failure=None,image_failure=None):
        events=[];items=[{'product_id':str(i),'sku':'sku'+str(i)} for i in range(3)];states={str(i):{} for i in range(3)}
        class Conn:
            async def execute(self,sql,*args):events.append(('sql',sql,args))
            async def fetch(self,sql,*args):return [i for i in items if states[i['product_id']].get('details')=='completed'] if "details_status='completed'" in sql else items
            async def fetchval(self,*args):return sum(v.get('details')!='completed' or v.get('images')!='completed' for v in states.values())
        async def plan(batch):events.append(('planning',));return items
        async def service(batch):return None
        async def result(batch,pid,stage,status,data):states[pid][stage]=status
        async def details(batch,item):
            events.append(('details',item['product_id']));states[item['product_id']]['details']='failed' if item['product_id']==core_failure else 'completed'
        async def images(batch,item):
            events.append(('images',item['product_id']))
            if item['product_id']==image_failure:raise ValueError('SSL disconnected')
            states[item['product_id']]['images']='completed'
        async def sleep(_):pass
        ns=extract('lightspeed_jobs.py',{'run_batch'},{'deps':SimpleNamespace(pool=Pool(Conn())),
            'plan':plan,'current_service':service,'item_result':result,'details_stage':details,'images_stage':images,
            'asyncio':SimpleNamespace(sleep=sleep),'log':SimpleNamespace(exception=lambda *args:None)})
        await ns['run_batch']({'id':'batch'})
        return events,states
    async def test_all_details_finish_before_any_images(self):
        events,_=await self.sample()
        self.assertEqual([e[0] for e in events if e[0] in ('details','images')],['details']*3+['images']*3)
    async def test_core_failure_excludes_only_affected_product_images(self):
        events,states=await self.sample(core_failure='1')
        self.assertNotIn(('images','1'),events);self.assertIn(('images','2'),events)
    async def test_image_error_keeps_details_and_continues(self):
        events,states=await self.sample(image_failure='0')
        self.assertEqual(states['0'],{'details':'completed','images':'pending'})
        self.assertIn(('images','2'),events)
        self.assertEqual([e for e in events if e[0]=='sql'][-1][2][-1],'completed_with_issues')
    async def test_successful_batch_finishes_completed(self):
        events,_=await self.sample()
        self.assertEqual([e for e in events if e[0]=='sql'][-1][2][-1],'completed')
    async def test_deferred_repair_has_no_image_io(self):
        ns=extract('single_family.py',{'repair_assets'},{'defer_images':ContextVar('test',default=True)})
        result=await ns['repair_assets'](None,'destination',[])
        self.assertTrue(result['deferred']);self.assertEqual(result['failed'],0)
    async def test_context_reset_on_export_failure(self):
        flag=ContextVar('test',default=False);events=[]
        route=ModuleType('routes.preprocessing')
        async def export(*args,**kwargs):
            self.assertTrue(flag.get());raise ValueError('Invalid inventory')
        route.sync_products_now=export
        async def result(*args):events.append(args)
        ns=extract('lightspeed_jobs.py',{'details_stage'},{'defer_images':flag,'decoded':lambda x:x,
            'item_result':result,'log':SimpleNamespace(exception=lambda *args:None)})
        with patch.dict(sys.modules,{'routes':ModuleType('routes'),'routes.preprocessing':route}):
            await ns['details_stage']({'id':'b','selection':{}},{'product_id':'p','sku':'sku'})
        self.assertFalse(flag.get());self.assertEqual(events[0][3],'failed')

class CategoryTests(unittest.TestCase):
    def test_exact_destination_filter(self):
        self.assertTrue(scope.in_category({'mapped_lightspeed_category_id':'polo'},'polo'))
        self.assertFalse(scope.in_category({'mapped_lightspeed_category_id':'tee'},'polo'))
        self.assertFalse(scope.in_category({'mapped_lightspeed_category_id':None},'polo'))
        self.assertTrue(scope.in_category({},None))
    def test_nested_category_path(self):
        labels=scope.category_labels([{'id':'a','name':'Apparel','children':[{'id':'p','name':'Polos'}]}])
        self.assertEqual(labels['p'],'Apparel > Polos')
    def test_flat_category_path(self):
        labels=scope.category_labels([{'id':'p','name':'Polos','parent_id':'a'},{'id':'a','name':'Apparel'}])
        self.assertEqual(labels['p'],'Apparel > Polos')
    def test_cycles_terminate(self):
        self.assertTrue(scope.category_labels([{'id':'a','name':'A','parent_id':'b'},{'id':'b','name':'B','parent_id':'a'}]))
    def test_all_supplier_categories_are_retained(self):
        products=[{'id':'1','supplier_id':'s','category':'SPORT SHIRTS'},{'id':'2','supplier_id':'s','category':'KNITS'}]
        states={key:{'mapped_lightspeed_category_id':'p','mapped_category_name':'Tops > Polos'} for key in ('1','2')}
        row=scope.category_rows(products,states,{'p':'Apparel > Polos'})[('s','p')]
        self.assertEqual(row['category_name'],'Apparel > Polos')
        self.assertEqual(row['supplier_categories'],['KNITS','SPORT SHIRTS']);self.assertEqual(row['product_count'],2)
    def test_same_destination_keeps_suppliers_separate(self):
        products=[{'id':'1','supplier_id':'s1'},{'id':'2','supplier_id':'s2'}]
        states={key:{'mapped_lightspeed_category_id':'p'} for key in ('1','2')}
        self.assertEqual(len(scope.category_rows(products,states,{'p':'Polos'})),2)

class MatchingTests(unittest.TestCase):
    def test_multicolour_abbreviations(self):
        for left,right in [('TrueNavy/Whit','True Navy/White'),('Carolina/Wht','Carolina/White'),('Forest/Wht','Forest/White'),('TrueRoy/White','True Royal/White')]:
            with self.subTest(left=left):self.assertEqual(media.sanmar_colour_alias(left),media.sanmar_colour_alias(right))
    def test_two_tone_is_not_solid(self):
        self.assertNotEqual(media.sanmar_colour_alias('Black/White'),media.sanmar_colour_alias('Black'))
    def test_verified_composite_link_expands_only_matching_sizes(self):
        variants=[{'variant_sku':'a','color':'TrueNavy/Whit','inventory':0},{'variant_sku':'b','color':'True Navy/White','inventory':2},{'variant_sku':'solid','color':'True Navy'}]
        result=media.associate_sanmar_images([{'source_part_ids':['a']}],variants,'Y3524')[0]
        self.assertEqual(set(result['source_part_ids']),{'a','b'})

class ReadinessTests(unittest.TestCase):
    def state(self,category='p',stock=3):
        ns=extract('product_readiness.py',{'evaluate'},{'sort_variants':lambda x:x,'eligible_variants':lambda x:x,
            'skip_sku':lambda x:False,'validate_prices':lambda *args:None,'LIMIT':200,'math':__import__('math')})
        return ns['evaluate']({'product_name':'P','supplier_sku':'SKU'},[{'id':'a','inventory':stock}],[],[],category)
    def test_images_do_not_block_details(self):self.assertTrue(self.state()['is_valid'])
    def test_category_validation_remains(self):self.assertFalse(self.state(category=None)['is_valid'])
    def test_inventory_validation_remains(self):self.assertFalse(self.state(stock=-1)['is_valid'])

if __name__=='__main__':unittest.main()
