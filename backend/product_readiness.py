"""One live Lightspeed readiness check for listing, review and export.
No manual approval flag overrides these checks; no schema change is required.
"""
import json
import math
from collections import defaultdict
from export_safety import validate_prices, export_name, LIMIT
from sanmar_taxonomy import sku_key
from size_order import sort_variants
from sku_eligibility import (
    eligible_variants,
    eligibility_reason,
    new_export_eligible_variants,
    skip_sku,
)


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def evaluate(product, variants, images, groups, category_id, category_error=None, image_issues=0):
    active = [
        dict(v)
        for v in variants
        if v.get("is_active") is not False
    ]

    active_by_id = {
        str(v["id"]): v
        for v in active
        if v.get("id") is not None
    }

    selected_by_id = {}
    eligibility_errors = []

    if groups:
        for group in groups:
            group_ids = [
                str(value)
                for value in decoded(group["variant_ids"])
            ]

            group_variants = [
                active_by_id[variant_id]
                for variant_id in group_ids
                if variant_id in active_by_id
            ]

            if group.get("lightspeed_product_id"):
                selected = eligible_variants(group_variants)
            else:
                selected = new_export_eligible_variants(group_variants)

                selected_ids = {
                    str(v["id"])
                    for v in selected
                }

                for variant in group_variants:
                    if str(variant["id"]) not in selected_ids:
                        reason = eligibility_reason(variant)
                        eligibility_errors.append(
                            f"Uncreated export group contains ineligible SKU "
                            f"{variant.get('variant_sku')}: {reason}"
                        )

            for variant in selected:
                selected_by_id[str(variant["id"])] = variant

        variants = list(selected_by_id.values())

    elif product.get("lightspeed_product_id"):
        variants = eligible_variants(active)

    else:
        variants = new_export_eligible_variants(active)

    skipped = len(active) - len(variants)
    variants = sort_variants(variants)
    excluded = bool(active) and not variants
    images = [dict(i) for i in images if i.get('media_type') == 'image' and str(i.get('url') or '').strip()]
    errors = []
    errors.extend(eligibility_errors)
    if any(v.get('inventory_error') for v in active):
        errors.append('Selected warehouse inventory is missing or invalid; refresh supplier inventory before syncing')
    if excluded:
        errors.append(
            "All variant SKUs are temporarily excluded: "
            "new Lightspeed products require a valid positive price "
            "and positive inventory."
        )
    if not str(product.get('product_name') or '').strip(): errors.append('Product name is missing')
    if not str(product.get('supplier_sku') or '').strip(): errors.append('Supplier SKU is missing')
    try: validate_prices(product, variants)
    except ValueError as exc: errors.append(str(exc))
    if not category_id: errors.append(category_error or 'Choose and publish a Lightspeed category in Category Mapping')
    image_warnings = [] if images else ['No usable source images; refresh supplier media']
    for variant in variants:
        try:
            stock = float(variant.get('inventory'))
            if not math.isfinite(stock) or stock < 0: raise ValueError()
        except (TypeError, ValueError, OverflowError):
            errors.append('Missing or invalid variant inventory; refresh supplier inventory')
            break
    plan_ready = False
    if groups:
        if any(g.get('export_mode') == 'colour_families' for g in groups) and not any(g.get('lightspeed_product_id') for g in groups):
            errors.append('Rebuild the unexported colour plan as size families in Export Review')
        if any(g.get('export_mode') not in ('size_families','colour_families') for g in groups):
            errors.append('Old shared-family plan: verify deleted destinations in Export Review, then save a new size-family plan')
        try:
            members = [str(i) for group in groups for i in decoded(group['variant_ids'])]
            expected_ids = {
                str(v["id"])
                for v in active
            }

            complete = (
                len(members) == len(set(members))
                and set(members) == expected_ids
            )
            bounded = all(0 < len(decoded(g['variant_ids'])) <= LIMIT for g in groups)
            available = all(g.get('state') in ('planned', 'done', 'uncertain', 'images_pending') for g in groups)
            plan_ready = complete and bounded and available
            if not complete: errors.append('Variants changed: saved groups must cover every active variant exactly once')
            if not bounded: errors.append(f'Each export group needs 1–{LIMIT} variants')
            if not available: errors.append('An export batch is running; wait or restart the backend after stopping the worker')
        except (TypeError, ValueError, KeyError): errors.append('Saved split plan is invalid; inspect Export Review')
    elif len(variants) > LIMIT:
        errors.append(f'More than {LIMIT} variants: preview and save size families in Export Review')
    # Remote image retries stay in Pre-processing; absent source images still block readiness.
    valid = not errors
    pending = bool(image_issues) or not images or product.get('lightspeed_sync_status') in ('images_pending','needs_review')
    synced = valid and product.get('lightspeed_sync_status') == 'synced'
    return { 'variants': variants,'excluded_from_queue': excluded, 'skipped_variants_count': skipped, 'validation_errors': errors, 'is_valid': valid, 'can_sync': valid and (not synced or pending),
            'status': 'invalid' if errors else ('images_pending' if pending else ('synced' if synced else 'ready')),
            'mapped_lightspeed_category_id': category_id, 'variants_count': len(variants),
            'image_warnings': image_warnings, 'images_count': len(images), 'group_count': len(groups), 'plan_ready': plan_ready,
            'needs_split': len(variants) > LIMIT and not plan_ready, 'image_review_count': image_issues,
            'previous_export_failed': product.get('lightspeed_sync_status') == 'failed'}


