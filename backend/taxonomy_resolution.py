"""Resolve current SanMar style assignments during every normal product push."""
import json
from sanmar_taxonomy import sku_key
from taxonomy_extensions import combined_nodes

async def resolve_category(conn, supplier_id, sku):
    # Explicit mappings on the unified page take precedence over the old CSV workflow.
    if await conn.fetchval("SELECT to_regclass('public.supplier_category_links')"):
        explicit = await conn.fetchrow("""SELECT m.lightspeed_category_id
            FROM products p JOIN supplier_category_links m
              ON m.supplier_id=p.supplier_id AND m.supplier_category_name=p.category
            JOIN settings s ON s.id='system_settings' AND m.store_domain=BTRIM(s.lightspeed_store_id)
            WHERE p.supplier_id=$1 AND p.supplier_sku=$2 AND m.lightspeed_override=TRUE""", supplier_id,sku)
        if explicit:
            return True, explicit['lightspeed_category_id'], (None if explicit['lightspeed_category_id'] else 'Choose a Lightspeed category for this supplier category')
    managed = await conn.fetchval('SELECT 1 FROM supplier_taxonomy_imports WHERE supplier_id=$1', supplier_id)
    if not managed:
        return False, None, None
    row = await conn.fetchrow('''SELECT t.data, o.sku_key AS override_key, o.path AS override_path
        FROM supplier_taxonomy_styles t LEFT JOIN supplier_taxonomy_overrides o
        ON o.supplier_id=t.supplier_id AND o.sku_key=t.sku_key
        WHERE t.supplier_id=$1 AND t.sku_key=$2''', supplier_id, sku_key(sku))
    if not row:
        manual = await conn.fetchrow('SELECT path FROM supplier_taxonomy_overrides WHERE supplier_id=$1 AND sku_key=$2', supplier_id, sku_key(sku))
        if not manual:
            return True, None, 'Style is absent from the SanMar category CSV; assign it manually'
        path = manual['path']
    else:
        data = json.loads(row['data']) if isinstance(row['data'], str) else row['data']
        path = row['override_path'] if row['override_key'] is not None else data.get('primary_path')
    if not path:
        return True, None, 'Primary category needs review in Category Mapping'
    nodes = await combined_nodes(conn, supplier_id)
    node = next((item for item in nodes if item['path'] == path), None)
    if not node or not node.get('leaf') or not node.get('verified'):
        return True, None, 'Primary category was removed or is not a verified leaf'
    cid = await conn.fetchval('''SELECT d.category_id FROM supplier_taxonomy_destinations d
        JOIN settings s ON s.id='system_settings' AND TRIM(s.lightspeed_store_id)=d.store_domain
        WHERE d.supplier_id=$1 AND d.path=$2''', supplier_id, path)
    if not cid:
        return True, None, 'Publish SanMar categories to the configured Lightspeed store first'
    return True, cid, None
