"""Lightspeed (X-Series) routes: OAuth, test, categories, push."""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import RedirectResponse
import asyncio
import deps
from deps import row_to_dict, utc_now, get_current_user, calculate_sale_price, create_sync_log, update_sync_log
import logging
import secrets
import os
import json
import logging
from contextlib import suppress
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
FRONTEND_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
_oauth_states: dict = {}

async def _get_lightspeed_settings():
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT lightspeed_store_id, lightspeed_secret_token, lightspeed_client_id,
                   lightspeed_client_secret, lightspeed_access_token, lightspeed_refresh_token,
                   lightspeed_token_expires_at
            FROM settings WHERE id = 'system_settings'
        """)
    if not row:
        raise HTTPException(404, "Settings not found")
    return dict(row)

async def _get_ls_service():
    from lightspeed_service import LightspeedService

    s = await _get_lightspeed_settings()

    ls = await asyncio.to_thread(
        LightspeedService,
        domain_prefix=s.get("lightspeed_store_id") or "",
        personal_token=s.get("lightspeed_secret_token") or "",
        access_token=s.get("lightspeed_access_token") or "",
        client_id=s.get("lightspeed_client_id") or "",
        client_secret=s.get("lightspeed_client_secret") or "",
        refresh_token=s.get("lightspeed_refresh_token") or "",
        token_expires_at=s.get("lightspeed_token_expires_at"),
    )

    if ls.token_was_refreshed:
        async with deps.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE settings
                SET lightspeed_access_token = $1,
                    lightspeed_refresh_token = $2,
                    lightspeed_token_expires_at = $3,
                    updated_at = $4
                WHERE id = 'system_settings'
                """,
                ls.access_token,
                ls.refresh_token,
                ls.token_expires_at,
                utc_now(),
            )

    return ls

@router.get("/lightspeed/oauth/authorize")
async def lightspeed_oauth_authorize(request: Request, user: dict = Depends(get_current_user)):
    s = await _get_lightspeed_settings()
    client_id = s.get("lightspeed_client_id") or ""
    domain = s.get("lightspeed_store_id") or ""
    if not client_id:
        raise HTTPException(400, "Lightspeed Client ID (Public Key) not configured. Save it in Settings first.")
    if not domain:
        raise HTTPException(400, "Lightspeed Domain Prefix not configured. Save it in Settings first.")
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = True
    callback_url = f"{FRONTEND_URL}/api/lightspeed/oauth/callback"
    scopes = "products:read products:write inventory:read"
    auth_url = f"https://secure.retail.lightspeed.app/connect?response_type=code&client_id={client_id}&redirect_uri={callback_url}&state={state}&scope={scopes}"
    return {"authorize_url": auth_url, "state": state}