async def load_readiness(conn, products, include_assets=True):
    """Batch child/taxonomy reads, avoiding one database round trip per product."""
    if not products: return {}
    ids = [p['id'] for p in products]
    supplier_ids = list({p['supplier_id'] for p in products if p.get('supplier_id')})
    settings = await conn.fetchrow("SELECT lightspeed_store_id,preferred_warehouse FROM settings WHERE id='system_settings'")
    domain = str(settings['lightspeed_store_id'] or '').strip() if settings else ''
    variants, images, groups = defaultdict(list), defaultdict(list), defaultdict(list)
    variant_columns = '*' if include_assets else 'id,product_id,variant_sku,color,size,price,inventory,warehouse_inventory,is_active,price_needs_review'
    image_columns = '*' if include_assets else 'id,product_id,url,media_type,is_primary,created_at'
    for r in await conn.fetch(f'SELECT {variant_columns} FROM product_variants WHERE product_id=ANY($1::varchar[]) AND is_active IS DISTINCT FROM FALSE', ids): variants[r['product_id']].append(dict(r))
    from inventory_selection import select_inventory
    for pid in variants:
        variants[pid] = select_inventory(variants[pid], settings['preferred_warehouse'] if settings else '', strict=False)
    for r in await conn.fetch(f"SELECT {image_columns} FROM product_media WHERE product_id=ANY($1::varchar[]) AND media_type='image' ORDER BY is_primary DESC,created_at", ids): images[r['product_id']].append(dict(r))
    for r in await conn.fetch('SELECT * FROM lightspeed_export_groups WHERE product_id=ANY($1::varchar[]) AND store_domain=$2 ORDER BY group_number', ids, domain): groups[r['product_id']].append(dict(r))
    managed = {r['supplier_id'] for r in await conn.fetch('SELECT supplier_id FROM supplier_taxonomy_imports WHERE supplier_id=ANY($1::varchar[])', supplier_ids)}
    styles = {(r['supplier_id'], r['sku_key']): decoded(r['data']) for r in await conn.fetch('SELECT supplier_id,sku_key,data FROM supplier_taxonomy_styles WHERE supplier_id=ANY($1::varchar[])', supplier_ids)}
    overrides = {(r['supplier_id'], r['sku_key']): r['path'] for r in await conn.fetch('SELECT supplier_id,sku_key,path FROM supplier_taxonomy_overrides WHERE supplier_id=ANY($1::varchar[])', supplier_ids)}
    nodes = {(r['supplier_id'], r['path']): decoded(r['data']) for r in await conn.fetch('SELECT supplier_id,path,data FROM supplier_taxonomy_nodes WHERE supplier_id=ANY($1::varchar[])', supplier_ids)}
    destinations = {(r['supplier_id'], r['path']): r['category_id'] for r in await conn.fetch('SELECT supplier_id,path,category_id FROM supplier_taxonomy_destinations WHERE supplier_id=ANY($1::varchar[]) AND store_domain=$2', supplier_ids, domain)}
    mappings = defaultdict(set)
    for r in await conn.fetch('SELECT supplier_category_name,lightspeed_category_id FROM category_mapping WHERE lightspeed_category_id IS NOT NULL AND lightspeed_category_id<>\'\''):
        mappings[r['supplier_category_name']].add(str(r['lightspeed_category_id']))
    explicit_mappings = {}
    if await conn.fetchval("SELECT to_regclass('public.supplier_category_links')"):
        explicit_mappings = {(r['supplier_id'],r['supplier_category_name']):r['lightspeed_category_id']
            for r in await conn.fetch("SELECT supplier_id,supplier_category_name,lightspeed_category_id FROM supplier_category_links WHERE supplier_id=ANY($1::varchar[]) AND store_domain=$2 AND lightspeed_override=TRUE", supplier_ids,domain)}
    remote_ids = list({str(i) for p in products for i in [p.get('lightspeed_product_id')] if i} | {str(g['lightspeed_product_id']) for rows in groups.values() for g in rows if g.get('lightspeed_product_id')})
    image_issues = defaultdict(int)
    if remote_ids:
        for r in await conn.fetch("SELECT destination_id,COUNT(*) AS count FROM lightspeed_export_image_results WHERE store_domain=$1 AND destination_id=ANY($2::text[]) AND status!='uploaded' GROUP BY destination_id", domain, remote_ids): image_issues[str(r['destination_id'])] = r['count']
    from category_scope import destination_labels
    labels = await destination_labels(conn)
    results = {}
    for product in products:
        pid, supplier = product['id'], product.get('supplier_id')
        category_id, error, label = None, None, None
        explicit_key = (supplier, product.get('category'))
        if explicit_key in explicit_mappings:
            category_id = explicit_mappings[explicit_key]
            label = product.get('category')
            if not category_id: error = 'Choose a Lightspeed category for this supplier category'
        elif supplier in managed:
            key = (supplier, sku_key(product.get('supplier_sku')))
            style = styles.get(key)
            path = overrides[key] if key in overrides else (style or {}).get('primary_path')
            label = path
            node = nodes.get((supplier, path))
            if not style and key not in overrides: error = 'Style is absent from SanMar CSV; assign it manually in Category Mapping'
            elif not path: error = 'Choose a primary category in Category Mapping'
            elif not node or not node.get('leaf') or not node.get('verified'): error = 'Choose a verified final category in Category Mapping'
            else:
                category_id = destinations.get((supplier, path))
                if not category_id: error = 'Publish SanMar categories to the configured Lightspeed store first'
        else:
            matches = mappings.get(product.get('category'), set())
            if len(matches) == 1: category_id = next(iter(matches)); label = product.get('category')
            elif len(matches) > 1: error = 'Conflicting legacy category mappings; keep one Lightspeed destination'
        destinations_for_product = {str(g['lightspeed_product_id']) for g in groups[pid] if g.get('lightspeed_product_id')}
        if product.get('lightspeed_product_id'): destinations_for_product.add(str(product['lightspeed_product_id']))
        state = evaluate(product, variants[pid], images[pid], groups[pid], category_id, error, sum(image_issues[i] for i in destinations_for_product))
        missing = bool(category_id) and str(category_id) not in labels
        state['category_available'] = not missing
        if missing:
            state['validation_errors'].append('The saved Lightspeed category is absent from the current category cache. Refresh categories and review this mapping.')
            state.update(is_valid=False,can_sync=False,status='invalid')
        results[pid] = {**state, 'mapped_category_name':label, 'variants': state['variants'], 'images': [i for i in images[pid] if str(i.get('url') or '').strip()]}
    return results


def public_state(state):
    return {k: v for k, v in state.items() if k not in ('variants', 'images')}



