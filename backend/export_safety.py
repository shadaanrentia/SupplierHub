"""Persistent export groups, image results, and last-valid supplier-price guards."""
import asyncio
import hashlib
import json
import math
import deps
from size_order import size_key, sort_variants
from sku_eligibility import eligible_variants
from deps import row_to_dict, calculate_sale_price

LIMIT = 200


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


def export_name(name, sku):
    from export_format import product_title
    return product_title(name, sku)


def positive(value):
    try:
        return value is not None and math.isfinite(float(value)) and float(value) > 0
    except (ValueError, TypeError, OverflowError):
        return False


def validate_prices(product, variants):
    if product.get('price_needs_review') or not positive(product.get('base_price')):
        raise ValueError('Supplier cost needs verification; refresh supplier pricing first')
    bad = [v.get('variant_sku') for v in variants if v.get('price_needs_review') or not positive(v.get('price'))]
    if bad:
        raise ValueError('Variant prices need verification: ' + ', '.join(str(s) for s in bad[:10]))
    if variants:
        combinations = [(str(v.get('color') or '').strip().casefold(), str(v.get('size') or '').strip().casefold()) for v in variants]
        if any(not color or not size for color, size in combinations) or len(combinations) != len(set(combinations)):
            raise ValueError('Variant colour/size combinations are missing or duplicated')
    skus = [str(v.get('variant_sku') or '').strip().casefold() for v in variants]
    if any(not s for s in skus) or len(skus) != len(set(skus)):
        raise ValueError('Variant SKUs are missing or duplicated')


def grouped_variants(variants):
    """Pack whole sizes in natural order. Split a size only if it alone exceeds 200."""
    sizes = {}
    for variant in sorted(variants, key=lambda v: (size_key(v.get('size')), str(v.get('color') or '').casefold(), str(v.get('variant_sku') or '').casefold())):
        sizes.setdefault(size_key(variant.get('size')), []).append(variant)
    groups, current = [], []
    for rows in sizes.values():
        if len(rows) > LIMIT:
            if current:
                groups.append(current); current = []
            groups.extend(rows[i:i+LIMIT] for i in range(0, len(rows), LIMIT))
        elif len(current) + len(rows) > LIMIT:
            groups.append(current); current = list(rows)
        else:
            current.extend(rows)
    if current: groups.append(current)
    return groups


