"""Category pricing and shipping policy for Pre-processing, normal exports and every split family."""
import asyncio
import math
from decimal import Decimal, ROUND_HALF_UP
import deps

_schema_lock = asyncio.Lock()
_schema_pool = None


async def ensure_pricing_schema():
    global _schema_pool
    if _schema_pool is deps.pool:
        return
    async with _schema_lock:
        if _schema_pool is deps.pool:
            return
        async with deps.pool.acquire() as conn:
            await conn.execute("""CREATE TABLE IF NOT EXISTS supplier_category_policies (
                store_domain TEXT NOT NULL, supplier_id VARCHAR(64) NOT NULL REFERENCES suppliers(id),
                category_id TEXT NOT NULL, pricing_mode TEXT NOT NULL DEFAULT 'global'
                    CHECK(pricing_mode IN ('global','percentage','direct')),
                pricing_value NUMERIC(14,4), weight_lb NUMERIC(14,4),
                length_in NUMERIC(14,4), width_in NUMERIC(14,4), height_in NUMERIC(14,4),
                updated_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY(store_domain,supplier_id,category_id));""")
        _schema_pool = deps.pool


def number(value, name, allow_zero=False):
    if isinstance(value, bool):
        raise ValueError(name + ' must be a number')
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(name + ' must be a number')
    if not math.isfinite(value) or value < 0 or (not allow_zero and value == 0):
        raise ValueError(name + (' must be zero or positive' if allow_zero else ' must be positive'))
    return value


def cents(value):
    return float(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def pricing_policy(product, variants, global_markup):
    mode = product.get('category_pricing_mode') or 'global'
    if mode not in ('global', 'percentage', 'direct'):
        raise ValueError('Unknown category pricing mode')
    costs = [number(v.get('price'), 'Variant cost') for v in variants]
    anchor = min(costs) if costs else number(product.get('base_price'), 'Product cost')
    value = number(global_markup, 'Global markup', True) if mode == 'global' else number(product.get('category_pricing_value'), 'Category pricing value', mode == 'percentage')
    return {'mode': mode, 'value': value, 'anchor_cost': anchor}


def price_for(cost, policy):
    cost = number(cost, 'Supplier cost')
    if policy['mode'] == 'direct':
        # Retain supplier surcharges in cents; do not flatten large sizes.
        return cents(Decimal(str(policy['value'])) + Decimal(str(cost)) - Decimal(str(policy['anchor_cost'])))
    # Keep existing percentage/global rounding behaviour.
    return float(deps.calculate_sale_price(cost, policy['value']))


def variant_retail(variant, markup):
    if variant.get('retail_price_override') is not None:
        return number(variant['retail_price_override'], 'Computed variant retail price')
    return float(deps.calculate_sale_price(number(variant.get('price'), 'Variant cost'), markup))


def pricing_summary(product, variants, global_markup):
    policy = pricing_policy(product, variants, global_markup)
    prices = [price_for(v['price'], policy) for v in variants] or [price_for(policy['anchor_cost'], policy)]
    return {'pricing_mode': policy['mode'], 'pricing_value': product.get('category_pricing_value'),
        'pricing_source': 'global' if policy['mode'] == 'global' else 'category',
        'effective_markup_percentage': policy['value'] if policy['mode'] != 'direct' else None,
        'pricing_anchor_cost': policy['anchor_cost'], 'cost_price': policy['anchor_cost'], 'calculated_sale_price': min(prices),
        'retail_price_min': min(prices), 'retail_price_max': max(prices),
        'pricing_label': f"Global {policy['value']:g}%" if policy['mode'] == 'global' else (f"Category {policy['value']:g}%" if policy['mode'] == 'percentage' else f"Category base ${policy['value']:.2f}")}


async def category_policies(conn):
    settings = await conn.fetchrow("SELECT lightspeed_store_id FROM settings WHERE id='system_settings'")
    domain = str(settings['lightspeed_store_id'] or '').strip() if settings else ''
    rows = await conn.fetch('SELECT * FROM supplier_category_policies WHERE store_domain=$1', domain)
    return {(r['supplier_id'],str(r['category_id'])):dict(r) for r in rows}


def apply_category_policy(product, category_id, policies):
    product = dict(product)
    rule = policies.get((product.get('supplier_id'),str(category_id)), {})
    product.update(category_pricing_mode=rule.get('pricing_mode') or 'global',
        category_pricing_value=rule.get('pricing_value'), category_policy_id=category_id,
        category_shipping={k:float(rule[k]) if rule.get(k) is not None else None
            for k in ('weight_lb','length_in','width_in','height_in')})
    return product


async def prepare_export_pricing(conn, product, variants, global_markup):
    # The caller holds the product export lock. Category edits lock affected products.
    from taxonomy_resolution import resolve_category
    managed, cid, error = await resolve_category(conn,product.get('supplier_id'),product.get('supplier_sku'))
    if managed and error: raise ValueError(error)
    if not managed:
        matches = await conn.fetch("SELECT DISTINCT lightspeed_category_id FROM category_mapping WHERE supplier_category_name=$1 AND lightspeed_category_id IS NOT NULL AND lightspeed_category_id<>''",product.get('category') or '')
        if len(matches) != 1: raise ValueError('Choose one published category before exporting')
        cid = matches[0]['lightspeed_category_id']
    product = apply_category_policy(product,cid,await category_policies(conn))
    settings = await conn.fetchrow("SELECT markup_percentage FROM settings WHERE id='system_settings'")
    if settings and settings['markup_percentage'] is not None:
        global_markup = settings['markup_percentage']
    policy = pricing_policy(product, variants, global_markup)
    priced = [dict(v,retail_price_override=price_for(v['price'],policy),category_shipping=product['category_shipping']) for v in variants]
    product.update(pricing_summary(product, variants, global_markup))
    return product, priced, policy['value'] if policy['mode'] != 'direct' else 0.0
