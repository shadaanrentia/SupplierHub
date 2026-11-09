import ast
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
ns={}
for filename,names in [('single_family.py',{'sku','members'}),('multi_family.py',{'verify_group_destination'})]:
 tree=ast.parse((ROOT/'backend'/filename).read_text())
 nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
 exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),filename,'exec'),ns)
verify=ns['verify_group_destination']
class Tests(unittest.TestCase):
 def family(self,name='Reviewed Group',sku='source-1',codes=None):
  return {'id':'family-1','name':name,'products':[{'id':'member-1','sku':sku,'codes':codes or []}]}
 def check(self,family=None,**kwargs):
  args=dict(family=family or self.family(),expected_skus=['source-1'],found={'source-1':{'id':'member-1'}},destination=None,expected_name='Reviewed Group',group_number=1)
  args.update(kwargs);return verify(**args)
 def test_matching_family_passes(self):self.assertEqual(list(self.check()),['source-1'])
 def test_custom_alias_resolves_primary_group_sku(self):
  f=self.family(sku='group-export-code',codes=[{'type':'CUSTOM','code':'SOURCE-1'}])
  self.assertEqual(list(self.check(f)),['source-1'])
 def test_legacy_code_alias_resolves(self):
  f=self.family(sku='group-export-code');f['products'][0]['product_codes']=[{'type':'CUSTOM','code':'source-1'}]
  self.assertEqual(list(self.check(f)),['source-1'])
 def test_unrelated_sku_still_blocked(self):
  with self.assertRaisesRegex(ValueError,'SKUs outside this group: other'):self.check(self.family(sku='other'))
 def test_exact_sku_set_recovers_renamed_family(self):
  self.assertEqual(list(self.check(self.family(name='Different'))),['source-1'])
 def test_incomplete_sku_evidence_cannot_claim_renamed_family(self):
  with self.assertRaisesRegex(ValueError,"expected name=.*actual name='Different'"):
   self.check(self.family(name='Different'),expected_skus=['source-1','source-2'])
 def test_found_members_across_families_blocked(self):
  with self.assertRaisesRegex(ValueError,'another family: other-member'):self.check(found={'source-1':{'id':'other-member'}})
 def test_verified_saved_member_allows_rename(self):self.assertTrue(self.check(self.family(name='Renamed'),destination='member-1'))
 def test_saved_member_cannot_bypass_foreign_sku(self):
  with self.assertRaises(ValueError):self.check(self.family(sku='other'),destination='member-1')
 def test_ambiguous_aliases_blocked(self):
  f=self.family(codes=[{'type':'CUSTOM','code':'source-2'}])
  with self.assertRaisesRegex(ValueError,'multiple source variant SKUs'):self.check(f,expected_skus=['source-1','source-2'])
 def test_duplicate_source_skus_blocked(self):
  f=self.family();f['products'].append(dict(f['products'][0],id='member-2'))
  with self.assertRaisesRegex(ValueError,'duplicate'):self.check(f)
 def test_empty_family_blocked(self):
  f=self.family();f['products']=[]
  with self.assertRaisesRegex(ValueError,'no identifiable members'):self.check(f,found={})
 def test_missing_remote_id_blocked(self):
  f=self.family();f['products'][0].pop('id')
  with self.assertRaises(ValueError):self.check(f)
if __name__=='__main__':unittest.main()

