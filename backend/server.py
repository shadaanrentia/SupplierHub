"""SupplierHub - PromoStandards Middleware (FastAPI)
Slim entrypoint: startup/shutdown, CORS, router registration.
All route logic lives in /routes/*.py, shared deps in deps.py, models in models.py.
"""
from fastapi import FastAPI, APIRouter
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import asyncpg
import os
import json
import logging
from pathlib import Path
import subprocess
import sys
import time as _time

import deps
from deps import new_id, hash_password, utc_now

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://supplierhub:supplierhub_pass@localhost:5432/supplierhub_db')

app = FastAPI(title="SupplierHub - PromoStandards Middleware")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _ensure_postgresql():
    """Auto-start PostgreSQL if running locally. Skip if DATABASE_URL points to an external host (e.g. Docker)."""
    from urllib.parse import urlparse
    parsed = urlparse(DATABASE_URL)
    host = parsed.hostname or 'localhost'

    # If database host is not localhost, assume external (Docker/cloud) — skip local management
    if host not in ('localhost', '127.0.0.1'):
        logger.info(f"PostgreSQL host is '{host}' (external) — skipping local management")
        return True

    if sys.platform.startswith('win'):
        logger.info("Running on Windows; skipping Linux-specific PostgreSQL auto-install/start logic")
        return True

    pg_running = False

    for attempt in range(3):
        # Check if already running
        try:
            result = subprocess.run(["pg_isready", "-h", "localhost"], capture_output=True, timeout=5)
            if result.returncode == 0:
                pg_running = True
                break
        except FileNotFoundError:
            # pg_isready not found — PostgreSQL not installed
            logger.warning("PostgreSQL not installed, installing...")
            subprocess.run(["apt-get", "update", "-qq"], capture_output=True, timeout=60)
            subprocess.run(["apt-get", "install", "-y", "-qq", "postgresql", "postgresql-client"],
                           capture_output=True, timeout=120)
            _time.sleep(2)
            continue
        except Exception:
            pass

        logger.warning(f"PostgreSQL not ready, attempting start (attempt {attempt+1}/3)")

        # Check if cluster exists
        try:
            cluster_check = subprocess.run(["pg_lsclusters", "--no-header"], capture_output=True, text=True, timeout=5)
            cluster_output = cluster_check.stdout.strip()
        except FileNotFoundError:
            logger.warning("pg_lsclusters not found, installing postgresql...")
            subprocess.run(["apt-get", "install", "-y", "-qq", "postgresql", "postgresql-client"],
                           capture_output=True, timeout=120)
            _time.sleep(2)
            cluster_output = ""
        except Exception:
            cluster_output = ""

        if not cluster_output or "15" not in cluster_output:
            logger.info("PostgreSQL cluster missing, creating...")
            r = subprocess.run(["id", "postgres"], capture_output=True, timeout=5)
            if r.returncode != 0:
                subprocess.run(["useradd", "-r", "-s", "/bin/bash", "-d", "/var/lib/postgresql", "postgres"],
                               capture_output=True, timeout=10)
            for d in ["/var/lib/postgresql/15/main", "/var/run/postgresql", "/var/log/postgresql"]:
                subprocess.run(["mkdir", "-p", d], capture_output=True, timeout=5)
            subprocess.run(["chown", "-R", "postgres:postgres", "/var/lib/postgresql", "/var/run/postgresql", "/var/log/postgresql"],
                           capture_output=True, timeout=10)
            try:
                subprocess.run(["pg_createcluster", "15", "main", "--start"], capture_output=True, timeout=60)
            except FileNotFoundError:
                logger.error("pg_createcluster not found even after install attempt")
            _time.sleep(3)
        else:
            subprocess.run(["pg_ctlcluster", "15", "main", "start"], capture_output=True, timeout=30)
            _time.sleep(3)

        try:
            result = subprocess.run(["pg_isready", "-h", "localhost"], capture_output=True, timeout=5)
            if result.returncode == 0:
                pg_running = True
                break
        except Exception:
            pass

    if not pg_running:
        logger.error("Failed to start PostgreSQL after 3 attempts")
        return False

    # ALWAYS ensure DB user and database exist
    logger.info("Ensuring supplierhub user and database exist...")
    r = subprocess.run(["sudo", "-u", "postgres", "psql", "-tAc",
                        "SELECT 1 FROM pg_roles WHERE rolname='supplierhub'"],
                       capture_output=True, text=True, timeout=10)
    if "1" not in (r.stdout or ""):
        logger.info("Creating supplierhub user...")
        subprocess.run(["sudo", "-u", "postgres", "psql", "-c",
                        "CREATE USER supplierhub WITH PASSWORD 'supplierhub_pass' CREATEDB;"],
                       capture_output=True, timeout=10)

    r = subprocess.run(["sudo", "-u", "postgres", "psql", "-tAc",
                        "SELECT 1 FROM pg_catalog.pg_database WHERE datname='supplierhub_db'"],
                       capture_output=True, text=True, timeout=10)
    if "1" not in (r.stdout or ""):
        logger.info("Creating supplierhub_db database...")
        subprocess.run(["sudo", "-u", "postgres", "psql", "-c",
                        "CREATE DATABASE supplierhub_db OWNER supplierhub;"],
                       capture_output=True, timeout=10)

    logger.info("PostgreSQL is ready")
    return True


