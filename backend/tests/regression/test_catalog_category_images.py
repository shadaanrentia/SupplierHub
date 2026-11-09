"""Offline category, image association and catalogue visibility regressions."""
import ast
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'backend'))
from category_tree import category_tree,category_choices
from category_scope import category_labels,in_category,destination_labels
from media_links import colour_key,resolved_links,associate_sanmar_images,matcher_runtime
from catalogue_labels import full_colour_name

APPAREL={'Accessories':['Aprons','Bags','Blankets','Towels'],
 'Bottoms':['Activewear Bottoms','Coveralls','Loungewear','Pants','Shorts','Sweatpants & Joggers'],
 'Gender':['Infants','Mens & Unisex','Toddlers','Womens','Youth'],
 'Headwear':['Beanies','Bucket Hats','Hats','Visors'],
 'Outerwear':['Jackets','Vests'],
 'Tops':['Activewear Tops','Polos & Knits','Sweatshirts & Fleece','T-Shirts','Woven Shirts']}
def fixture():
 rows=[{'id':'apparel','name':'Apparel','parent_category_id':None}]
 for parent,leaves in APPAREL.items():
  rows.append({'id':parent,'name':parent,'parent_category_id':'apparel'})
  rows.extend({'id':leaf,'name':leaf,'parent_category_id':parent} for leaf in leaves)
 return rows

class Categories(unittest.TestCase):
 def test_all_supplied_paths_are_preserved(self):
  tree=category_tree(fixture());self.assertEqual(len(tree),33)
  leaves=[r for r in tree if r['leaf_category']];self.assertEqual(len(leaves),26)
  self.assertEqual({r['path'] for r in leaves},{f'Apparel > {p} > {l}' for p,ls in APPAREL.items() for l in ls})
 def test_nested_and_json_envelopes(self):
  rows={'data':{'categories':[{'id':'a','name':'Apparel','children':[{'id':'b','name':'Tops','children':[{'id':'c','name':'T-Shirts'}]}]}]}}
  self.assertEqual(category_labels(json.dumps(rows))['c'],'Apparel > Tops > T-Shirts')
 def test_api_path_recovers_real_ancestor_ids_and_keeps_leaf(self):
  rows=[{'id':'c','name':'T-Shirts','category_path':[{'id':'a','name':'Apparel'},{'id':'b','name':'Tops'}]}]
  labels=category_labels(rows);self.assertEqual(labels['c'],'Apparel > Tops > T-Shirts');self.assertEqual(len(labels),3)
 def test_path_including_self_is_not_duplicated(self):
  rows=[{'id':'c','name':'T-Shirts','category_path':[{'id':'a','name':'Apparel'},{'id':'c','name':'T-Shirts'}]}]
  self.assertEqual(category_labels(rows)['c'],'Apparel > T-Shirts')
 def test_incomplete_cycles_never_become_valid_destinations(self):
  for rows in [[{'id':'a','name':'A','parent_id':'missing'}],[{'id':'a','name':'A','parent_id':'b'},{'id':'b','name':'B','parent_id':'a'}]]:
   self.assertEqual(category_labels(rows),{})
 def test_stale_ids_are_one_unmapped_bucket_not_fake_categories(self):
  products=[{'id':'p1'},{'id':'p2'},{'id':'p3'},{'id':'p4'}]
  states={'p1':{'mapped_lightspeed_category_id':'T-Shirts'},'p2':{'mapped_lightspeed_category_id':'obsolete'},'p3':{},'p4':{'excluded_from_queue':True}}
  choices=category_choices(fixture(),products,states)
  self.assertEqual(len(choices),27)
  self.assertFalse(any(r['category_id']=='obsolete' for r in choices))
  self.assertEqual(next(r for r in choices if r['category_id']=='T-Shirts')['product_count'],1)
  self.assertEqual(next(r for r in choices if r['category_id']=='__unmapped__')['product_count'],2)
 def test_unmapped_scope_is_distinct_from_all_products(self):
  self.assertTrue(in_category({'mapped_lightspeed_category_id':'old','category_available':False},'__unmapped__'))
  self.assertFalse(in_category({'mapped_lightspeed_category_id':'new','category_available':True},'__unmapped__'))
 def test_empty_cache_never_invents_a_remote_id(self):
  choices=category_choices([], [{'id':'p'}], {'p':{'mapped_lightspeed_category_id':'old'}})
  self.assertEqual([r['category_id'] for r in choices],['__unmapped__'])

 def test_destination_labels_only_accept_current_final_categories(self):
  import asyncio
  class Conn:
   async def fetchval(self,sql,*args):return 'table' if 'to_regclass' in sql else fixture()
  labels=asyncio.run(destination_labels(Conn()))
  self.assertEqual(len(labels),26);self.assertNotIn('Apparel',labels);self.assertNotIn('Tops',labels)
  self.assertEqual(labels['Woven Shirts'],'Apparel > Tops > Woven Shirts')

