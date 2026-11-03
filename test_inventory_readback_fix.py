import sys
from pathlib import Path
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).parent/'backend'))
from inventory_selection import read_inventory_for_verification, verify_inventory_records

def records(amount=64):return [{'product_id':'product','outlet_id':'outlet','current_inventory_level':amount}]
def service():
 s=Mock(domain_prefix='store');s.family_request.return_value={'data':{'id':'product'}};s._handle_response.return_value=records();s._http_session().get.return_value.status_code=200;return s
class Tests(unittest.TestCase):
 def test_endpoint_contract(self):
  s=service();self.assertTrue(read_inventory_for_verification(s,'product','outlet',64));s._http_session().get.assert_called_once_with('https://store.retail.lightspeed.app/api/2026-07/inventory/product',headers=s._headers(),params={'variants':'false','include_deleted':'false','page_size':5000},timeout=120)
 def test_modern_success_no_second_read(self):
  s=service();s.family_request.return_value={'data':{'id':'product','outlet_inventories':[{'outlet_id':'outlet','current_amount':64}]}}
  self.assertTrue(read_inventory_for_verification(s,'product','outlet',64));s._http_session().get.assert_not_called()
 def test_modern_mismatch_not_bypassed(self):
  s=service();s.family_request.return_value={'data':{'id':'product','outlet_inventories':[{'outlet_id':'outlet','current_amount':1}]}}
  with self.assertRaisesRegex(ValueError,'mismatch'):read_inventory_for_verification(s,'product','outlet',64)
  s._http_session().get.assert_not_called()
 def test_zero_verified(self):self.assertTrue(verify_inventory_records(records(0),'product','outlet',0))
 def test_other_outlets_not_summed(self):
  rows=records();rows.append({'product_id':'product','outlet_id':'other','current_inventory_level':100})
  self.assertTrue(verify_inventory_records(rows,'product','outlet',64))
 def test_empty_is_not_zero(self):
  with self.assertRaises(ValueError):verify_inventory_records([],'product','outlet',0)
 def test_product_wrapper_rejected(self):
  with self.assertRaises(ValueError):verify_inventory_records({'data':records()},'product','outlet',64)
 def test_wrong_product_rejected(self):
  r=records();r[0]['product_id']='other'
  with self.assertRaises(ValueError):verify_inventory_records(r,'product','outlet',64)
 def test_wrong_outlet_rejected(self):
  with self.assertRaises(ValueError):verify_inventory_records(records(),'product','different',64)
 def test_duplicate_rejected(self):
  with self.assertRaises(ValueError):verify_inventory_records(records()*2,'product','outlet',64)
 def test_bad_quantity_rejected(self):
  for v in [None,True,-1,'NaN',1.5,2147483648]:
   with self.assertRaises(ValueError):verify_inventory_records(records(v),'product','outlet',64)
 def test_missing_quantity_rejected(self):
  r=records();r[0].pop('current_inventory_level')
  with self.assertRaises(ValueError):verify_inventory_records(r,'product','outlet',0)
 def test_deleted_rejected(self):
  r=records();r[0]['deleted_at']='2026-01-01'
  with self.assertRaises(ValueError):verify_inventory_records(r,'product','outlet',64)
 def test_scope_error_actionable(self):
  s=service();s._http_session().get.return_value.status_code=403
  with self.assertRaisesRegex(ValueError,'inventory:read'):read_inventory_for_verification(s,'product','outlet',64)
 def test_truncation_rejected(self):
  with self.assertRaises(ValueError):verify_inventory_records(records()*5000,'product','outlet',64)
 def test_transport_error_not_success(self):
  s=service();s._http_session().get.side_effect=ConnectionError('offline')
  with self.assertRaises(ConnectionError):read_inventory_for_verification(s,'product','outlet',64)
if __name__=='__main__':unittest.main()
