import sys
from pathlib import Path
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).parent/'backend'))
from inventory_selection import read_inventory_for_verification, verify_legacy_inventory

def modern(amount=64):return {'data':{'id':'product','outlet_inventories':[{'outlet_id':'outlet','current_amount':amount}]}}
def legacy(amount=64):return {'data':{'id':'product','inventory':[{'product_id':'product','outlet_id':'outlet','count':amount}]}}
def service(response):
 s=Mock(domain_prefix='store');s.family_request.return_value=response;s._handle_response.return_value=legacy();return s
class Tests(unittest.TestCase):
 def test_modern_success_has_no_fallback(self):
  s=service(modern());self.assertTrue(read_inventory_for_verification(s,'product','outlet',64));s._http_session.assert_not_called()
 def test_missing_modern_field_reads_legacy(self):
  s=service({'data':{'id':'product'}});self.assertTrue(read_inventory_for_verification(s,'product','outlet',64));self.assertEqual(s._http_session().get.call_args.args[0],'https://store.retail.lightspeed.app/api/2.0/products/product');s.family_request.assert_called_once_with('GET','products/product')
 def test_zero_verified(self):self.assertTrue(verify_legacy_inventory(legacy('0.00000'),'product','outlet',0))
 def test_mismatch_not_hidden(self):
  s=service(modern(12))
  with self.assertRaisesRegex(ValueError,'mismatch'):read_inventory_for_verification(s,'product','outlet',64)
  s._http_session.assert_not_called()
 def test_wrong_product_no_fallback(self):
  s=service({'data':{'id':'other'}})
  with self.assertRaises(ValueError):read_inventory_for_verification(s,'product','outlet',64)
  s._http_session.assert_not_called()
 def test_invalid_modern_collection_no_fallback(self):
  for value in [None,[],{}]:
   s=service({'data':{'id':'product','outlet_inventories':value}})
   with self.assertRaises(ValueError):read_inventory_for_verification(s,'product','outlet',64)
   s._http_session.assert_not_called()
 def test_legacy_missing_never_zero(self):
  for r in [{'data':{'id':'product'}},{'data':{'id':'product','inventory':[]}}]:
   with self.assertRaises(ValueError):verify_legacy_inventory(r,'product','outlet',0)
 def test_foreign_record_rejected(self):
  r=legacy();r['data']['inventory'][0]['product_id']='other'
  with self.assertRaises(ValueError):verify_legacy_inventory(r,'product','outlet',64)
 def test_duplicate_outlet_rejected(self):
  r=legacy();r['data']['inventory']*=2
  with self.assertRaises(ValueError):verify_legacy_inventory(r,'product','outlet',64)
 def test_bad_legacy_quantities_rejected(self):
  for v in [None,True,-1,'NaN',1.5,2147483648]:
   with self.assertRaises(ValueError):verify_legacy_inventory(legacy(v),'product','outlet',64)
 def test_wrong_outlet_rejected(self):
  with self.assertRaises(ValueError):verify_legacy_inventory(legacy(),'product','different',64)
 def test_read_error_propagates(self):
  s=service({'data':{'id':'product'}});s._http_session().get.side_effect=RuntimeError('offline')
  with self.assertRaisesRegex(RuntimeError,'offline'):read_inventory_for_verification(s,'product','outlet',64)
if __name__=='__main__':unittest.main()
