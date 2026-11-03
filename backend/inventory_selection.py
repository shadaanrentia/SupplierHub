"""Shared source-warehouse selection and exact destination inventory verification."""
import json
from decimal import Decimal, InvalidOperation


def quantity(value):
    if value is None or isinstance(value, bool):
        raise ValueError('Inventory is missing or invalid')
    try:
        amount = Decimal(str(value).strip())
    except (ValueError, InvalidOperation):
        raise ValueError('Inventory is missing or invalid') from None
    if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value() or amount > Decimal("2147483647"):
        raise ValueError('Inventory must be a non-negative whole number')
    return int(amount)


def select_inventory(rows, preferred_warehouse='', strict=True):
    result = []
    preferred = str(preferred_warehouse or '').strip()
    for original in rows:
        row = dict(original)
        try:
            warehouses = row.get('warehouse_inventory')
            if isinstance(warehouses, str):
                warehouses = json.loads(warehouses)
            if warehouses is not None and not isinstance(warehouses, list):
                raise ValueError('Invalid warehouse inventory collection')
            if preferred and warehouses:
                matches = [w for w in warehouses if isinstance(w, dict)
                           and str(w.get('name') or '').strip().casefold() == preferred.casefold()]
                if len(matches) != 1:
                    raise ValueError('Selected warehouse is missing or ambiguous: ' + preferred)
                row['inventory'] = quantity(matches[0].get('quantity'))
                row['warehouse_name'] = matches[0]['name']
            else:
                row['inventory'] = quantity(row.get('inventory'))
        except (ValueError, TypeError) as exc:
            if strict:
                raise ValueError(str(row.get('variant_sku') or row.get('sku') or 'variant') + ': ' + str(exc)) from exc
            row['inventory'] = None
            row['inventory_error'] = str(exc)
        result.append(row)
    return result


async def export_inventory(conn, rows):
    setting = await conn.fetchrow("SELECT preferred_warehouse FROM settings WHERE id='system_settings'")
    return select_inventory(rows, setting['preferred_warehouse'] if setting else '')


def verify_member_inventory(response, product_id, outlet_id, expected_quantity):
    expected = quantity(expected_quantity)
    row = response.get('data') if isinstance(response, dict) else None
    if not isinstance(row, dict) or str(row.get('id') or '') != str(product_id):
        raise ValueError('Inventory readback returned the wrong product')
    entries = row.get('outlet_inventories')
    if not isinstance(entries, list):
        raise ValueError('Inventory readback did not include outlet inventories')
    matches = [i for i in entries if isinstance(i, dict) and str(i.get('outlet_id') or '') == str(outlet_id)]
    if len(matches) != 1:
        raise ValueError('Inventory readback needs exactly one record for the selected outlet')
    actual = quantity(matches[0].get('current_amount'))
    if actual != expected:
        raise ValueError(f'Inventory mismatch for {product_id} at outlet {outlet_id}: expected {expected}, received {actual}')
    return True


def verify_legacy_inventory(response, product_id, outlet_id, expected_quantity):
    """Validate a 2.0 product read; never interpret a missing row as zero."""
    row = response.get('data') if isinstance(response, dict) else None
    if not isinstance(row, dict) or str(row.get('id') or '') != str(product_id):
        raise ValueError('Legacy inventory readback returned the wrong product')
    entries = row.get('inventory')
    if not isinstance(entries, list):
        raise ValueError('Legacy inventory readback did not include inventory records')
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Invalid legacy inventory record')
        if entry.get('product_id') is not None and str(entry['product_id']) != str(product_id):
            raise ValueError('Legacy inventory record belongs to another product')
        normalized.append({'outlet_id': entry.get('outlet_id'), 'current_amount': entry.get('count')})
    return verify_member_inventory({'data': {'id': row['id'], 'outlet_inventories': normalized}},
                                   product_id, outlet_id, expected_quantity)


def read_inventory_for_verification(service, product_id, outlet_id, expected_quantity):
    """Read modern inventory, falling back to the explicit legacy read only
    when the correctly identified modern product omits its inventory field.
    No write is repeated and a real quantity mismatch cannot use fallback.
    """
    response = service.family_request('GET', f'products/{product_id}')
    row = response.get('data') if isinstance(response, dict) else None
    if not isinstance(row, dict) or str(row.get('id') or '') != str(product_id):
        return verify_member_inventory(response, product_id, outlet_id, expected_quantity)
    if 'outlet_inventories' in row:
        return verify_member_inventory(response, product_id, outlet_id, expected_quantity)
    service._throttle()
    legacy_response = service._http_session().get(
        f'https://{service.domain_prefix}.retail.lightspeed.app/api/2.0/products/{product_id}',
        headers=service._headers(), timeout=120)
    service._handle_rate_limit(legacy_response)
    legacy = service._handle_response(legacy_response)
    return verify_legacy_inventory(legacy, product_id, outlet_id, expected_quantity)

