"""Published destination labels and exact category scoping, shared by UI and queue."""
import json


def category_labels(categories):
    if isinstance(categories, str):
        categories = json.loads(categories)
    if isinstance(categories, dict):
        categories = categories.get('data') or categories.get('categories') or []
    nodes = {}
    def visit(rows, parent=None):
        for original in rows if isinstance(rows, list) else []:
            if not isinstance(original, dict):
                continue
            key = str(original.get('lightspeed_category_id') or original.get('id') or '')
            if not key:
                continue
            row = dict(original)
            row['parent_id'] = row.get('parent_id') or parent
            nodes[key] = row
            visit(row.get('children'), key)
    visit(categories)
    labels = {}
    for key in nodes:
        path, seen, current = [], set(), key
        while current in nodes and current not in seen:
            seen.add(current)
            row = nodes[current]
            name = row.get('category_name') or row.get('name')
            if name:
                path.insert(0, str(name))
            current = str(row.get('parent_id') or '')
        if path:
            labels[key] = ' > '.join(path)
    return labels


async def destination_labels(conn):
    if not await conn.fetchval("SELECT to_regclass('public.lightspeed_category_snapshots')"):
        return {}
    snapshot = await conn.fetchval("""SELECT categories FROM lightspeed_category_snapshots
        WHERE LOWER(BTRIM(store_domain))=(SELECT LOWER(BTRIM(lightspeed_store_id)) FROM settings WHERE id='system_settings')
        ORDER BY synced_at DESC NULLS LAST LIMIT 1""")
    return category_labels(snapshot or [])


def in_category(state, category_id):
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
            'category_name':labels.get(key[1]) or 'Lightspeed category name unavailable',
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
