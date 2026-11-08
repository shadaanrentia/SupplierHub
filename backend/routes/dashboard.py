"""Lightweight saved catalogue summaries. No export-readiness or asset loading."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
import deps
from deps import get_current_user
router=APIRouter(prefix='/api')

@router.get('/dashboard/stats')
async def get_dashboard_stats(user:dict=Depends(get_current_user)):
    from catalog_filters import IMAGE_EXISTS
    async with deps.pool.acquire() as conn:
        async with conn.transaction(isolation='repeatable_read',readonly=True):
            row=await conn.fetchrow("""SELECT COUNT(*) total_products,
                (SELECT COUNT(*) FROM product_variants) total_variants,
                (SELECT COUNT(*) FROM suppliers) total_suppliers,
                COUNT(DISTINCT BTRIM(category)) FILTER(WHERE NULLIF(BTRIM(category),'') IS NOT NULL AND LOWER(BTRIM(category))<>'uncategorized') total_categories,
                COUNT(DISTINCT BTRIM(brand)) FILTER(WHERE NULLIF(BTRIM(brand),'') IS NOT NULL AND LOWER(BTRIM(brand))<>'unbranded') total_brands,
                COUNT(*) FILTER(WHERE NULLIF(BTRIM(category),'') IS NOT NULL AND LOWER(BTRIM(category))<>'uncategorized') categorized,
                COUNT(*) FILTER(WHERE NULLIF(BTRIM(brand),'') IS NOT NULL AND LOWER(BTRIM(brand))<>'unbranded') branded,
                COUNT(*) FILTER(WHERE p.base_price>0) priced,
                COUNT(*) FILTER(WHERE """+IMAGE_EXISTS+''') with_images FROM products p''')
            suppliers=await conn.fetch("""WITH pc AS (
                SELECT supplier_id,COUNT(*) products,MAX(updated_at) updated_at FROM products GROUP BY supplier_id),
                vc AS (SELECT p.supplier_id,COUNT(*) variants FROM products p JOIN product_variants v ON v.product_id=p.id GROUP BY p.supplier_id)
                SELECT s.id supplier_id,s.supplier_name,s.last_sync,COALESCE(pc.products,0) products,
                    COALESCE(vc.variants,0) variants,pc.updated_at
                FROM suppliers s LEFT JOIN pc ON pc.supplier_id=s.id LEFT JOIN vc ON vc.supplier_id=s.id
                UNION ALL SELECT '__unassigned__','Unassigned supplier',NULL,COALESCE(SUM(pc.products),0),
                    COALESCE(SUM(vc.variants),0),MAX(pc.updated_at) FROM pc
                LEFT JOIN vc ON vc.supplier_id IS NOT DISTINCT FROM pc.supplier_id
                WHERE NOT EXISTS(SELECT 1 FROM suppliers s WHERE s.id=pc.supplier_id)
                HAVING SUM(pc.products)>0 ORDER BY products DESC,supplier_name""")
            categories=await conn.fetch("""SELECT CASE WHEN NULLIF(BTRIM(category),'') IS NULL OR LOWER(BTRIM(category))='uncategorized'
                THEN 'Uncategorized' ELSE BTRIM(category) END category,COUNT(*) count
                FROM products GROUP BY 1 ORDER BY count DESC,category LIMIT 8""")
            brands=await conn.fetch("""SELECT CASE WHEN NULLIF(BTRIM(brand),'') IS NULL OR LOWER(BTRIM(brand))='unbranded'
                THEN 'Unbranded' ELSE BTRIM(brand) END brand,COUNT(*) count
                FROM products GROUP BY 1 ORDER BY count DESC,brand LIMIT 8""")
            recent=await conn.fetch("""SELECT p.id,p.product_name,p.supplier_sku,p.brand,p.created_at,s.supplier_name
                FROM products p LEFT JOIN suppliers s ON s.id=p.supplier_id
                ORDER BY p.created_at DESC,p.id LIMIT 6""")
    return {**dict(row),'supplier_catalogues':[dict(r) for r in suppliers],
            'category_distribution':[dict(r) for r in categories],'brand_distribution':[dict(r) for r in brands],
            'recent_products':[dict(r) for r in recent],'as_of':datetime.now(timezone.utc)}
