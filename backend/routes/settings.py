"""Settings and scheduler routes."""
from fastapi import APIRouter, Depends, HTTPException
import deps
from deps import row_to_dict, utc_now, get_current_user, get_admin_user
from models import SettingsUpdate

router = APIRouter(prefix="/api")


@router.get("/settings")
async def get_settings(user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
        if not row:
            return {
                "id": "system_settings", "odoo_url": "", "odoo_db": "", "odoo_username": "", "odoo_api_key": "",
                "odoo_connected": False, "sync_products_interval_hours": 24, "sync_inventory_interval_minutes": 30,
                "sync_pricing_interval_hours": 12, "auto_sync_enabled": False, "preferred_warehouse": "MISSISSAUGA/ON"
            }
        s = row_to_dict(row)
        has_access_token = bool(s.get('lightspeed_access_token'))
        if s.get('odoo_api_key'): s['odoo_api_key'] = '***'
        if s.get('lightspeed_secret_token'): s['lightspeed_secret_token'] = '***'
        if s.get('lightspeed_client_secret'): s['lightspeed_client_secret'] = '***'
        if s.get('lightspeed_access_token'): s['lightspeed_access_token'] = '***'
        if s.get('lightspeed_refresh_token'): s['lightspeed_refresh_token'] = '***'
        s['lightspeed_oauth_connected'] = has_access_token
        for old_field in ('lightspeed_api_key', 'lightspeed_api_secret', 'lightspeed_cluster', 'lightspeed_language'):
            s.pop(old_field, None)
        return s


@router.put("/settings")
async def update_settings(data: SettingsUpdate, user: dict = Depends(get_admin_user)):
    async with deps.pool.acquire() as conn:
        update_fields = []; values = []; param_idx = 1
        for field in ['sync_products_interval_hours', 'sync_inventory_interval_minutes', 'sync_pricing_interval_hours',
                      'auto_sync_enabled', 'odoo_url', 'odoo_db', 'odoo_username', 'preferred_warehouse', 'markup_percentage',
                      'auto_push_to_odoo', 'lightspeed_store_id', 'lightspeed_client_id']:
            val = getattr(data, field, None)
            if val is not None:
                update_fields.append(f"{field} = ${param_idx}"); values.append(val); param_idx += 1
        if data.odoo_api_key and data.odoo_api_key != '***':
            update_fields.append(f"odoo_api_key = ${param_idx}"); values.append(data.odoo_api_key); param_idx += 1
        if data.lightspeed_secret_token and data.lightspeed_secret_token != '***':
            update_fields.append(f"lightspeed_secret_token = ${param_idx}"); values.append(data.lightspeed_secret_token); param_idx += 1
        if data.lightspeed_client_secret and data.lightspeed_client_secret != '***':
            update_fields.append(f"lightspeed_client_secret = ${param_idx}"); values.append(data.lightspeed_client_secret); param_idx += 1
        update_fields.append(f"updated_at = ${param_idx}"); values.append(utc_now()); param_idx += 1
        if update_fields:
            query = f"UPDATE settings SET {', '.join(update_fields)} WHERE id = 'system_settings'"
            await conn.execute(query, *values)
        from scheduler import apply_schedule_from_settings
        await apply_schedule_from_settings()
        return {"status": "updated", "success": True}


@router.get("/settings/warehouses")
async def get_available_warehouses(user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT jsonb_array_elements(warehouse_inventory)->>'name' as name
            FROM product_variants
            WHERE warehouse_inventory != '[]'::jsonb AND warehouse_inventory IS NOT NULL
        """)
        warehouses = sorted(set(r['name'] for r in rows if r['name']))
        return {"warehouses": warehouses}


@router.get("/scheduler/status")
async def scheduler_status(user: dict = Depends(get_current_user)):
    from scheduler import get_scheduler_status
    return get_scheduler_status()


@router.post("/scheduler/reschedule")
async def reschedule_jobs(user: dict = Depends(get_admin_user)):
    from scheduler import apply_schedule_from_settings
    await apply_schedule_from_settings()
    from scheduler import get_scheduler_status
    return {"status": "rescheduled", **get_scheduler_status()}
