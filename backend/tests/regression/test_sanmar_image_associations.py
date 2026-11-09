import ast
import json
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'backend'))
from media_links import associate_sanmar_images
# Exercise the real matcher without loading FastAPI or database dependencies.
tree=ast.parse((ROOT/'backend/single_family.py').read_text())
fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='matched_images')
sku_fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='sku')
ns={'json':json};exec(compile(ast.fix_missing_locations(ast.Module(body=[sku_fn,fn],type_ignores=[])),'matcher','exec'),ns)
matched_images=ns['matched_images']
BASE='https://media.sanmarcanada.com/catalog/product/t/s/'
class Tests(unittest.TestCase):
 def rows(self):return [{'variant_sku':'one','color':'True Navy','size':'S','inventory':10},{'variant_sku':'two','color':'True Navy','size':'XL','inventory':0},{'variant_sku':'white','color':'White','size':'S','inventory':0}]
 def link(self,name,**kw):return associate_sanmar_images([dict(url=BASE+name,**kw)],self.rows(),'TS445')[0]
 def test_zero_stock_receives_same_colour(self):
  image=self.link('ts445_truenavy_flat_front.jpg')
  for v in self.rows()[:2]:self.assertEqual(matched_images(v,[image]),[image])
  self.assertEqual(matched_images(self.rows()[2],[image]),[])
 def test_spaced_colour_tokens(self):self.assertEqual(self.link('ts445_true_navy_front.jpg')['source_part_ids'],['one','two'])
 def test_white_links_without_stock(self):self.assertEqual(self.link('ts445_white_flat_front.jpg')['source_part_ids'],['white'])
 def test_wrong_product_rejected(self):self.assertNotIn('source_part_ids',self.link('ts365_white_front.jpg'))
 def test_similar_style_rejected(self):self.assertNotIn('source_part_ids',self.link('ts4450_white_front.jpg'))
 def test_other_host_rejected(self):
  for u in ['https://example.com/catalog/product/t/s/ts445_white.jpg','https://media.sanmarcanada.com.evil.test/catalog/product/t/s/ts445_white.jpg','http://media.sanmarcanada.com/catalog/product/t/s/ts445_white.jpg','https://media.sanmarcanada.com:bad/catalog/product/t/s/ts445_white.jpg']:
   self.assertNotIn('source_part_ids',associate_sanmar_images([{'url':u}],self.rows(),'TS445')[0])
 def test_unknown_colour_rejected(self):self.assertNotIn('source_part_ids',self.link('ts445_green_front.jpg'))
 def test_multiple_colours_rejected(self):self.assertNotIn('source_part_ids',self.link('ts445_white_truenavy_front.jpg'))
 def test_explicit_colour_preserved(self):self.assertEqual(self.link('ts445_white_front.jpg',source_color='True Navy')['source_color'],'True Navy')
 def test_explicit_parts_expand_only_verified_colour_sizes(self):
  image=self.link('ts445_white_front.jpg',source_part_ids=['one'])
  self.assertEqual(image['source_part_ids'],['one','two'])
  self.assertEqual(image['source_color'],'True Navy')
  self.assertEqual(matched_images(self.rows()[2],[image]),[])
 def test_no_substring_match(self):self.assertNotIn('source_part_ids',self.link('ts445_offwhite_front.jpg'))
 def test_missing_style_rejected(self):self.assertNotIn('source_part_ids',associate_sanmar_images([{'url':BASE+'ts445_white.jpg'}],self.rows(),'')[0])
 def test_input_not_mutated(self):
  image={'url':BASE+'ts445_white.jpg'};associate_sanmar_images([image],self.rows(),'TS445');self.assertEqual(list(image),['url'])
 def test_compact_colour_collision_rejected(self):
  rows=[{'variant_sku':'a','color':'Off White'},{'variant_sku':'b','color':'Offwhite'}]
  self.assertNotIn('source_part_ids',associate_sanmar_images([{'url':BASE+'ts445_offwhite.jpg'}],rows,'TS445')[0])
 def test_explicit_json_parts_normalize_to_verified_colour_sizes(self):
  image=self.link('ts445_white.jpg',source_part_ids='["one"]')
  self.assertEqual(image['source_part_ids'],['one','two'])
  self.assertEqual(matched_images(self.rows()[2],[image]),[])


