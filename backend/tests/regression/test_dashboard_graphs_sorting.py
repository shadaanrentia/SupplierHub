"""Saved catalogue sorting regressions; all fixtures are local."""
import unittest,asyncio
from test_catalogue_workspace import Conn,functions,namespace
from catalog_filters import catalog_filter,SAVED_INVENTORY
class Sorting(unittest.TestCase):
 def setUp(self):self.c=Conn()
 def tearDown(self):self.c.db.close()
 def ids(self,key,**filters):
  where,args,order=catalog_filter({'sort':key,**filters})
  return [r['id'] for r in self.c.execute('SELECT p.id FROM products p WHERE '+where+' ORDER BY '+order,args)]
 def test_product_both_directions(self):
  asc=self.ids('name_asc');self.assertEqual(self.ids('name_desc'),list(reversed(asc)))
 def test_brands_missing_last_both_directions(self):
  self.assertEqual(self.ids('brand_asc'),list('bdeacf'));self.assertEqual(self.ids('brand_desc'),list('ebdacf'))
 def test_prices_missing_last_both_directions(self):
  self.assertEqual(self.ids('price_asc'),list('bcedfa'));self.assertEqual(self.ids('price_desc'),list('fde cba'.replace(' ','')))
 def test_inventory_known_zero_and_unknown_last(self):
  self.assertEqual(self.ids('inventory_asc'),list('bdcaef'));self.assertEqual(self.ids('inventory_desc'),list('cbdaef'))
 def test_partial_or_negative_inventory_is_unknown(self):
  self.c.db.execute("UPDATE product_variants SET inventory=-1 WHERE id='c0'")
  totals={r['id']:r['stock'] for r in self.c.execute('SELECT p.id,'+SAVED_INVENTORY+' AS stock FROM products p',[])}
  self.assertIsNone(totals['c']);self.assertIsNone(totals['e']);self.assertEqual(totals['b'],0)
 def test_supplier_filter_applies_to_global_sort(self):self.assertEqual(self.ids('inventory_desc',supplier_id='s1'),list('cbda'))
 def test_api_exposes_saved_total_and_sorted_pagination(self):
  ns=functions('backend/routes/products.py',['get_products'],namespace(self.c))
  result=asyncio.run(ns['get_products'](sort='inventory_desc',page=1,limit=2,user={}))
  self.assertEqual([r['id'] for r in result['products']],list('cb'));self.assertEqual(result['products'][0]['inventory_total'],800)
 def test_postgres_syntax_all_new_sorts(self):
  from pglast import parse_sql
  for field in ['brand','inventory','price','name']:
   for direction in ['asc','desc']:
    where,args,order=catalog_filter({'sort':field+'_'+direction});parse_sql('SELECT p.id,'+SAVED_INVENTORY+' FROM products p WHERE '+where+' ORDER BY '+order)
if __name__=='__main__':unittest.main()
