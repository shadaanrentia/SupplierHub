"""Additive, repeatable PostgreSQL migration used by server.py startup."""
async def init_taxonomy_schema(conn):
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS supplier_taxonomy_imports (
            supplier_id VARCHAR(64) PRIMARY KEY REFERENCES suppliers(id) ON DELETE CASCADE,
            digest TEXT NOT NULL, filename TEXT NOT NULL, summary JSONB NOT NULL,
            labels JSONB NOT NULL, warnings JSONB NOT NULL,
            imported_by VARCHAR(64), updated_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS supplier_taxonomy_nodes (
            supplier_id VARCHAR(64) NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
            path TEXT NOT NULL, data JSONB NOT NULL,
            PRIMARY KEY (supplier_id, path)
        );
        CREATE TABLE IF NOT EXISTS supplier_taxonomy_styles (
            supplier_id VARCHAR(64) NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
            sku_key VARCHAR(200) NOT NULL, data JSONB NOT NULL,
            PRIMARY KEY (supplier_id, sku_key)
        );
        CREATE TABLE IF NOT EXISTS supplier_taxonomy_overrides (
            supplier_id VARCHAR(64) NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
            sku_key VARCHAR(200) NOT NULL, path TEXT, updated_by VARCHAR(64),
            updated_at TIMESTAMP DEFAULT NOW(), PRIMARY KEY(supplier_id, sku_key)
        );
        CREATE TABLE IF NOT EXISTS supplier_taxonomy_destinations (
            supplier_id VARCHAR(64) NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
            path TEXT NOT NULL, store_domain TEXT NOT NULL, category_id TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW(), PRIMARY KEY (supplier_id, path, store_domain)
        );
        CREATE TABLE IF NOT EXISTS supplier_taxonomy_jobs (
            id VARCHAR(64) PRIMARY KEY, supplier_id VARCHAR(64) REFERENCES suppliers(id) ON DELETE CASCADE,
            kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            digest TEXT NOT NULL, store_domain TEXT NOT NULL, items JSONB NOT NULL,
            created_by VARCHAR(64), updated_at TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_taxonomy_jobs_supplier ON supplier_taxonomy_jobs(supplier_id);
        CREATE TABLE IF NOT EXISTS supplier_taxonomy_config (
            supplier_id VARCHAR(64) PRIMARY KEY
                REFERENCES suppliers(id) ON DELETE CASCADE,
            store_domain TEXT NOT NULL,
            parent_category_id TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS supplier_taxonomy_custom_nodes (
            supplier_id VARCHAR(64) NOT NULL
                REFERENCES suppliers(id) ON DELETE CASCADE,
            path TEXT NOT NULL,
            data JSONB NOT NULL,
            created_by VARCHAR(64),
            updated_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (supplier_id, path)
        );
    ''')
    # Fail interrupted jobs explicitly; a new preview is required to resume failed items.
    await conn.execute("UPDATE supplier_taxonomy_jobs SET status='interrupted', updated_at=NOW() WHERE status='running'")