FIXTURES = [{'style': 'OG1301', 'variants': [{'variant_sku': '21300-1', 'color': 'Blacktop', 'size': 'XS', 'inventory': 0}, {'variant_sku': '21300-2', 'color': 'Blacktop', 'size': 'S', 'inventory': 0}, {'variant_sku': '21300-3', 'color': 'Blacktop', 'size': 'M', 'inventory': 0}, {'variant_sku': '21300-4', 'color': 'Blacktop', 'size': 'L', 'inventory': 0}, {'variant_sku': '21300-5', 'color': 'Blacktop', 'size': 'XL', 'inventory': 0}, {'variant_sku': '21301-1', 'color': 'Blacktop', 'size': '2XL', 'inventory': 0}, {'variant_sku': '21302-2', 'color': 'Blacktop', 'size': '3XL', 'inventory': 0}, {'variant_sku': '21303-3', 'color': 'Blacktop', 'size': '4XL', 'inventory': 0}, {'variant_sku': '21304-1', 'color': 'Blush Red', 'size': 'XS', 'inventory': 0}, {'variant_sku': '21304-2', 'color': 'Blush Red', 'size': 'S', 'inventory': 0}, {'variant_sku': '21304-3', 'color': 'Blush Red', 'size': 'M', 'inventory': 0}, {'variant_sku': '21304-4', 'color': 'Blush Red', 'size': 'L', 'inventory': 0}, {'variant_sku': '21304-5', 'color': 'Blush Red', 'size': 'XL', 'inventory': 0}, {'variant_sku': '21305-1', 'color': 'Blush Red', 'size': '2XL', 'inventory': 0}, {'variant_sku': '21306-2', 'color': 'Blush Red', 'size': '3XL', 'inventory': 0}, {'variant_sku': '21307-3', 'color': 'Blush Red', 'size': '4XL', 'inventory': 0}, {'variant_sku': '21308-1', 'color': 'Electric Blue', 'size': 'XS', 'inventory': 0}, {'variant_sku': '21308-2', 'color': 'Electric Blue', 'size': 'S', 'inventory': 0}, {'variant_sku': '21308-3', 'color': 'Electric Blue', 'size': 'M', 'inventory': 0}, {'variant_sku': '21308-4', 'color': 'Electric Blue', 'size': 'L', 'inventory': 0}, {'variant_sku': '21308-5', 'color': 'Electric Blue', 'size': 'XL', 'inventory': 0}, {'variant_sku': '21309-1', 'color': 'Electric Blue', 'size': '2XL', 'inventory': 0}, {'variant_sku': '21310-2', 'color': 'Electric Blue', 'size': '3XL', 'inventory': 0}, {'variant_sku': '21311-3', 'color': 'Electric Blue', 'size': '4XL', 'inventory': 0}, {'variant_sku': '21312-1', 'color': 'Fuel Green', 'size': 'XS', 'inventory': 0}, {'variant_sku': '21312-2', 'color': 'Fuel Green', 'size': 'S', 'inventory': 0}, {'variant_sku': '21312-3', 'color': 'Fuel Green', 'size': 'M', 'inventory': 0}, {'variant_sku': '21312-4', 'color': 'Fuel Green', 'size': 'L', 'inventory': 0}, {'variant_sku': '21312-5', 'color': 'Fuel Green', 'size': 'XL', 'inventory': 0}, {'variant_sku': '21313-1', 'color': 'Fuel Green', 'size': '2XL', 'inventory': 0}, {'variant_sku': '21314-2', 'color': 'Fuel Green', 'size': '3XL', 'inventory': 0}, {'variant_sku': '21315-3', 'color': 'Fuel Green', 'size': '4XL', 'inventory': 0}], 'images': [{'url': 'https://media.sanmarcanada.com/catalog/product/o/g/og1301_form_angle_blacktop_042014.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/o/g/og1301_form_angle_blushred_042014.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/o/g/og1301_form_angle_electricblue_042014.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/o/g/og1301_form_angle_fuelgreen.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/o/g/og1301_form_front_blacktop_042014.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/o/g/og1301_form_front_blushred_042014.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/o/g/og1301_form_front_electricblue_042014.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/o/g/og1301_form_front_fuelgreen.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/o/g/og1301_form_back_blacktop_042014.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/o/g/og1301_form_back_blushred_042014.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/o/g/og1301_form_back_electricblue_042014.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/o/g/og1301_form_back_fuelgreen.jpg', 'source_color': '', 'source_part_ids': '[]'}]}, {'style': 'TS445', 'variants': [{'variant_sku': '20762-1', 'color': 'Black', 'size': 'LT', 'inventory': 0}, {'variant_sku': '20763-3', 'color': 'Black', 'size': '2XLT', 'inventory': 0}, {'variant_sku': '20764-4', 'color': 'Black', 'size': '3XLT', 'inventory': 0}, {'variant_sku': '20765-5', 'color': 'Black', 'size': '4XLT', 'inventory': 0}, {'variant_sku': '20766-1', 'color': 'True Navy', 'size': 'LT', 'inventory': 0}, {'variant_sku': '20767-3', 'color': 'True Navy', 'size': '2XLT', 'inventory': 0}, {'variant_sku': '20768-4', 'color': 'True Navy', 'size': '3XLT', 'inventory': 0}, {'variant_sku': '20769-5', 'color': 'True Navy', 'size': '4XLT', 'inventory': 0}, {'variant_sku': '20770-1', 'color': 'White', 'size': 'LT', 'inventory': 0}, {'variant_sku': '20771-3', 'color': 'White', 'size': '2XLT', 'inventory': 0}, {'variant_sku': '20772-4', 'color': 'White', 'size': '3XLT', 'inventory': 0}, {'variant_sku': '20773-5', 'color': 'White', 'size': '4XLT', 'inventory': 0}, {'variant_sku': '20774-1', 'color': 'Iron Grey', 'size': 'LT', 'inventory': 0}, {'variant_sku': '20775-3', 'color': 'Iron Grey', 'size': '2XLT', 'inventory': 0}, {'variant_sku': '20776-4', 'color': 'Iron Grey', 'size': '3XLT', 'inventory': 0}, {'variant_sku': '20777-5', 'color': 'Iron Grey', 'size': '4XLT', 'inventory': 0}, {'variant_sku': '21828-2', 'color': 'Black', 'size': 'XLT', 'inventory': 0}, {'variant_sku': '21829-2', 'color': 'Iron Grey', 'size': 'XLT', 'inventory': 0}, {'variant_sku': '21830-2', 'color': 'True Navy', 'size': 'XLT', 'inventory': 0}, {'variant_sku': '21831-2', 'color': 'White', 'size': 'XLT', 'inventory': 0}], 'images': [{'url': 'https://media.sanmarcanada.com/catalog/product/t/s/ts445_truenavy_modl_studio-1_1.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/t/s/ts445_black_flat_front.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/t/s/ts445_irongrey_flat_front.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/t/s/ts445_truenavy_flat_front.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/t/s/ts445_white_flat_front.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/t/s/ts445_black_form_angle.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/t/s/ts445_irongrey_form_angle.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/t/s/ts445_truenavy_form_angle.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/t/s/ts445_white_form_angle.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/t/s/ts445_black_flat_back.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/t/s/ts445_irongrey_flat_back.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/t/s/ts445_truenavy_flat_back.jpg', 'source_color': '', 'source_part_ids': '[]'}, {'url': 'https://media.sanmarcanada.com/catalog/product/t/s/ts445_white_flat_back.jpg', 'source_color': '', 'source_part_ids': '[]'}]}]