@router.get("/lightspeed/oauth/callback")
async def lightspeed_oauth_callback(code: str = None, state: str = None, error: str = None, domain_prefix: str = None):
    import requests as http_requests
    frontend_settings_url = f"{FRONTEND_URL}/settings"
    if error:
        logger.error(f"Lightspeed OAuth error: {error}")
        return RedirectResponse(f"{frontend_settings_url}?ls_oauth=error&message={error}")
    if not code:
        return RedirectResponse(f"{frontend_settings_url}?ls_oauth=error&message=No+authorization+code+received")
    if state and state in _oauth_states:
        del _oauth_states[state]
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT lightspeed_store_id, lightspeed_client_id, lightspeed_client_secret
            FROM settings WHERE id = 'system_settings'
        """)
    if not row:
        return RedirectResponse(f"{frontend_settings_url}?ls_oauth=error&message=Settings+not+found")
    domain = domain_prefix or row["lightspeed_store_id"] or ""
    client_id = row["lightspeed_client_id"] or ""
    client_secret = row["lightspeed_client_secret"] or ""
    if not all([domain, client_id, client_secret]):
        return RedirectResponse(f"{frontend_settings_url}?ls_oauth=error&message=Missing+client+credentials")
    callback_url = f"{FRONTEND_URL}/api/lightspeed/oauth/callback"
    token_url = f"https://{domain}.retail.lightspeed.app/api/1.0/token"
    try:
        resp = http_requests.post(token_url, data={
            "grant_type": "authorization_code", "code": code, "client_id": client_id,
            "client_secret": client_secret, "redirect_uri": callback_url
        }, timeout=30)
        if resp.status_code != 200:
            logger.error(f"Lightspeed token exchange failed ({resp.status_code}): {resp.text[:300]}")
            return RedirectResponse(f"{frontend_settings_url}?ls_oauth=error&message=Token+exchange+failed:+{resp.status_code}")
        token_data = resp.json()
        access_token = token_data.get("access_token", "")
        refresh_token = token_data.get("refresh_token", "")
        expires_in = int(token_data.get("expires_in", 86400))
        from datetime import datetime, timezone, timedelta
        expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=expires_in)
        async with deps.pool.acquire() as conn:
            if domain_prefix and domain_prefix != row["lightspeed_store_id"]:
                await conn.execute("""
                    UPDATE settings
                    SET lightspeed_access_token = $1, lightspeed_refresh_token = $2,
                        lightspeed_token_expires_at = $3, lightspeed_store_id = $4, updated_at = $5
                    WHERE id = 'system_settings'
                """, access_token, refresh_token, expires_at, domain_prefix, utc_now())
            else:
                await conn.execute("""
                    UPDATE settings
                    SET lightspeed_access_token = $1, lightspeed_refresh_token = $2,
                        lightspeed_token_expires_at = $3, updated_at = $4
                    WHERE id = 'system_settings'
                """, access_token, refresh_token, expires_at, utc_now())
        logger.info(f"Lightspeed OAuth tokens saved (expires in {expires_in}s)")
        return RedirectResponse(f"{frontend_settings_url}?ls_oauth=success")
    except Exception as e:
        logger.error(f"Lightspeed OAuth token exchange error: {e}")
        return RedirectResponse(f"{frontend_settings_url}?ls_oauth=error&message=Token+exchange+error")

@router.post("/lightspeed/oauth/disconnect")
async def lightspeed_oauth_disconnect(user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        await conn.execute("""
            UPDATE settings
            SET lightspeed_access_token = '', lightspeed_refresh_token = '',
                lightspeed_token_expires_at = NULL, updated_at = $1
            WHERE id = 'system_settings'
        """, utc_now())
    return {"status": "disconnected", "success": True}

@router.post("/settings/lightspeed/test")
async def test_lightspeed_connection(user: dict = Depends(get_current_user)):
    ls = await _get_ls_service()
    result = ls.test_connection()
    if ls.token_was_refreshed:
        async with deps.pool.acquire() as conn:
            await conn.execute("""
                UPDATE settings
                SET lightspeed_access_token = $1, lightspeed_token_expires_at = $2, updated_at = $3
                WHERE id = 'system_settings'
            """, ls.access_token, ls.token_expires_at, utc_now())
    return result

_category_refresh_task = None
_category_refresh_lock = asyncio.Lock()
_category_logger = logging.getLogger(__name__)

CATEGORY_REFRESH_SECONDS = 300


async def _category_store_key(conn):
    value = await conn.fetchval("""
        SELECT lightspeed_store_id
        FROM settings
        WHERE id = 'system_settings'
    """)
    return str(value or "").strip().lower()


async def _refresh_category_snapshot():
    # Prevent concurrent refreshes within this backend process.
    if _category_refresh_lock.locked():
        return

    async with _category_refresh_lock:
        async with deps.pool.acquire() as conn:
            store = await _category_store_key(conn)

        if not store:
            return

        try:
            ls = await _get_ls_service()
            result = await asyncio.to_thread(ls.get_categories)

            if not isinstance(result, dict) or not result.get("success"):
                raise ValueError("Lightspeed category request failed")

            categories = result.get("categories")
            if not isinstance(categories, list):
                raise ValueError("Invalid Lightspeed category response")

            seen = set()

            for category in categories:
                if not isinstance(category, dict):
                    raise ValueError("Invalid category record")

                category_id = category.get("lightspeed_category_id")

                if not category_id or not category.get("category_name"):
                    raise ValueError("Category ID or name is missing")

                if category_id in seen:
                    raise ValueError("Duplicate category ID")

                seen.add(category_id)

            async with deps.pool.acquire() as conn:
                # Do not save results under a different store.
                if await _category_store_key(conn) != store:
                    return

                await conn.execute("""
                    INSERT INTO lightspeed_category_snapshots
                        (store_domain, categories, synced_at, last_error)
                    VALUES ($1, $2::jsonb, NOW(), NULL)
                    ON CONFLICT (store_domain)
                    DO UPDATE SET
                        categories = EXCLUDED.categories,
                        synced_at = EXCLUDED.synced_at,
                        last_error = NULL
                """, store, json.dumps(categories))

        except asyncio.CancelledError:
            raise

        except Exception:
            _category_logger.exception("Category refresh failed")

            async with deps.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO lightspeed_category_snapshots
                        (store_domain, last_error)
                    VALUES ($1, $2)
                    ON CONFLICT (store_domain)
                    DO UPDATE SET last_error = EXCLUDED.last_error
                """, store, "Refresh failed; previously saved categories retained.")