async def init_export_safety_schema(conn):
    from single_family import init_schema
    await init_schema(conn)
    await conn.execute('''
        ALTER TABLE products ADD COLUMN IF NOT EXISTS price_needs_review BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE product_variants ADD COLUMN IF NOT EXISTS price_needs_review BOOLEAN NOT NULL DEFAULT FALSE;
        CREATE TABLE IF NOT EXISTS lightspeed_export_groups (
            id VARCHAR(64) PRIMARY KEY, product_id VARCHAR(64) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            store_domain TEXT NOT NULL, group_number INTEGER NOT NULL, export_sku TEXT NOT NULL,
            variant_ids JSONB NOT NULL, lightspeed_product_id TEXT, state TEXT NOT NULL DEFAULT 'planned',
            message TEXT NOT NULL DEFAULT '', updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(product_id,store_domain,group_number), UNIQUE(store_domain,export_sku)
        );
        ALTER TABLE lightspeed_export_groups ADD COLUMN IF NOT EXISTS export_mode TEXT NOT NULL DEFAULT 'legacy';
        CREATE TABLE IF NOT EXISTS lightspeed_export_image_results (
            store_domain TEXT NOT NULL, destination_id TEXT NOT NULL, image_key TEXT NOT NULL,
            status TEXT NOT NULL, message TEXT NOT NULL DEFAULT '', updated_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY(store_domain,destination_id,image_key)
        );
        CREATE TABLE IF NOT EXISTS supplier_price_rejections (
            id BIGSERIAL PRIMARY KEY, source_table TEXT NOT NULL, record_id TEXT NOT NULL,
            incoming_price TEXT, retained_price NUMERIC, database_user TEXT,
            application_name TEXT, rejected_at TIMESTAMP DEFAULT NOW()
        );
        CREATE OR REPLACE FUNCTION supplierhub_guard_supplier_price() RETURNS TRIGGER LANGUAGE plpgsql AS $$
        DECLARE incoming NUMERIC; previous NUMERIC;
        BEGIN
            IF TG_TABLE_NAME='products' THEN
                incoming:=NEW.base_price;
                IF TG_OP='UPDATE' THEN previous:=OLD.base_price; END IF;
            ELSE
                incoming:=NEW.price;
                IF TG_OP='UPDATE' THEN previous:=OLD.price; END IF;
            END IF;
            IF incoming IS NULL OR incoming <= 0 OR incoming::TEXT IN ('NaN','Infinity','-Infinity') THEN
                NEW.price_needs_review:=TRUE;
                INSERT INTO supplier_price_rejections(source_table,record_id,incoming_price,retained_price,database_user,application_name)
                VALUES(TG_TABLE_NAME,NEW.id,incoming::TEXT,previous,current_user,current_setting('application_name'));
                IF previous>0 AND previous::TEXT NOT IN ('NaN','Infinity','-Infinity') THEN
                    IF TG_TABLE_NAME='products' THEN NEW.base_price:=previous; ELSE NEW.price:=previous; END IF;
                END IF;
            ELSE
                NEW.price_needs_review:=FALSE;
            END IF;
            RETURN NEW;
        END; $$;
        DROP TRIGGER IF EXISTS supplierhub_product_price_guard ON products;
        CREATE TRIGGER supplierhub_product_price_guard BEFORE INSERT OR UPDATE OF base_price ON products
            FOR EACH ROW EXECUTE FUNCTION supplierhub_guard_supplier_price();
        DROP TRIGGER IF EXISTS supplierhub_variant_price_guard ON product_variants;
        CREATE TRIGGER supplierhub_variant_price_guard BEFORE INSERT OR UPDATE OF price ON product_variants
            FOR EACH ROW EXECUTE FUNCTION supplierhub_guard_supplier_price();
        UPDATE products SET price_needs_review=TRUE WHERE base_price IS NULL OR base_price<=0 OR base_price::TEXT IN ('NaN','Infinity','-Infinity');
        UPDATE product_variants SET price_needs_review=TRUE WHERE price IS NULL OR price<=0 OR price::TEXT IN ('NaN','Infinity','-Infinity');
        UPDATE lightspeed_export_groups SET state='uncertain',message='Server restarted during export; inspect Lightspeed before retrying' WHERE state='running';
        UPDATE lightspeed_export_image_results SET status='uncertain',message='Server restarted during upload; inspect remote images before retrying' WHERE status='running';
    ''')


def image_key(image):
    if image.get('_source_image_key'): return str(image['_source_image_key'])
    data = image.get('image_base64')
    if data:
        return hashlib.sha256(str(data).encode()).hexdigest()
    return hashlib.sha256(str(image.get('url') or '').strip().encode()).hexdigest()


async def repair_images(ls, destination_id, images):
    from single_family import repair_assets
    return await repair_assets(ls,destination_id,images)


