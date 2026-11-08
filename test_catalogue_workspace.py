"""Offline catalogue/filter/dashboard/review/export regressions; no remote writes."""
import ast
import asyncio
from contextlib import asynccontextmanager
from datetime import date
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import sys
import types
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'backend'))
from catalog_filters import catalog_filter

class HTTPException(Exception):
 def __init__(self,status_code,detail):self.status_code=status_code;self.detail=detail
class Conn:
 def __init__(self):
  self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.queries=[];self.transactions=[]
  self.db.create_function('BTRIM',1,lambda v:str(v).strip() if v is not None else None)
  self.db.create_function('REGEXP_REPLACE',4,lambda text,pattern,value,flags:re.sub(r'^[~\s]+','',text))
  self.db.executescript('''CREATE TABLE suppliers(id TEXT,supplier_name TEXT,last_sync TEXT);
   CREATE TABLE products(id TEXT,product_name TEXT,supplier_sku TEXT,supplier_id TEXT,category TEXT,brand TEXT,
     base_price REAL,currency TEXT,created_at TEXT,updated_at TEXT,selected_for_odoo BOOLEAN,odoo_sync_status TEXT);
   CREATE TABLE product_variants(id TEXT,product_id TEXT,color TEXT,size TEXT,inventory INTEGER,is_active BOOLEAN);
   CREATE TABLE product_media(id TEXT,product_id TEXT,media_type TEXT,url TEXT,image_base64 TEXT,is_primary BOOLEAN,created_at TEXT);
   CREATE TABLE settings(id TEXT,markup_percentage REAL);
   INSERT INTO suppliers VALUES('s1','SanMar','2026-11-09 01:00:00'),('s2','Other supplier',NULL);
   INSERT INTO settings VALUES('system_settings',40);''')
  rows=[('a','None category','A','s1',None,None,None),('b','Blank category','B','s1','   ','ATC',0),
        ('c','Named uncategorized','C','s1','Uncategorized',None,10),('d','Tee','D','s1','Tops','ATC',20),
        ('e','Bag','E','s2','Bags','Maker',15),('f','Orphan','F','missing','Tops',None,30)]
  self.db.executemany('INSERT INTO products VALUES(?,?,?,?,?,?,?,\'CAD\',\'2026-11-01\',\'2026-11-09\',0,\'pending\')',rows)
  for pid,count,colour,size,stock in [('b',1,'~Ivy Green','Small',0),('c',200,'Black','M',4),('d',201,'White','L',0),('e',1,'Red','One size',None)]:
   self.db.executemany('INSERT INTO product_variants VALUES(?,?,?,?,?,1)',[(pid+str(i),pid,colour,size,stock) for i in range(count)])
  self.db.executescript("INSERT INTO product_media VALUES('im1','d','image','https://fixture.test/one.jpg','',1,'2026-01-01'); INSERT INTO product_media VALUES('im2','e','image','','saved-image',1,'2026-01-01');")
 def execute(self,sql,args):
  self.queries.append((sql,args));sql=sql.replace('ILIKE','LIKE').replace('NULL::text','NULL')
  return self.db.execute(sql,{str(i+1):value for i,value in enumerate(args)})
 async def fetchval(self,sql,*args):return self.execute(sql,args).fetchone()[0]
 async def fetchrow(self,sql,*args):
  row=self.execute(sql,args).fetchone();return dict(row) if row else None
 async def fetch(self,sql,*args):return [dict(row) for row in self.execute(sql,args)]
 @asynccontextmanager
 async def transaction(self,**kwargs):self.transactions.append(kwargs);yield self
class Pool:
 def __init__(self,conn):self.conn=conn
 @asynccontextmanager
 async def acquire(self):yield self.conn

def functions(path,names,ns):
 tree=ast.parse((ROOT/path).read_text())
 selected=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
 for node in selected:
  node.decorator_list=[];node.returns=None
  for arg in node.args.args:arg.annotation=None
 exec(compile(ast.Module(body=selected,type_ignores=[]),str(path),'exec'),ns)
 return ns

def namespace(conn):return {'deps':types.SimpleNamespace(pool=Pool(conn)),'Query':lambda default,**kw:default,
 'Depends':lambda fn:None,'get_current_user':lambda:None,'HTTPException':HTTPException,'row_to_dict':dict,
 'display_product_labels':dict,'asyncio':asyncio,'public_state':dict,'export_name':lambda name,sku:name,'LIMIT':200}

