"""Offline Export Review list regressions; no external services or database writes."""
import ast
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[3]
class Tests(unittest.IsolatedAsyncioTestCase):
    async def run_listing(self,count=257,page=1,oversized=False,issues=True):
        rows=[{'id':str(i),'supplier_sku':str(i),'product_name':'Product'} for i in range(count)]
        batches=[];query=[]
        class Conn:
            async def fetch(self,sql,*args):query.append(sql);return rows
        @asynccontextmanager
        async def acquire():yield Conn()
        async def readiness(conn,batch,include_assets=True):
            self.assertFalse(include_assets,'Listing must never load full assets')
            self.assertLessEqual(len(batch),100)
            batches.append([p['id'] for p in batch])
            return {p['id']:{'excluded_from_queue':int(p['id'])%11==0,'variants_count':201 if int(p['id'])%2 else 10,'is_valid':int(p['id'])%3==0,'previous_export_failed':False,'status':'ready','images_count':2} for p in batch}
        def validate_export_name(name,sku):return name+' '+sku
        ns={'deps':SimpleNamespace(pool=SimpleNamespace(acquire=acquire)),'row_to_dict':dict,'load_readiness':readiness,'public_state':dict,'export_name':validate_export_name,'LIMIT':200}
        tree=ast.parse((ROOT/'backend/routes/export_review.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_review_listing')
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'review-listing','exec'),ns)
        result=await ns['_review_listing']('',oversized,issues,page)
        expected=[str(i) for i in range(count) if (not oversized or i%2) and (not issues or i%3)]
        self.assertEqual(result['total'],len(expected))
        self.assertEqual([p['id'] for p in result['products']],expected[(page-1)*50:page*50])
        self.assertNotIn('p.*',query[0]);self.assertNotIn('image_base64',query[0]);self.assertNotIn('bulk_metadata',query[0])
        return result,batches
    async def test_issue_filter_before_pagination(self):await self.run_listing(page=2)
    async def test_all_products(self):await self.run_listing(issues=False)
    async def test_oversized_issues(self):await self.run_listing(page=2,oversized=True)
    async def test_empty_catalogue(self):
        result,batches=await self.run_listing(count=0);self.assertEqual(result['products'],[]);self.assertEqual(batches,[])
    async def test_page_past_end(self):await self.run_listing(page=99)
    async def test_large_catalogue_is_bounded(self):
        result,batches=await self.run_listing(count=1201,page=10)
        self.assertEqual(len(batches),13)
        self.assertEqual(len({identity for batch in batches for identity in batch}),1201)
    async def test_timeout_is_clear_and_not_false_empty_success(self):
        class HTTPException(Exception):
            def __init__(self,status_code,detail):self.status_code=status_code;self.detail=detail
        async def blocked(*args):raise asyncio.TimeoutError()
        ns={'asyncio':asyncio,'_review_listing':blocked,'HTTPException':HTTPException,'Query':lambda *a,**kw:1,'Depends':lambda x:None,'get_current_user':lambda:None}
        tree=ast.parse((ROOT/'backend/routes/export_review.py').read_text());fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='products');fn.decorator_list=[]
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'review-route','exec'),ns)
        with self.assertRaises(HTTPException) as error:await ns['products'](page=1,user={})
        self.assertEqual(error.exception.status_code,503);self.assertIn('no products were changed',error.exception.detail)
    async def test_oversized_boundary_199_variants(self):
        await self.run_boundary_listing(199, expected_included=False)

    async def test_oversized_boundary_200_variants(self):
        await self.run_boundary_listing(200, expected_included=True)

    async def test_oversized_boundary_201_variants(self):
        await self.run_boundary_listing(201, expected_included=True)

    async def run_boundary_listing(self, count, expected_included):
        rows = [{
            "id": "boundary-product",
            "supplier_sku": "BOUNDARY-001",
            "product_name": "Boundary Product",
        }]

        class Conn:
            async def fetch(self, sql, *args):
                return rows

        @asynccontextmanager
        async def acquire():
            yield Conn()

        async def readiness(conn, batch, include_assets=True):
            return {
                "boundary-product": {
                    "excluded_from_queue": False,
                    "variants_count": count,
                    "is_valid": True,
                    "previous_export_failed": False,
                    "status": "ready",
                    "images_count": 1,
                }
            }

        namespace = {
            "deps": SimpleNamespace(
                pool=SimpleNamespace(acquire=acquire)
            ),
            "row_to_dict": dict,
            "load_readiness": readiness,
            "public_state": dict,
            "export_name": lambda name, sku: name + " " + sku,
            "LIMIT": 200,
        }

        tree = ast.parse(
            (ROOT / "backend" / "routes" / "export_review.py").read_text()
        )

        function = next(
            node for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_review_listing"
        )

        exec(
            compile(
                ast.Module(body=[function], type_ignores=[]),
                "review-boundary",
                "exec",
            ),
            namespace,
        )

        result = await namespace["_review_listing"](
            "",
            True,
            False,
            1,
        )

        self.assertEqual(
            len(result["products"]) == 1,
            expected_included,
        )
        self.assertEqual(
            result["total"],
            1 if expected_included else 0,
        )

if __name__=='__main__':unittest.main()