class Images(unittest.TestCase):
 def test_generic_leading_markers_for_every_colour(self):
  for colour in ['Ivy Green','Verry','Silver','Orange','Black / White','Athletic Grey']:
   self.assertEqual(colour_key(' ~ ~'+colour),colour_key(colour))
   self.assertEqual(full_colour_name(' ~'+colour),full_colour_name(colour))
 def test_internal_markers_and_different_colours_do_not_collapse(self):
  self.assertNotEqual(colour_key('Blue~Green'),colour_key('BlueGreen'))
  self.assertNotEqual(colour_key('Ivy Green'),colour_key('Green'))
 def test_explicit_colour_links_expand_only_to_same_colour(self):
  variants=[{'variant_sku':'1','color':'~Ivy Green'},{'variant_sku':'2','color':'~Ivy Green'},{'variant_sku':'3','color':'~Verry'}]
  _,parts,linked=resolved_links({'source_color':'Ivy Green'},variants)
  self.assertTrue(linked);self.assertEqual(parts,['1','2'])
 def test_conflicting_part_colour_evidence_is_still_blocked(self):
  variants=[{'variant_sku':'1','color':'~Ivy Green'}]
  self.assertEqual(resolved_links({'source_color':'Verry','source_part_ids':['1']},variants),('',[],False))
 def test_exact_sanmar_filename_recovery_uses_generic_marker(self):
  variants=[{'variant_sku':'a','color':'~Ivy Green'},{'variant_sku':'b','color':'~Verry'}]
  images=[{'url':'https://media.sanmarcanada.com/catalog/product/eb539_ivygreen_front.jpg'}]
  result=associate_sanmar_images(images,variants,'EB539')
  self.assertEqual(result[0]['source_part_ids'],['a']);self.assertNotIn('source_part_ids',images[0])
 def test_other_styles_hosts_and_ambiguous_names_are_not_guessed(self):
  variants=[{'variant_sku':'a','color':'~Ivy Green'}]
  for url in ['https://untrusted.test/catalog/product/eb539_ivygreen.jpg','https://media.sanmarcanada.com/catalog/product/OTHER_ivygreen.jpg']:
   self.assertNotIn('source_part_ids',associate_sanmar_images([{'url':url}],variants,'EB539')[0])
 def test_real_member_matcher_uses_generic_colour_key(self):
  module=ast.parse((ROOT/'backend/single_family.py').read_text())
  fn=next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=='matched_images')
  ns={'json':json,'sku':lambda v:str(v['variant_sku']).lower()}
  exec(compile(ast.Module(body=[fn],type_ignores=[]),'member-matcher','exec'),ns)
  self.assertEqual(len(ns['matched_images']({'variant_sku':'a','color':'~Verry'},[{'source_color':'Verry'}])),1)
  self.assertEqual(ns['matched_images']({'variant_sku':'a','color':'~Verry'},[{'source_color':'Ivy Green'}]),[])
 def test_matcher_version_identifies_the_new_code(self):
  self.assertEqual(matcher_runtime()['version'],'generic-colour-prefix-v4')

class Catalogue(unittest.TestCase):
 def test_only_explicit_filters_affect_catalogue_query(self):
  from catalog_filters import catalog_filter
  where,args,_=catalog_filter({})
  self.assertEqual(where,'1=1');self.assertEqual(args,[])
  where,args,_=catalog_filter({'supplier_id':'supplier','category':'TEES','brand':'ATC'})
  self.assertIn('p.supplier_id=$1',where);self.assertIn('BTRIM(p.category)=$2',where)
  self.assertEqual(args,['supplier','TEES','ATC'])