async def _legacy_export_product(ls, product, variants, images, markup, category_id):
    """Shared entry point used by normal pushes and the split-export page."""
    active = [dict(v) for v in variants if v.get('is_active') is not False]
    variants = eligible_variants(active)
    if active and not variants:
        raise ValueError('All variant SKUs are temporarily excluded: missing price and zero inventory')
    validate_prices(product, variants)
    from pricing_rules import prepare_export_pricing
    async with deps.pool.acquire() as pricing_conn:
        product, variants, markup = await prepare_export_pricing(pricing_conn, product, variants, markup)
    from export_format import inventory_quantity
    for variant in variants: inventory_quantity(variant)
    if not any(i.get('media_type','image')=='image' and (i.get('url') or i.get('image_base64')) for i in images):
        raise ValueError('No source images; refresh supplier media and check Export Review')
    async with deps.pool.acquire() as conn:
        groups = [dict(r) for r in await conn.fetch('SELECT * FROM lightspeed_export_groups WHERE product_id=$1 AND store_domain=$2 ORDER BY group_number', product['id'],ls.domain_prefix)]
    if len(variants) > LIMIT and not groups:
        raise ValueError('200+ variants: preview and save a split plan in Export Review first')
    if groups:
        all_ids = [str(i) for g in groups for i in decode(g['variant_ids'])]
        if len(all_ids) != len(set(all_ids)) or set(all_ids) != {str(v['id']) for v in variants}:
            raise ValueError('Variants changed after the saved split plan; review the plan before syncing')
        if any(g['state'] in ('running','uncertain') for g in groups):
            raise ValueError('An export is running or has an uncertain result; inspect Export Review')
    else:
        groups = [None]
    # Before the first split write, verify every original SKU is unassigned remotely.
    # Do not repeat this check for confirmed groups, whose variants now exist remotely.
    if groups[0] and not any(g.get('lightspeed_product_id') for g in groups):
        await asyncio.to_thread(ls.assert_split_skus_available, [v['variant_sku'] for v in variants] + [g['export_sku'] for g in groups])
    by_id = {str(v['id']): v for v in variants}
    completed, messages = [], []
    for group in groups:
        group_variants = [by_id[str(i)] for i in decode(group['variant_ids'])] if group else variants
        group_variants = sort_variants(group_variants)
        if len(group_variants) > LIMIT:
            raise ValueError('Saved group exceeds the configured limit of 199')
        if group:
            async with deps.pool.acquire() as conn:
                claimed = await conn.fetchval("UPDATE lightspeed_export_groups SET state='running',message='',updated_at=NOW() WHERE id=$1 AND state NOT IN ('running','uncertain') RETURNING id",group['id'])
            if not claimed:
                raise ValueError('Another export claimed this group')
        cost = min(float(v['price']) for v in group_variants) if group_variants else float(product['base_price'])
        retail = min(v['retail_price_override'] for v in group_variants) if group_variants else product['calculated_sale_price']
        payload = {
            'product_id': product['id'], 'supplier_sku': group['export_sku'] if group else product['supplier_sku'],
            'product_name': export_name(product['product_name'],product['supplier_sku']) + (f" — Group {group['group_number']:02d}" if group else ''),
            'description': product.get('description'), 'brand_name': product.get('brand'),
            'supplier_name': product.get('supplier_name') or '', 'cost_price':cost,
            'base_price':retail,'sale_price':retail,'retail_price':retail,
            'category_id':category_id,'variants':group_variants,'images':[],
            'effective_markup_percentage':markup,
            'lightspeed_product_id': group.get('lightspeed_product_id') if group else product.get('lightspeed_product_id'),
        }
        try:
            result = await ls.create_or_update_product(payload)
            if not result.get('success'):
                raise ValueError(result.get('error','Export failed'))
            destination = str(result['lightspeed_id'])
            if group:
                async with deps.pool.acquire() as conn:
                    await conn.execute("UPDATE lightspeed_export_groups SET lightspeed_product_id=$2,state='done',message='Export confirmed',updated_at=NOW() WHERE id=$1",group['id'],destination)
            if not group:
                async with deps.pool.acquire() as conn:
                    await conn.execute('UPDATE products SET lightspeed_product_id=$2 WHERE id=$1', product['id'], destination)
            completed.append(destination)
            from single_family import repair_assets
            image_result = await repair_assets(ls,destination,images,variants=group_variants)
            if image_result['uncertain'] or image_result['failed']:
                messages.append(f"{destination}: " + '; '.join(image_result['messages'])[:1500])
        except Exception as exc:
            if group:
                async with deps.pool.acquire() as conn:
                    await conn.execute("UPDATE lightspeed_export_groups SET state='uncertain',message=$2,updated_at=NOW() WHERE id=$1",group['id'],str(exc)[:1500])
            return {'success':False,'error':str(exc),'completed_groups':completed}
    return {'success':True,'lightspeed_id':completed[0], 'destination_ids':completed,'image_warnings':messages}


async def export_product(ls, product, variants, images, markup, category_id):
    from pricing_rules import ensure_pricing_schema
    await ensure_pricing_schema()
    from export_format import assert_service_compatible
    assert_service_compatible(ls)
    active = [dict(v) for v in variants if v.get('is_active') is not False]
    eligible = eligible_variants(active)
    async with deps.pool.acquire() as conn:
        groups = await conn.fetch('SELECT id FROM lightspeed_export_groups WHERE product_id=$1 AND store_domain=$2', product['id'], ls.domain_prefix)
    if groups or len(eligible) > LIMIT:
        from multi_family import export_families
        return await export_families(ls, product, eligible, images, markup, category_id)
    async with deps.pool.acquire() as conn:
        lock = 'export-review:' + str(product['id'])
        if not await conn.fetchval('SELECT pg_try_advisory_lock(hashtext($1))', lock):
            raise ValueError('This product is already exporting; wait for that job')
        try:
            return await _legacy_export_product(ls, product, variants, images, markup, category_id)
        finally:
            await conn.execute('SELECT pg_advisory_unlock(hashtext($1))', lock)
