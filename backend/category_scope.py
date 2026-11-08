"""Published destination labels and exact category scoping, shared by UI and queue."""
import json


def category_labels(categories):
    from category_tree import category_tree
    return {row['lightspeed_category_id']:row['path'] for row in category_tree(categories)
            if row['hierarchy_valid']}


async def destination_labels(conn):
    if not await conn.fetchval("SELECT to_regclass('public.lightspeed_category_snapshots')"):
        return {}
    snapshot = await conn.fetchval("""SELECT categories FROM lightspeed_category_snapshots
        WHERE LOWER(BTRIM(store_domain))=(SELECT LOWER(BTRIM(lightspeed_store_id)) FROM settings WHERE id='system_settings')
        ORDER BY synced_at DESC NULLS LAST LIMIT 1""")
    from category_tree import category_tree
    return {row['lightspeed_category_id']:row['path'] for row in category_tree(snapshot or [])
            if row['hierarchy_valid'] and row['leaf_category']}


def in_category(state, category_id):
    if category_id == '__unmapped__':
        return not state.get('mapped_lightspeed_category_id') or state.get('category_available') is False
    return not category_id or str(state.get('mapped_lightspeed_category_id') or '') == str(category_id)


def category_rows(products, states, labels):
    """One destination row per supplier; retain all contributing source categories."""
    rows = {}
    for product in products:
        state = states[product['id']]
        cid = state.get('mapped_lightspeed_category_id')
        if not cid:
            continue
        key = (product['supplier_id'], str(cid))
        item = rows.setdefault(key, {'supplier_id':key[0], 'category_id':key[1],
            'category_name':labels.get(key[1]) or 'Needs category mapping',
            'category_available':key[1] in labels,
            'product_count':0, 'supplier_categories':set(), 'supplier_paths':set()})
        item['product_count'] += 1
        if product.get('category'):
            item['supplier_categories'].add(str(product['category']))
        if state.get('mapped_category_name'):
            item['supplier_paths'].add(str(state['mapped_category_name']))
    for item in rows.values():
        for key in ('supplier_categories','supplier_paths'):
            item[key] = sorted(item[key])
        item['path'] = item['category_name']
    return rows

