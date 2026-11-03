"""Offline tests; no database, credentials, supplier requests or Lightspeed writes."""
import ast
import asyncio
import copy
import logging
from pathlib import Path
import sys
import unittest

BACKEND=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(BACKEND))
from inventory_selection import quantity,select_inventory,verify_member_inventory
from sku_eligibility import eligible_variants


def member(amount=0,product='remote',outlet='outlet'):
    return {'data':{'id':product,'outlet_inventories':[{'outlet_id':outlet,'current_amount':amount}]}}


class InventoryTests(unittest.TestCase):
    def test_preferred_warehouse_overwrites_total(self):
        row={'inventory':124,'warehouse_inventory':[{'name':'MISSISSAUGA/ON','quantity':64}]}
        before=copy.deepcopy(row)
        self.assertEqual(select_inventory([row],'MISSISSAUGA/ON')[0]['inventory'],64)
        self.assertEqual(row,before)

    def test_warehouse_zero_is_preserved(self):
        self.assertEqual(select_inventory([{'inventory':19,'warehouse_inventory':'[{"name":"A","quantity":0}]'}],'A')[0]['inventory'],0)

    def test_bad_quantities_rejected(self):
        for value in (None,True,False,-1,1.5,'NaN','Infinity','abc',''):
            with self.subTest(value=value),self.assertRaises(ValueError):quantity(value)

    def test_missing_warehouse_blocks_export(self):
        with self.assertRaises(ValueError):select_inventory([{'inventory':19,'warehouse_inventory':[{'name':'B','quantity':19}]}],'A')

    def test_duplicate_warehouse_blocks_export(self):
        with self.assertRaises(ValueError):select_inventory([{'warehouse_inventory':[{'name':'A','quantity':1}]*2}],'A')

    def test_supplier_without_breakdown_uses_stored_quantity(self):
        self.assertEqual(select_inventory([{'inventory':12}],'A')[0]['inventory'],12)

    def test_valid_zero_variants_stay_eligible(self):
        self.assertEqual(len(eligible_variants([{'inventory':0,'price':19.99}])),1)

    def test_invalid_price_inactive_and_invalid_inventory_excluded(self):
        for row in ({'inventory':0,'price':0},{'inventory':0,'price':1,'is_active':False},{'inventory':-1,'price':1}):
            self.assertEqual(eligible_variants([row]),[])

    def test_readback_requires_exact_quantity_product_and_outlet(self):
        self.assertTrue(verify_member_inventory(member(64),'remote','outlet',64))
        self.assertTrue(verify_member_inventory(member(0),'remote','outlet',0))
        for response in (member(124),member(64,product='wrong'),member(64,outlet='wrong'),{'data':{'id':'remote'}}):
            with self.assertRaises(ValueError):verify_member_inventory(response,'remote','outlet',64)


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tree=ast.parse((BACKEND/'lightspeed_service.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LightspeedService')
        cls.body=[n for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in ('_sync_single_variant','_verify_remote_inventory','update_product_inventory')]
        ns={'asyncio':asyncio,'logger':logging.getLogger('offline-test')}
        exec(compile(ast.Module(body=[cls],type_ignores=[]),'actual_service_methods','exec'),ns)
        self.ls=ns['LightspeedService']();self.ls.mock_mode=False
        self.ls._variant_sync_semaphore=asyncio.Semaphore(2);self.writes=[]
        def put(path,payload):self.writes.append((path,copy.deepcopy(payload)));return {'data':{'id':'remote'}}
        self.ls._put_legacy_21=put
        self.ls.family_request=lambda method,path:member(0)

    async def send(self,amount):
        return await self.ls._sync_single_variant('remote','sku',{'details':{'price_excluding_tax':39.98,'inventory':[{'outlet_id':'outlet','current_amount':amount}]}})

    async def test_zero_written_and_verified_with_price_preserved(self):
        result=await self.send(0);self.assertTrue(result['success']);self.assertTrue(result['inventory_verified'])
        self.assertEqual(self.writes[0][1]['details']['inventory'][0]['current_amount'],0)
        self.assertEqual(self.writes[0][1]['details']['price_excluding_tax'],39.98)

    async def test_bad_quantities_cannot_reach_write(self):
        for amount in (-1,None,True,1.5,'NaN'):self.assertFalse((await self.send(amount))['success'])
        self.assertEqual(self.writes,[])

    async def test_mismatch_fails_without_repeating_write(self):
        self.assertFalse((await self.send(64))['success']);self.assertEqual(len(self.writes),1)

    async def test_repeated_sync_does_not_add_stock(self):
        self.ls.family_request=lambda method,path:member(64)
        for _ in range(2):self.assertTrue((await self.send(64))['success'])
        self.assertEqual([r[1]['details']['inventory'][0]['current_amount'] for r in self.writes],[64,64])

    async def test_inventory_only_path_uses_absolute_write(self):
        self.assertTrue(self.ls.update_product_inventory('remote','outlet',0)['success'])
        self.assertEqual(self.writes[0][1],{'details':{'inventory':[{'outlet_id':'outlet','current_amount':0}]}})

    async def test_inventory_only_path_blocks_bad_input(self):
        self.assertFalse(self.ls.update_product_inventory('remote','outlet',-1)['success']);self.assertEqual(self.writes,[])

    async def test_inventory_only_path_preserves_identifier_checks(self):
        for product,outlet in ((None,'outlet'),(42,'outlet'),('','outlet'),('remote',False),('remote',' ')):
            self.assertFalse(self.ls.update_product_inventory(product,outlet,0)['success'])
        self.assertEqual(self.writes,[])

    async def test_inventory_only_path_preserves_maximum_quantity(self):
        self.assertFalse(self.ls.update_product_inventory('remote','outlet',2147483648)['success'])
        self.assertEqual(self.writes,[])

    async def test_variant_path_rejects_out_of_range_quantity(self):
        self.assertFalse((await self.send(2147483648))['success'])
        self.assertEqual(self.writes,[])

    async def test_inventory_only_readback_mismatch_is_failure(self):
        self.assertFalse(self.ls.update_product_inventory('remote','outlet',64)['success'])
        self.assertEqual(len(self.writes),1)

    async def test_price_only_update_does_not_require_stock(self):
        reads=[]
        self.ls.family_request=lambda *args:reads.append(args)
        result=await self.ls._sync_single_variant('remote','sku',{'details':{'price_excluding_tax':20}})
        self.assertTrue(result['success']);self.assertFalse(result['inventory_verified'])
        self.assertEqual(reads,[]);self.assertEqual(len(self.writes),1)

    async def test_measurements_only_update_still_works(self):
        calls=[]
        self.ls._sync_measurements=lambda *args:calls.append(args)
        result=await self.ls._sync_single_variant('remote','sku',{'details':{}},measurements={'weight':2})
        self.assertTrue(result['success']);self.assertEqual(len(calls),1)

    async def test_unconfirmed_readback_cannot_succeed(self):
        async def unconfirmed(*args):return None
        self.ls._verify_remote_inventory=unconfirmed
        self.assertFalse((await self.send(0))['success'])


if __name__=='__main__':unittest.main(verbosity=2)