class Filters(unittest.TestCase):
 def setUp(self):self.conn=Conn()
 def tearDown(self):self.conn.db.close()
 def ids(self,**values):
  where,args,order=catalog_filter(values)
  return {r['id'] for r in self.conn.execute('SELECT p.id FROM products p WHERE '+where+' ORDER BY '+order,args)}
 def test_default_has_no_exclusions(self):self.assertEqual(self.ids(),set('abcdef'))
 def test_uncategorized_covers_null_blank_and_literal(self):self.assertEqual(self.ids(category='__uncategorized__'),set('abc'))
 def test_unknown_brand_and_supplier(self):self.assertEqual(self.ids(brand='__unbranded__'),set('acf'));self.assertEqual(self.ids(supplier_id='__unassigned__'),{'f'})
 def test_images_and_price_quality(self):self.assertEqual(self.ids(images='with'),set('de'));self.assertEqual(self.ids(pricing='missing'),set('ab'))
 def test_inclusive_price_range_and_variant_boundaries(self):self.assertEqual(self.ids(price_min=10,price_max=20),set('cde'));self.assertEqual(self.ids(variants_min=200,variants_max=200),{'c'})
 def test_stock_distinguishes_unknown_from_zero(self):self.assertEqual(self.ids(stock='in_stock'),{'c'});self.assertEqual(self.ids(stock='out_of_stock'),set('bd'));self.assertEqual(self.ids(stock='unknown'),set('aef'))
 def test_colour_marker_and_size(self):self.assertEqual(self.ids(colour='Ivy Green',size='small'),{'b'})
 def test_explicit_filters_combine(self):self.assertEqual(self.ids(supplier_id='s1',category='Tops',brand='ATC',images='with',variants_min=201),{'d'})
 def test_search_is_bound_as_data(self):self.assertEqual(self.ids(search="' OR 1=1 --"),set())
 def test_invalid_ranges_and_sort_fail(self):
  for values in [{'price_min':20,'price_max':2},{'variants_min':1.5},{'price_max':float('inf')},{'sort':'DROP TABLE products'},{'updated_from':'2026-11-10','updated_to':'2026-11-01'},{'updated_to':'bad'}]:
   with self.assertRaises(ValueError):catalog_filter(values)
 def test_dates_are_typed_and_inclusive_end(self):
  where,args,_=catalog_filter({'updated_from':'2026-11-01','updated_to':'2026-11-09'})
  self.assertEqual(args,[date(2026,11,1),date(2026,11,9)]);self.assertIn('$2::date+1',where)
 def test_postgres_syntax_for_complex_filter(self):
  try:from pglast import parse_sql
  except ImportError:self.skipTest('Optional PostgreSQL parser is not installed')
  where,args,order=catalog_filter({'supplier_id':'s1','category':'__uncategorized__','brand':'ATC','images':'without','colour':'Ivy Green','size':'S','updated_from':'2026-11-01','updated_to':'2026-11-09','variants_min':0,'sort':'variants_desc'})
  parse_sql('SELECT p.id FROM products p WHERE '+where+' ORDER BY '+order)