class DiagnosticRegressionTests(unittest.TestCase):
 def check_product(self, index):
  fixture=FIXTURES[index]
  result=associate_sanmar_images(fixture['images'],fixture['variants'],fixture['style'])
  self.assertTrue(all(image.get('source_part_ids') for image in result))
  for variant in fixture['variants']:
   selected=matched_images(variant,result)
   self.assertTrue(selected, variant['variant_sku'])
   self.assertTrue(all(image['source_color']==variant['color'] for image in selected))
 def test_og1301_all_32_zero_stock_variants(self):self.check_product(0)
 def test_ts445_all_20_zero_stock_variants(self):self.check_product(1)




class ReadbackTimingTests(unittest.IsolatedAsyncioTestCase):
 async def exercise(self, values):
  import asyncio
  import types
  from unittest.mock import Mock, AsyncMock, patch, call
  tree=ast.parse((ROOT/'backend/lightspeed_service.py').read_text())
  cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LightspeedService')
  method=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_verify_remote_inventory')
  ns={'asyncio':asyncio}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'readback','exec'),ns)
  reader=Mock(side_effect=values)
  selection=types.ModuleType('inventory_selection');selection.read_inventory_for_verification=reader
  verification=types.ModuleType('inventory_verification');verification.InventoryVerificationError=ValueError
  target=object()
  with patch.dict(sys.modules,{'inventory_selection':selection,'inventory_verification':verification}), patch.object(asyncio,'sleep',new_callable=AsyncMock) as sleep:
   try:
    result=await ns['_verify_remote_inventory'](target,'member','outlet',195)
   except ValueError:
    result=False
   self.assertEqual(reader.call_args_list,[call(target,'member','outlet',195)]*3)
   self.assertEqual(sleep.call_args_list,[call(1.0),call(3.0)])
   return result
 async def test_delayed_read_is_verified(self):
  self.assertTrue(await self.exercise([ValueError('mismatch'),ValueError('mismatch'),True]))
 async def test_persistent_mismatch_remains_failure(self):
  self.assertFalse(await self.exercise([ValueError('mismatch')]*3))

if __name__=='__main__':unittest.main()

