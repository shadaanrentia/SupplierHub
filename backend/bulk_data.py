"""ATC BulkData parsing and durable, account-scoped 24-hour request guard."""
import asyncio
import hashlib
import html
import json
import math
from datetime import datetime, timezone
from lxml import etree
import re
import unicodedata

def normalize_description(value):
    text = unicodedata.normalize("NFC", str(value or ""))

    # Decode supplier entities without changing specifications.
    for _ in range(2):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded

    # Preserve paragraph/list boundaries from supplier HTML.
    text = re.sub(
        r"<\s*(?:br\s*/?|/p|/div|/li)\s*>",
        "\n",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\xa0", " ")

    paragraphs = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            paragraphs.append(line)

    text = "\n".join(paragraphs)

    # Separate sentences; decimal measurements such as 5.5 remain intact.
    return re.sub(
        r"(?<=[.!?]) +(?=[A-Z0-9*])",
        "\n",
        text,
    ).strip()

def parse_bulk_xml(xml):
    data = xml.encode('utf-8') if isinstance(xml, str) else xml
    if len(data) > 256 * 1024 * 1024:
        raise ValueError('BulkData exceeds the 256 MiB import limit')
    root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
    if root.getroottree().docinfo.doctype:
        raise ValueError('BulkData must not contain a document type declaration')
    responses = root.xpath("descendant-or-self::*[local-name()='GetBulkDataResponse']")
    if len(responses) != 1 or etree.QName(responses[0]).namespace != 'https://edi.atc-apparel.com/bulk-data/':
        raise ValueError('Expected a complete ATC GetBulkDataResponse; excerpts are not accepted')
    response = responses[0]
    for message in response.xpath(".//*[local-name()='ServiceMessage' or local-name()='errorMessage' or local-name()='ErrorMessage']"):
        fields = {etree.QName(c).localname.casefold(): (c.text or '').strip() for c in message if isinstance(c.tag, str)}
        if fields.get('severity', '').casefold() == 'error' or fields.get('code') not in (None, '', '0', '200'):
            raise ValueError('BulkData contains a supplier error; code ' + fields.get('code', 'unknown'))
    rows, seen = [], set()
    for element in response.xpath(".//*[local-name()='Product']"):
        raw = {etree.QName(c).localname: (c.text or '').strip() for c in element if isinstance(c.tag, str)}
        part, style = raw.get('productId', ''), raw.get('style', '')
        if not part or not style or part in seen:
            raise ValueError('BulkData contains a missing style/SKU or duplicate variant SKU')
        seen.add(part)
        def number(name):
            try:
                result = float(raw.get(name, ''))
                return result if math.isfinite(result) else None
            except (ValueError, TypeError):
                return None
        rows.append({
            'product_id': part, 'style': style,
            'product_name': html.unescape(raw.get('productName', '')),
            'fr_product_name': html.unescape(raw.get('frProductName', '')),
            'description': normalize_description(raw.get('description', '')),
            'fr_description': normalize_description(raw.get('frDescription', '')),
            'color': html.unescape(raw.get('swatchColor', '')),
            'fr_color': html.unescape(raw.get('frSwatchColor', '')),
            'size': raw.get('size', ''), 'brand': html.unescape(raw.get('brand', '')),
            'image_url': raw.get('image', ''), 'quantity': number('quantity'),
            'price': number('price'), 'sale_price': number('salePrice'),
            'sale_end_date': raw.get('saleEndDate', ''), 'weight': raw.get('weight', ''),
            'case_size': number('caseSize'), 'youth': raw.get('youth', '').casefold() == 'true',
            'discount_code': raw.get('discountCode', ''), 'price_group': raw.get('priceGroup', ''),
            'raw_fields': raw,
        })
    if not rows:
        raise ValueError('BulkData contains no product records; existing data retained')
    return {'success': True, 'products': rows, 'count': len(rows),
            'raw_xml': data.decode('utf-8-sig')}


async def init_bulk_schema(conn):
    await conn.execute("""
        ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS bulk_data_email TEXT DEFAULT '';
        ALTER TABLE products ADD COLUMN IF NOT EXISTS pricing_synced_at TIMESTAMPTZ;
        ALTER TABLE product_variants ADD COLUMN IF NOT EXISTS pricing_synced_at TIMESTAMPTZ;
        ALTER TABLE product_variants ADD COLUMN IF NOT EXISTS inventory_synced_at TIMESTAMPTZ;
        ALTER TABLE products ADD COLUMN IF NOT EXISTS description_source TEXT DEFAULT '';
        ALTER TABLE products ADD COLUMN IF NOT EXISTS bulk_metadata JSONB DEFAULT '{}'::jsonb;
        ALTER TABLE product_variants ADD COLUMN IF NOT EXISTS bulk_metadata JSONB DEFAULT '{}'::jsonb;
        CREATE TABLE IF NOT EXISTS supplier_bulk_cache (
            supplier_id VARCHAR(64) PRIMARY KEY REFERENCES suppliers(id) ON DELETE CASCADE,
            account_key TEXT NOT NULL, raw_xml TEXT NOT NULL, payload JSONB NOT NULL,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), source TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS supplier_bulk_quota (
            account_key TEXT PRIMARY KEY, last_attempt TIMESTAMPTZ NOT NULL,
            next_allowed_at TIMESTAMPTZ NOT NULL
        );
    """)


def account_key(connector):
    # A duplicate supplier configuration for the same account shares its quota.
    from urllib.parse import urlsplit
    host = urlsplit(connector._get_endpoint('bulk_data')).hostname or ''
    return hashlib.sha256((host.casefold() + ':' + connector.account_id.strip()).encode()).hexdigest()


async def save_snapshot(conn, supplier_id, key, result, source):
    payload = {k: v for k, v in result.items() if k != 'raw_xml'}
    await conn.execute("""INSERT INTO supplier_bulk_cache(supplier_id,account_key,raw_xml,payload,source)
        VALUES($1,$2,$3,$4::jsonb,$5) ON CONFLICT(supplier_id) DO UPDATE SET
        account_key=EXCLUDED.account_key,raw_xml=EXCLUDED.raw_xml,payload=EXCLUDED.payload,
        fetched_at=NOW(),source=EXCLUDED.source""", supplier_id, key, result['raw_xml'], json.dumps(payload), source)


async def get_snapshot(pool, supplier_id, connector, cache_only=False):
    key = account_key(connector)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock(hashtext($1))', 'atc-bulk:' + key)
            cached = await conn.fetchrow("""SELECT payload,fetched_at,
                fetched_at > NOW()-INTERVAL '24 hours' AS fresh
                FROM supplier_bulk_cache WHERE supplier_id=$1 AND account_key=$2""", supplier_id, key)
            if cached and (cache_only or cached['fresh']):
                payload = json.loads(cached['payload']) if isinstance(cached['payload'], str) else dict(cached['payload'])
                return {**payload, 'cache_used': True, 'fetched_at': str(cached['fetched_at'])}
            if cache_only:
                raise ValueError('No saved BulkData response exists for this supplier account')
            # Validate configuration before consuming the locally guarded request slot.
            if connector.is_atc and not connector.bulk_data_email:
                raise ValueError('Configure suppliers.bulk_data_email with the SanMar login email before fetching BulkData')
            blocked = await conn.fetchval('SELECT next_allowed_at FROM supplier_bulk_quota WHERE account_key=$1 AND next_allowed_at>NOW()', key)
            if blocked:
                raise ValueError('BulkData request already attempted; next local request allowed at ' + str(blocked) + '. Reuse/import a saved response instead.')
            await conn.execute("""INSERT INTO supplier_bulk_quota(account_key,last_attempt,next_allowed_at)
                VALUES($1,NOW(),NOW()+INTERVAL '24 hours') ON CONFLICT(account_key) DO UPDATE
                SET last_attempt=NOW(),next_allowed_at=NOW()+INTERVAL '24 hours'""", key)
    # The reservation is committed BEFORE network I/O. Timeout/crash does not allow another call.
    result = await asyncio.to_thread(connector.get_bulk_data)
    if not result.get('success'):
        raise ValueError(result.get('error') or 'BulkData request failed; no automatic retry')
    if not result.get('raw_xml'):
        raise ValueError('BulkData response missing raw XML; cache not replaced')
    async with pool.acquire() as conn:
        async with conn.transaction():
            await save_snapshot(conn, supplier_id, key, result, 'supplier')
    return {**result, 'cache_used': False, 'fetched_at': datetime.now(timezone.utc).isoformat()}


async def import_snapshot(conn, supplier_id, connector, xml):
    result = parse_bulk_xml(xml)
    key = account_key(connector)
    await conn.execute('SELECT pg_advisory_xact_lock(hashtext($1))', 'atc-bulk:' + key)
    await save_snapshot(conn, supplier_id, key, result, 'soapui')
    # An externally downloaded response may already have consumed today's supplier quota.
    await conn.execute("""INSERT INTO supplier_bulk_quota(account_key,last_attempt,next_allowed_at)
        VALUES($1,NOW(),NOW()+INTERVAL '24 hours') ON CONFLICT(account_key) DO UPDATE SET
        next_allowed_at=GREATEST(supplier_bulk_quota.next_allowed_at,EXCLUDED.next_allowed_at)""", key)
    return {'variants': result['count'], 'styles': len({r['style'] for r in result['products']})}