class LiveCategoryParser(unittest.TestCase):
 def parse(self,responses):
  tree=ast.parse((ROOT/'backend/lightspeed_service.py').read_text())
  cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and any(isinstance(f,ast.FunctionDef) and f.name=='get_categories' for f in n.body))
  method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='get_categories')
  ns={'logger':types.SimpleNamespace(warning=lambda *args:None)}
  exec(compile(ast.Module(body=[method],type_ignores=[]),'category-reader','exec'),ns)
  calls=[]
  def read(endpoint,params):calls.append((endpoint,params));return responses.pop(0)
  result=ns['get_categories'](types.SimpleNamespace(mock_mode=False,_get=read))
  return result,calls
 def test_nested_paginated_api_rows_make_complete_hierarchy(self):
  rows=fixture();result,calls=self.parse([{'data':{'categories':rows[:10],'page_info':{'has_next':True,'last_seen':'cursor'}}},{'data':rows[10:],'page_info':{'has_next':False}}])
  self.assertTrue(result['success']);self.assertEqual(len(result['categories']),33)
  self.assertEqual(calls[1][1]['after'],'cursor')
  self.assertEqual(category_labels(result['categories'])['Woven Shirts'],'Apparel > Tops > Woven Shirts')
 def test_incomplete_response_does_not_claim_success(self):
  result,_=self.parse([{'data':[{'id':'leaf','name':'Leaf','parent_category_id':'absent'}]}])
  self.assertFalse(result['success']);self.assertEqual(result['categories'],[])

class CatalogueDatabase(unittest.IsolatedAsyncioTestCase):
 async def test_unfiltered_listing_includes_missing_price_images_and_inactive_rows(self):
  import sqlite3
  from contextlib import asynccontextmanager
  db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
  db.executescript("""CREATE TABLE products(id TEXT,product_name TEXT,supplier_sku TEXT,supplier_id TEXT,
   category TEXT,brand TEXT,base_price REAL,is_active BOOLEAN,created_at TEXT,selected_for_odoo BOOLEAN,odoo_sync_status TEXT);
   CREATE TABLE suppliers(id TEXT,supplier_name TEXT);
   CREATE TABLE product_variants(id TEXT,product_id TEXT,inventory INTEGER);
   CREATE TABLE product_media(id TEXT,product_id TEXT,media_type TEXT,url TEXT,image_base64 TEXT,is_primary BOOLEAN,created_at TEXT);
   INSERT INTO suppliers VALUES('s','SanMar');
   INSERT INTO products VALUES('one','Normal','ONE','s','TEES','ATC',9,1,'2026-01-01',0,'pending');
   INSERT INTO products VALUES('two','Missing price','TWO','s','TEES','ATC',NULL,1,'2026-01-01',0,'pending');
   INSERT INTO products VALUES('three','Zero price','THREE','s','TEES','ATC',0,1,'2026-01-01',0,'pending');
   INSERT INTO products VALUES('four','Inactive','FOUR','s','TEES','ATC',7,0,'2026-01-01',0,'pending');""")
  class Conn:
   async def fetchval(self,sql,*args):return db.execute(sql.replace('ILIKE','LIKE'),{str(i+1):v for i,v in enumerate(args)}).fetchone()[0]
   async def fetch(self,sql,*args):return [dict(r) for r in db.execute(sql.replace('NULL::text','NULL').replace('ILIKE','LIKE'),{str(i+1):v for i,v in enumerate(args)})]
  class Pool:
   @asynccontextmanager
   async def acquire(self):yield Conn()
  module=ast.parse((ROOT/'backend/routes/products.py').read_text())
  fn=next(n for n in module.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='get_products')
  fn.decorator_list=[];fn.returns=None
  for arg in fn.args.args:arg.annotation=None
  ns={'deps':types.SimpleNamespace(pool=Pool()),'Query':lambda default,**kw:default,'Depends':lambda fn:None,
      'get_current_user':lambda:None,'row_to_dict':dict,'display_product_labels':lambda row:row}
  exec(compile(ast.Module(body=[fn],type_ignores=[]),'catalogue-list','exec'),ns)
  response=await ns['get_products'](page=1,limit=50,user={})
  self.assertEqual(response['total'],4)
  self.assertEqual({p['id'] for p in response['products']},{'one','two','three','four'})
  self.assertTrue(all(p['image'] is None for p in response['products']))
  filtered=await ns['get_products'](search='Inactive',page=1,limit=50,user={})
  self.assertEqual([p['id'] for p in filtered['products']],['four'])
  paged=await ns['get_products'](page=2,limit=2,user={})
  self.assertEqual(paged['total'],4);self.assertEqual(len(paged['products']),2)
  db.close()

if __name__=='__main__':unittest.main()