async def _category_refresh_loop():
    while True:
        try:
            await _refresh_category_snapshot()
        except asyncio.CancelledError:
            raise
        except Exception:
            _category_logger.exception("Category refresh worker failed")

        await asyncio.sleep(CATEGORY_REFRESH_SECONDS)


async def start_category_refresh():
    global _category_refresh_task

    async with deps.pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS lightspeed_category_snapshots (
                store_domain TEXT PRIMARY KEY,
                categories JSONB NOT NULL DEFAULT '[]'::jsonb,
                synced_at TIMESTAMPTZ,
                last_error TEXT
            )
        """)

    if _category_refresh_task is None or _category_refresh_task.done():
        _category_refresh_task = asyncio.create_task(
            _category_refresh_loop()
        )


async def stop_category_refresh():
    global _category_refresh_task

    if _category_refresh_task:
        _category_refresh_task.cancel()

        with suppress(asyncio.CancelledError):
            await _category_refresh_task

        _category_refresh_task = None


@router.get("/categories/lightspeed")
async def get_lightspeed_categories(
    user: dict = Depends(get_current_user)
):
    # This endpoint reads PostgreSQL; it does not call Lightspeed.
    async with deps.pool.acquire() as conn:
        store = await _category_store_key(conn)

        row = await conn.fetchrow("""
            SELECT categories, synced_at, last_error
            FROM lightspeed_category_snapshots
            WHERE store_domain = $1
        """, store)

    categories = row["categories"] if row else []

    if isinstance(categories, str):
        categories = json.loads(categories)

    return {
        "success": True,
        "categories": categories,
        "synced_at": row["synced_at"] if row else None,
        "last_error": row["last_error"] if row else None,
    }


@router.post("/categories/lightspeed/refresh")
async def refresh_lightspeed_categories(
    user: dict = Depends(get_current_user)
):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")

    await _refresh_category_snapshot()

    return await get_lightspeed_categories(user)

@router.post("/sync/lightspeed/{supplier_id}")
async def push_to_lightspeed(supplier_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        supplier = await conn.fetchrow("SELECT supplier_name FROM suppliers WHERE id = $1", supplier_id)
        if not supplier:
            raise HTTPException(404, "Supplier not found")
        count = await conn.fetchval("""
            SELECT COUNT(*)
            FROM products
            WHERE selected_for_lightspeed = TRUE
              AND lightspeed_sync_status = 'pending'
              AND supplier_id = $1
        """, supplier_id)
    log_id = await create_sync_log(
        supplier_id, supplier["supplier_name"], "lightspeed_push",
        f"Pushing {count} products to Lightspeed..."
    )
    background_tasks.add_task(lightspeed_push_task, supplier_id, log_id)
    return {"status": "started", "log_id": log_id, "products_to_push": count}

async def _process_lightspeed_product(ls, product, variants, images, markup):
    from taxonomy_resolution import resolve_category
    from export_safety import export_product
    product_data = row_to_dict(product)
    variant_data = [row_to_dict(v) for v in variants if v.get('is_active') is not False]
    image_data = [row_to_dict(image) for image in images]
    async with deps.pool.acquire() as conn:
        managed, category_id, error = await resolve_category(
            conn, product_data['supplier_id'], product_data['supplier_sku']
        )
    if managed and error:
        return {'success': False, 'error': error}
    if not managed:
        async with deps.pool.acquire() as conn:
            category_id = await conn.fetchval('''
                SELECT lightspeed_category_id FROM category_mapping
                WHERE supplier_category_name=$1
                  AND lightspeed_category_id IS NOT NULL
                  AND lightspeed_category_id<>''
                ORDER BY updated_at DESC LIMIT 1
            ''', product_data.get('category') or '')
    if not category_id:
        return {'success': False, 'error': 'Map or publish the Lightspeed category first'}
    try:
        return await export_product(ls, product_data, variant_data, image_data, markup, category_id)
    except ValueError as exc:
        return {'success': False, 'error': str(exc)}



async def lightspeed_push_task(supplier_id: str, log_id: str):
    from lightspeed_service import LightspeedService
    try:
        async with deps.pool.acquire() as conn:
            settings_row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
            settings = row_to_dict(settings_row)
            markup = float(settings["markup_percentage"]) if settings.get("markup_percentage") is not None else 40.0
            products = await conn.fetch("""
                SELECT p.*, cm.lightspeed_category_id, s.supplier_name
                FROM products p
                LEFT JOIN category_mapping cm ON p.category = cm.supplier_category_name
                LEFT JOIN suppliers s ON p.supplier_id = s.id
                WHERE p.selected_for_lightspeed = TRUE
                  AND p.lightspeed_sync_status = 'pending'
                  AND p.supplier_id = $1
            """, supplier_id)
        if not products:
            await update_sync_log(log_id, "completed", "No pending products for Lightspeed", progress=100)
            return
        ls = LightspeedService(
            domain_prefix=settings.get("lightspeed_store_id", ""),
            personal_token=settings.get("lightspeed_secret_token", ""),
            access_token=settings.get("lightspeed_access_token", ""),
            client_id=settings.get("lightspeed_client_id", ""),
            client_secret=settings.get("lightspeed_client_secret", ""),
            refresh_token=settings.get("lightspeed_refresh_token", ""),
            token_expires_at=settings_row["lightspeed_token_expires_at"] if settings_row else None,
        )
        conn_test = await asyncio.to_thread(ls.test_connection)
        if not conn_test.get("connected"):
            await update_sync_log(log_id, "failed", f"Lightspeed connection failed: {conn_test.get('message')}")
            return
        if ls.token_was_refreshed:
            async with deps.pool.acquire() as conn:
                await conn.execute("""
                    UPDATE settings
                    SET lightspeed_access_token = $1, lightspeed_token_expires_at = $2, updated_at = $3
                    WHERE id = 'system_settings'
                """, ls.access_token, ls.token_expires_at, utc_now())
        product_ids = [p["id"] for p in products]
        async with deps.pool.acquire() as conn:
            variants_rows = await conn.fetch("""
                SELECT * FROM product_variants
                WHERE product_id = ANY($1::varchar[])
            """, product_ids)
            media_rows = await conn.fetch("""
                SELECT * FROM product_media
                WHERE product_id = ANY($1::varchar[])
            """, product_ids)
        variants_by_product = {}
        for variant in variants_rows:
            variants_by_product.setdefault(str(variant["product_id"]), []).append(variant)
        media_by_product = {}
        for media in media_rows:
            media_by_product.setdefault(str(media["product_id"]), []).append(media)
        total = len(products)
        synced = 0
        failed = 0
        semaphore = asyncio.Semaphore(5)
        async def process(index, product):
            nonlocal synced, failed
            async with semaphore:
                try:
                    pid = str(product["id"])
                    result = await _process_lightspeed_product(
                        ls, product,
                        variants_by_product.get(pid, []),
                        media_by_product.get(pid, []),
                        markup
                    )
                    if result.get("success"):
                        async with deps.pool.acquire() as conn:
                            await conn.execute("""
                                UPDATE products
                                SET lightspeed_sync_status = 'synced',
                                    lightspeed_product_id = $1,
                                    updated_at = $2
                                WHERE id = $3
                            """, str(result.get("lightspeed_id", "")), utc_now(), product["id"])
                        synced += 1
                    else:
                        async with deps.pool.acquire() as conn:
                            await conn.execute("""
                                UPDATE products
                                SET lightspeed_sync_status = 'failed',
                                    updated_at = $1
                                WHERE id = $2
                            """, utc_now(), product["id"])
                        failed += 1
                    processed = index + 1
                    progress = int((processed / total) * 100)
                    await update_sync_log(
                        log_id, "running",
                        f"Pushed {synced}/{total} to Lightspeed ({failed} failed)",
                        progress=progress, total=total, processed=synced
                    )
                except Exception as e:
                    logger.exception(f"Lightspeed product sync failed: {product.get('id')}: {e}")
                    failed += 1
                    async with deps.pool.acquire() as conn:
                        await conn.execute("""
                            UPDATE products
                            SET lightspeed_sync_status = 'failed', updated_at = $1
                            WHERE id = $2
                        """, utc_now(), product["id"])
        await asyncio.gather(*(process(i, p) for i, p in enumerate(products)))
        msg = f"Lightspeed push complete: {synced} synced, {failed} failed out of {total}"
        await update_sync_log(log_id, "completed", msg, progress=100, total=total, processed=synced)
        logger.info(msg)
    except Exception as e:
        logger.exception(f"Lightspeed push error: {e}")
        await update_sync_log(log_id, "failed", f"Error: {str(e)}")