class Routes(unittest.IsolatedAsyncioTestCase):
 def setUp(self):self.conn=Conn();self.ns=namespace(self.conn)
 def tearDown(self):self.conn.db.close()
 async def test_product_list_filters_and_counts_match(self):
  functions('backend/routes/products.py',['get_products'],self.ns)
  result=await self.ns['get_products'](category='__uncategorized__',page=1,limit=2,user={})
  self.assertEqual(result['total'],3);self.assertEqual(len(result['products']),2)
  result=await self.ns['get_products'](page=1,limit=50,images='without',variants_min=0,user={})
  self.assertEqual({p['id'] for p in result['products']},set('abcf'))
 async def test_facets_include_uncategorized_and_unbranded(self):
  functions('backend/routes/products.py',['get_categories','get_brands','filter_options'],self.ns)
  result=await self.ns['get_categories'](supplier_id='s1',user={});self.assertEqual(result['categories'],['Tops','Uncategorized'])
  result=await self.ns['get_brands'](supplier_id='s1',category='__uncategorized__',user={});self.assertEqual(result['brands'],['ATC','Unbranded'])
  result=await self.ns['filter_options'](supplier_id='s1',category=None,brand=None,user={});self.assertIn('Ivy Green',result['colours']);self.assertNotIn('~Ivy Green',result['colours']);self.assertTrue(result['unassigned_supplier'])
 async def test_dashboard_is_aggregate_and_read_only(self):
  functions('backend/routes/dashboard.py',['get_dashboard_stats'],self.ns)
  self.ns.update(datetime=__import__('datetime').datetime,timezone=__import__('datetime').timezone)
  result=await self.ns['get_dashboard_stats'](user={})
  self.assertEqual(result['total_products'],6);self.assertEqual(result['total_variants'],403)
  self.assertEqual(result['total_categories'],2);self.assertEqual(result['with_images'],2)
  self.assertEqual(sum(row['products'] for row in result['supplier_catalogues']),6)
  self.assertTrue(self.conn.transactions[0]['readonly'])
  source=(ROOT/'backend/routes/dashboard.py').read_text();self.assertNotIn('load_readiness',source);self.assertNotIn('SELECT *',source)
  self.assertTrue(all(not re.search(r'\b(INSERT|UPDATE|DELETE|DROP)\b',sql,re.I) for sql,args in self.conn.queries))
 async def test_supplier_export_ignores_page_and_other_filters(self):
  try:from openpyxl import load_workbook
  except ImportError:self.skipTest('openpyxl is required by the application export')
  from io import BytesIO
  rules=types.ModuleType('pricing_rules');readiness=types.ModuleType('product_readiness')
  async def ensure():pass
  async def policies(conn):return {}
  async def states(conn,batch,include_assets=True):
   self.assertFalse(include_assets);return {p['id']:{'mapped_lightspeed_category_id':None,'variants':[]} for p in batch}
  rules.ensure_pricing_schema=ensure;rules.category_policies=policies;rules.apply_category_policy=lambda p,*args:p
  rules.pricing_policy=lambda *args:{'markup':40};rules.price_for=lambda cost,*args:cost*1.4
  readiness.load_readiness=states
  class Response:
   def __init__(self,content,**kw):self.content=content
  responses=types.ModuleType('fastapi.responses');responses.StreamingResponse=Response
  functions('backend/routes/products.py',['build_supplier_workbook','export_supplier_products'],self.ns)
  with patch.dict(sys.modules,{'pricing_rules':rules,'product_readiness':readiness,'fastapi.responses':responses}):
   result=await self.ns['export_supplier_products']('s1',user={})
   book=load_workbook(BytesIO(result.content.getvalue()));rows=list(book.active.values)
   self.assertEqual({row[2] for row in rows[1:]},set('ABCD'));self.assertEqual(len(rows),5)
   for supplier in ['','  ','all','__unassigned__']:
    with self.assertRaises(HTTPException):await self.ns['export_supplier_products'](supplier,user={})

class Review(unittest.IsolatedAsyncioTestCase):
 async def test_supplier_is_bound_before_readiness_and_200_is_included(self):
  conn=Conn();ns=namespace(conn);batches=[]
  # This method returns only the selected supplier, like the real SQL predicate.
  async def fetch(sql,*args):
   self.assertEqual(args,('%%','s1',True))
   self.assertIn('p.supplier_id=$2',sql)
   return [{'id':'200','product_name':'Boundary','supplier_sku':'200'},{'id':'199','product_name':'Small','supplier_sku':'199'},{'id':'201','product_name':'Large','supplier_sku':'201'}]
  async def states(conn,batch,include_assets=True):
   self.assertFalse(include_assets);self.assertLessEqual(len(batch),100);batches.extend(batch)
   return {p['id']:{'variants_count':int(p['id']),'is_valid':True,'previous_export_failed':False,'status':'ready','images_count':0,'excluded_from_queue':False} for p in batch}
  conn.fetch=fetch;ns['load_readiness']=states
  functions('backend/routes/export_review.py',['_review_listing'],ns)
  result=await ns['_review_listing']('',True,False,1,'s1')
  self.assertEqual([p['id'] for p in result['products']],['200','201']);self.assertEqual(result['total'],2)
  conn.db.close()
 def test_review_defaults_are_200_plus_without_hidden_issue_filter(self):
  tree=ast.parse((ROOT/'backend/routes/export_review.py').read_text());fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='products')
  values={arg.arg:default for arg,default in zip(fn.args.args[-len(fn.args.defaults):],fn.args.defaults)}
  self.assertTrue(ast.literal_eval(values['oversized']));self.assertFalse(ast.literal_eval(values['issues_only']))

if __name__=='__main__':unittest.main()