# ==================== STARTUP & SHUTDOWN ====================
@app.on_event("startup")
async def startup():
    _ensure_postgresql()
    deps.pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    pool = deps.pool

    async with pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR(64) PRIMARY KEY, username VARCHAR(100) UNIQUE NOT NULL,
                full_name VARCHAR(200), email VARCHAR(200) UNIQUE,
                hashed_password TEXT NOT NULL, role VARCHAR(50) DEFAULT 'user',
                approved BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS suppliers (
                id VARCHAR(64) PRIMARY KEY, supplier_name VARCHAR(200) NOT NULL,
                supplier_type VARCHAR(100), api_base_url TEXT, account_number VARCHAR(100),
                password TEXT, media_password TEXT, use_uat BOOLEAN DEFAULT FALSE,
                endpoint_style VARCHAR(50), services JSONB DEFAULT '{}', bulk_data_url TEXT,
                is_active BOOLEAN DEFAULT TRUE, status VARCHAR(50) DEFAULT 'active',
                last_sync TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id VARCHAR(64) PRIMARY KEY, supplier_id VARCHAR(64) REFERENCES suppliers(id) ON DELETE CASCADE,
                supplier_sku VARCHAR(200) NOT NULL, product_name TEXT, description TEXT,
                brand VARCHAR(200), category VARCHAR(200), base_price DECIMAL(10,2) DEFAULT 0,
                currency VARCHAR(10) DEFAULT 'CAD', is_active BOOLEAN DEFAULT TRUE,
                selected_for_odoo BOOLEAN DEFAULT FALSE, odoo_sync_status VARCHAR(50) DEFAULT 'not_selected',
                odoo_product_id VARCHAR(100), last_synced TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(supplier_id, supplier_sku)
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS product_variants (
                id VARCHAR(64) PRIMARY KEY, product_id VARCHAR(64) REFERENCES products(id) ON DELETE CASCADE,
                variant_sku VARCHAR(200) NOT NULL, color VARCHAR(200), size VARCHAR(100),
                price DECIMAL(10,2) DEFAULT 0, inventory INTEGER DEFAULT 0,
                warehouse_inventory JSONB DEFAULT '[]', lead_time INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS product_media (
                id VARCHAR(64) PRIMARY KEY, product_id VARCHAR(64) REFERENCES products(id) ON DELETE CASCADE,
                media_type VARCHAR(50) DEFAULT 'image', url TEXT NOT NULL, description TEXT,
                is_primary BOOLEAN DEFAULT FALSE, image_base64 TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS sync_logs (
                id VARCHAR(64) PRIMARY KEY, supplier_id VARCHAR(64), supplier_name VARCHAR(200),
                sync_type VARCHAR(50) NOT NULL, status VARCHAR(50) DEFAULT 'pending',
                message TEXT, progress INTEGER DEFAULT 0, total_items INTEGER DEFAULT 0,
                processed_items INTEGER DEFAULT 0, start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                end_time TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id VARCHAR(64) PRIMARY KEY, odoo_url TEXT, odoo_db VARCHAR(200),
                odoo_username VARCHAR(200), odoo_api_key TEXT, odoo_connected BOOLEAN DEFAULT FALSE,
                sync_products_interval_hours INTEGER DEFAULT 24, sync_inventory_interval_minutes INTEGER DEFAULT 30,
                sync_pricing_interval_hours INTEGER DEFAULT 12, auto_sync_enabled BOOLEAN DEFAULT FALSE,
                preferred_warehouse VARCHAR(200) DEFAULT 'MISSISSAUGA/ON',
                markup_percentage DECIMAL(5,2) DEFAULT 40.00,
                default_warehouse VARCHAR(200) DEFAULT 'Main Warehouse',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Indexes
        for idx in ['CREATE INDEX IF NOT EXISTS idx_products_supplier ON products(supplier_id)',
                     'CREATE INDEX IF NOT EXISTS idx_products_sku ON products(supplier_sku)',
                     'CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand)',
                     'CREATE INDEX IF NOT EXISTS idx_products_category ON products(category)',
                     'CREATE INDEX IF NOT EXISTS idx_variants_product ON product_variants(product_id)',
                     'CREATE INDEX IF NOT EXISTS idx_media_product ON product_media(product_id)']:
            await conn.execute(idx)

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS odoo_categories (
                id VARCHAR(64) PRIMARY KEY, odoo_category_id INTEGER NOT NULL UNIQUE,
                category_name VARCHAR(300) NOT NULL, parent_category VARCHAR(300),
                parent_id INTEGER, is_selected BOOLEAN DEFAULT FALSE,
                last_synced TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS category_mapping (
                id VARCHAR(64) PRIMARY KEY, supplier_category_name VARCHAR(300) NOT NULL UNIQUE,
                supplier_category_id VARCHAR(100), odoo_category_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS product_sync_status (
                id VARCHAR(64) PRIMARY KEY, product_id VARCHAR(64) REFERENCES products(id) ON DELETE CASCADE,
                supplier_id VARCHAR(64), odoo_product_id VARCHAR(100), odoo_template_id INTEGER,
                sync_status VARCHAR(50) DEFAULT 'pending', cost_price DECIMAL(10,2), sale_price DECIMAL(10,2),
                mapped_category_id INTEGER, variants_count INTEGER DEFAULT 0, images_count INTEGER DEFAULT 0,
                validation_errors JSONB DEFAULT '[]', last_sync_date TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(product_id)
            )
        ''')

        # ALTER TABLE additions
        for alt in [
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS preprocessing_status VARCHAR(50) DEFAULT 'pending'",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS calculated_sale_price DECIMAL(10,2)",
            "ALTER TABLE settings ADD COLUMN IF NOT EXISTS markup_percentage DECIMAL(5,2) DEFAULT 40.00",
            "ALTER TABLE settings ADD COLUMN IF NOT EXISTS default_warehouse VARCHAR(200) DEFAULT 'Main Warehouse'",
            "ALTER TABLE settings ADD COLUMN IF NOT EXISTS auto_push_to_odoo BOOLEAN DEFAULT FALSE",
            "ALTER TABLE settings ADD COLUMN IF NOT EXISTS lightspeed_store_id VARCHAR(100) DEFAULT ''",
            "ALTER TABLE settings ADD COLUMN IF NOT EXISTS lightspeed_secret_token VARCHAR(500) DEFAULT ''",
            "ALTER TABLE category_mapping ADD COLUMN IF NOT EXISTS lightspeed_category_id TEXT",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS lightspeed_sync_status VARCHAR(50) DEFAULT 'pending'",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS lightspeed_product_id VARCHAR(100)",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS selected_for_lightspeed BOOLEAN DEFAULT FALSE",
            "ALTER TABLE settings ADD COLUMN IF NOT EXISTS lightspeed_client_id VARCHAR(200) DEFAULT ''",
            "ALTER TABLE settings ADD COLUMN IF NOT EXISTS lightspeed_client_secret VARCHAR(500) DEFAULT ''",
            "ALTER TABLE settings ADD COLUMN IF NOT EXISTS lightspeed_access_token TEXT DEFAULT ''",
            "ALTER TABLE settings ADD COLUMN IF NOT EXISTS lightspeed_refresh_token TEXT DEFAULT ''",
            "ALTER TABLE settings ADD COLUMN IF NOT EXISTS lightspeed_token_expires_at TIMESTAMP",
        ]:
            await conn.execute(alt)

        from taxonomy_schema import init_taxonomy_schema
        await init_taxonomy_schema(conn)
        from product_name_schema import init_product_name_schema
        await init_product_name_schema(conn)
        from export_safety import init_export_safety_schema
        from routes.export_review import init_export_review_schema

        await init_export_safety_schema(conn)
        await init_export_review_schema(conn)

        await conn.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS source_metadata JSONB DEFAULT '{}'::jsonb; ALTER TABLE products ADD COLUMN IF NOT EXISTS source_product_type TEXT; ALTER TABLE products ADD COLUMN IF NOT EXISTS standard_inventory INTEGER")
        from routes.sync import init_sync_schema
        await init_sync_schema(conn)

        # Persistent Lightspeed image synchronization jobs
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS lightspeed_image_jobs (
                id VARCHAR(64) PRIMARY KEY,
                product_id VARCHAR(64) REFERENCES products(id) ON DELETE CASCADE,
                lightspeed_product_id VARCHAR(100) NOT NULL,
                status VARCHAR(30) DEFAULT 'pending',
                total_images INTEGER DEFAULT 0,
                uploaded_images INTEGER DEFAULT 0,
                failed_images INTEGER DEFAULT 0,
                current_image TEXT,
                error_message TEXT,
                retry_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        await conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_ls_image_jobs_status '
            'ON lightspeed_image_jobs(status)'
        )

        await conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_ls_image_jobs_product '
            'ON lightspeed_image_jobs(product_id)'
        )

        # Migration: change lightspeed_category_id from INTEGER to TEXT if needed
        try:
            col_type = await conn.fetchval("""
                SELECT data_type FROM information_schema.columns
                WHERE table_name = 'category_mapping' AND column_name = 'lightspeed_category_id'
            """)
            if col_type and col_type != 'text':
                await conn.execute("ALTER TABLE category_mapping ALTER COLUMN lightspeed_category_id TYPE TEXT USING lightspeed_category_id::TEXT")
                logger.info("Migrated lightspeed_category_id from INTEGER to TEXT")
        except Exception as e:
            logger.warning(f"lightspeed_category_id migration check: {e}")

        # Default admin user
        admin = await conn.fetchrow("SELECT id FROM users WHERE username = 'admin'")
        if not admin:
            await conn.execute('''
                INSERT INTO users (id, username, full_name, email, hashed_password, role, approved)
                VALUES ($1, 'admin', 'Shadaan Rentia', 'admin@supplierhub.com', $2, 'admin', TRUE)
            ''', new_id(), hash_password('admin'))
            logger.info("Default admin user created: admin/admin")

        # Default settings
        settings = await conn.fetchrow("SELECT id FROM settings WHERE id = 'system_settings'")
        if not settings:
            await conn.execute('''
                INSERT INTO settings (id, odoo_url, odoo_db, odoo_username, odoo_api_key, preferred_warehouse)
                VALUES ('system_settings', '', '', '', '', 'MISSISSAUGA/ON')
            ''')

    logger.info("PostgreSQL database initialized")
    from scheduler import init_scheduler, apply_schedule_from_settings
    init_scheduler(deps.pool)
    await apply_schedule_from_settings()

    await start_category_refresh()
    from lightspeed_jobs import start_worker
    await start_worker()


@app.on_event("shutdown")
async def shutdown():
    from scheduler import shutdown_scheduler

    from lightspeed_jobs import stop_worker
    await stop_worker()
    shutdown_scheduler()
    await stop_category_refresh()

    if deps.pool:
        await deps.pool.close()


# ==================== CORS ====================
origins = os.environ.get('CORS_ORIGINS', '*')
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins.split(',') if origins != '*' else ['*'],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)


# ==================== HEALTH CHECK ====================
health_router = APIRouter(prefix="/api")

@health_router.get("/health")
async def health_check():
    from deps import utc_now_str
    return {"status": "healthy", "database": "postgresql", "timestamp": utc_now_str()}

app.include_router(health_router)


# ==================== REGISTER ROUTE MODULES ====================
from routes.auth import router as auth_router
from routes.suppliers import router as suppliers_router
from routes.products import router as products_router
from routes.dashboard import router as dashboard_router
from routes.settings import router as settings_router
from routes.sync import router as sync_router, init_sync_schema
from routes.odoo import router as odoo_router
from routes.lightspeed import (
    router as lightspeed_router,
    start_category_refresh,
    stop_category_refresh,
)
from routes.categories import router as categories_router
from routes.taxonomy import router as taxonomy_router
from taxonomy_extensions import router as taxonomy_extensions_router
from lightspeed_jobs import router as lightspeed_jobs_router
from routes.preprocessing import router as preprocessing_router
from routes.media import router as media_router
from routes.export_review import router as export_review_router

for r in [auth_router, suppliers_router, products_router, dashboard_router,
          settings_router, sync_router, odoo_router, lightspeed_router,
          categories_router, taxonomy_router,taxonomy_extensions_router, preprocessing_router, media_router, export_review_router, lightspeed_jobs_router]:
    app.include_router(r)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

