import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'backend'))
from inventory_selection import read_inventory_for_verification,verify_inventory_records
class Tests(unittest.TestCase):
 def service(self,entries):
  s=Mock(domain_prefix='test-store')
  s.family_request.return_value={'data':{'id':'member','outlet_inventories':entries}}
  s._http_session().get.return_value.status_code=200
  s._handle_response.return_value=[{'product_id':'member','outlet_id':'outlet','current_inventory_level':0}]
  return s
 def test_empty_metadata_reads_stock_endpoint(self):
  s=self.service([]);self.assertTrue(read_inventory_for_verification(s,'member','outlet',0));self.assertIn('/inventory/member',s._http_session().get.call_args.args[0])
 def test_other_outlet_metadata_reads_stock_endpoint(self):
  s=self.service([{'outlet_id':'another','current_amount':20}]);self.assertTrue(read_inventory_for_verification(s,'member','outlet',0))
 def test_missing_stock_does_not_mean_zero(self):
  s=self.service([]);s._handle_response.return_value=[]
  with self.assertRaisesRegex(ValueError,'matching_records=0'):read_inventory_for_verification(s,'member','outlet',0)
 def test_duplicate_metadata_not_bypassed(self):
  s=self.service([{'outlet_id':'outlet','current_amount':0}]*2)
  with self.assertRaisesRegex(ValueError,'matching_records=2'):read_inventory_for_verification(s,'member','outlet',0)
  s._http_session().get.assert_not_called()
 def test_real_mismatch_not_bypassed(self):
  s=self.service([{'outlet_id':'outlet','current_amount':10}])
  with self.assertRaisesRegex(ValueError,'expected 0, received 10'):read_inventory_for_verification(s,'member','outlet',0)
  s._http_session().get.assert_not_called()
 def test_invalid_metadata_not_bypassed(self):
  s=self.service(None)
  with self.assertRaises(ValueError):read_inventory_for_verification(s,'member','outlet',0)
  s._http_session().get.assert_not_called()
 def test_duplicate_stock_reports_count(self):
  with self.assertRaisesRegex(ValueError,'matching_records=2'):verify_inventory_records([{'product_id':'member','outlet_id':'outlet','current_inventory_level':0}]*2,'member','outlet',0)
 def test_nonzero_stock_verified(self):
  s=self.service([]);s._handle_response.return_value=[{'product_id':'member','outlet_id':'outlet','current_inventory_level':195}]
  self.assertTrue(read_inventory_for_verification(s,'member','outlet',195))
 def test_wrong_product_never_falls_back(self):
  s=self.service([]);s.family_request.return_value={'data':{'id':'other'}}
  with self.assertRaises(ValueError):read_inventory_for_verification(s,'member','outlet',0)
  s._http_session().get.assert_not_called()
if __name__=='__main__':unittest.main()
