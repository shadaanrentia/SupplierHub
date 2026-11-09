import ast
import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('sizes',ROOT/'backend/size_order.py')
sizes=importlib.util.module_from_spec(spec);spec.loader.exec_module(sizes)
class UpdateTests(unittest.TestCase):
 def test_sizes_within_colour(self):
  labels=['4XL','M','XS','2XL','S','XL','L','3XL']
  rows=[{'size':s,'color':c} for c in ['Red','Black'] for s in labels]
  result=sizes.sort_export_variants(rows)
  self.assertEqual([v['size'] for v in result[:8]],['XS','S','M','L','XL','2XL','3XL','4XL'])
  self.assertEqual([v['color'] for v in result],['Black']*8+['Red']*8)
  self.assertEqual(rows[0]['size'],'4XL')
 def test_extended_and_alias_sizes(self):
  values=['XXL','Small','3XS','Large','XS','2XS','Medium','XL']
  result=sizes.sort_export_variants([{'size':v} for v in values])
  self.assertEqual([v['size'] for v in result],['3XS','2XS','XS','Small','Medium','Large','XL','XXL'])
 def test_split_sort_stays_size_first(self):
  rows=[{'size':'L','color':'Black'},{'size':'S','color':'Red'}]
  self.assertEqual(sizes.sort_variants(rows)[0]['size'],'S')
 def test_repair_filter_keeps_zero_and_missing_price(self):
  tree=ast.parse((ROOT/'backend/single_family.py').read_text())
  fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='repair_assets')
  assignment=next(n for n in ast.walk(fn) if isinstance(n,ast.Assign) and isinstance(n.value,ast.ListComp) and any(isinstance(t,ast.Name) and t.id=='variants' for t in n.targets))
  rows=[{'inventory':0,'price':None},{'inventory':64},{'inventory':0,'is_active':False}]
  context={'variants':rows}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[assignment],type_ignores=[])),'filter','exec'),context)
  self.assertEqual(context['variants'],rows[:2])
if __name__=='__main__':unittest.main()
