"""Dashboard routes."""
from fastapi import APIRouter, Depends
import deps
from deps import row_to_dict, get_current_user
router = APIRouter(prefix="/api")
@router.get("/dashboard/stats")
async def get_dashboard_stats(user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        total_products = await conn.fetchval("SELECT COUNT(*) FROM products")
        total_suppliers = await conn.fetchval("SELECT COUNT(*) FROM suppliers")
        active_suppliers = await conn.fetchval("SELECT COUNT(*) FROM suppliers WHERE status = 'active'")
        synced_lightspeed = await conn.fetchval("SELECT COUNT(*) FROM products WHERE lightspeed_sync_status = 'synced'")
        pending_lightspeed = await conn.fetchval("SELECT COUNT(*) FROM products WHERE lightspeed_sync_status = 'pending'")
        failed_lightspeed = await conn.fetchval("SELECT COUNT(*) FROM products WHERE lightspeed_sync_status = 'failed'")
        total_variants = await conn.fetchval("SELECT COUNT(*) FROM product_variants")
        active_products = await conn.fetchval("SELECT COUNT(*) FROM products WHERE is_active = TRUE")
        category_rows = await conn.fetch("SELECT COALESCE(category, 'Uncategorized') as category, COUNT(*) as count FROM products GROUP BY category ORDER BY count DESC LIMIT 10")
        brand_rows = await conn.fetch("SELECT COALESCE(brand, 'Unknown') as brand, COUNT(*) as count FROM products GROUP BY brand ORDER BY count DESC LIMIT 10")
        supplier_rows = await conn.fetch("SELECT s.supplier_name as supplier, COUNT(p.id) as count FROM suppliers s LEFT JOIN products p ON p.supplier_id = s.id GROUP BY s.id, s.supplier_name ORDER BY count DESC")
        from product_readiness import load_readiness
        products=[row_to_dict(r) for r in await conn.fetch('SELECT * FROM products')]
        states=await load_readiness(conn,products)
        ready=sum(s['status']=='ready' for s in states.values() if not s['excluded_from_queue'])
        review=sum(s['status']=='invalid' for s in states.values() if not s['excluded_from_queue'])
        images_pending=sum(s['status']=='images_pending' for s in states.values())
        return {
            "total_products": total_products,
            "ready_for_lightspeed": ready,
            "review_products": review,
            "images_pending_lightspeed": images_pending,
            "synced_to_lightspeed": synced_lightspeed,
            "pending_lightspeed": pending_lightspeed,
            "failed_lightspeed": failed_lightspeed,
            "total_suppliers": total_suppliers,
            "active_suppliers": active_suppliers,
            "total_variants": total_variants,
            "active_products": active_products,
            "category_distribution": [{"category": r["category"][:20], "count": r["count"]} for r in category_rows],
            "brand_distribution": [{"brand": r["brand"][:15], "count": r["count"]} for r in brand_rows],
            "supplier_distribution": [{"supplier": r["supplier"][:15], "count": r["count"]} for r in supplier_rows],
        }