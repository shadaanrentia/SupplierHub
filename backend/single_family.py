"""Resumable batches into one family. Creation/addition POSTs are never blind-retried."""
from sync_context import defer_images
import asyncio
import base64
import json
import logging
import math
import requests
import deps
from size_order import sort_variants, sort_export_variants
from export_format import normalize_image_ack, assert_service_compatible

log = logging.getLogger(__name__)


async def init_schema(conn):
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS lightspeed_family_exports (
            product_id VARCHAR(64) NOT NULL, store_domain TEXT NOT NULL,
            family_id TEXT, destination_id TEXT, state TEXT NOT NULL DEFAULT 'planned',
            message TEXT NOT NULL DEFAULT '', updated_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY(product_id, store_domain)
        );
        CREATE TABLE IF NOT EXISTS lightspeed_family_additions (
            product_id VARCHAR(64) NOT NULL, store_domain TEXT NOT NULL,
            variant_sku TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'planned',
            destination_id TEXT, message TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY(product_id,store_domain,variant_sku)
        );
        ALTER TABLE product_media ADD COLUMN IF NOT EXISTS source_color TEXT DEFAULT '';
        ALTER TABLE product_media ADD COLUMN IF NOT EXISTS source_part_ids JSONB DEFAULT '[]'::jsonb;
    """)


def sku(row):
    return str(row.get('variant_sku') or row.get('sku') or '').strip().lower()


def members(family, expected_skus=None):
    expected = {str(v).strip().lower() for v in expected_skus or []}
    result = {}
    for original in family['products']:
        item = dict(original)
        aliases = [item.get('sku')]
        for field in ('codes', 'product_codes'):
            aliases += [c.get('code') for c in item.get(field) or []
                        if isinstance(c, dict) and str(c.get('type') or '').upper() == 'CUSTOM']
        matches = {str(v).strip().lower() for v in aliases if v and str(v).strip().lower() in expected}
        if len(matches) > 1:
            raise ValueError('A remote member carries multiple source variant SKUs; cannot match safely')
        key = next(iter(matches)) if matches else sku(item)
        if not key or not item.get('id') or key in result:
            raise ValueError('Family contains missing/duplicate SKUs or IDs')
        item['sku'] = key
        result[key] = item
    return result


def verify_owner(family, product, variants):
    from export_safety import export_name
    name = export_name(product['product_name'], product['supplier_sku'])
    allowed = {name, str(product['product_name']), name + ' — Group 01', str(product['product_name']) + ' — Group 01'}
    expected = {sku(v) for v in variants}
    remote = members(family, expected_skus=expected)
    if not remote or not set(remote).issubset(expected):
        raise ValueError('Family contains other or missing SKUs; automatic migration is blocked')
    if family.get('name') not in allowed and set(remote) != expected:
        raise ValueError('Renamed family has an incomplete SKU match; automatic adoption is blocked')
    return remote


def append_payload(variant, attributes, markup, supplier_id, outlet_id):
    from deps import calculate_sale_price
    from pricing_rules import variant_retail
    cost = float(variant['price'])
    quantity = variant.get('inventory')
    if quantity is None or not math.isfinite(float(quantity)) or float(quantity) < 0:
        raise ValueError('Unknown/invalid inventory for ' + sku(variant))
    values = [str(variant.get(name.lower()) or '').strip() for name in attributes]
    if not all(values):
        raise ValueError('Missing variant attributes for ' + sku(variant))
    body = {'variant_attributes': values,
            'codes': [{'type': 'CUSTOM', 'code': str(variant['variant_sku'])}],
            'prices': {'price_excluding_tax': str(variant_retail(variant, markup))},
            'active': {'in_store': True, 'ecwid': True},
            'outlet_inventories': [{'outlet_id': outlet_id, 'current_amount': int(float(quantity)),
                                   'reorder_point': 0, 'reorder_amount': 0}]}
    if supplier_id:
        body['suppliers'] = [{'supplier_id': supplier_id, 'code': str(variant['variant_sku']), 'price': str(cost)}]
    return body


def attribute_order(family, attr_map):
    reverse = {str(value): key for key, value in attr_map.items()}
    order = [reverse.get(str(value)) for value in family.get('variant_attribute_ids', [])]
    if not order or any(name not in ('Color', 'Size') for name in order):
        raise ValueError('Cannot map destination family attribute order safely')
    return order


async def export_one_family(ls, product, variants, images, markup, category_id):
    """Called only for saved batches/oversized products; normal products keep their existing path."""
    from export_safety import validate_prices, decode, export_name
    if len(variants) > 200:
        raise ValueError(f'Lightspeed permits at most 200 variants per family; this product has {len(variants)} eligible variants. Select at most 200 or use separate families. Batching does not bypass this limit.')
    from media_links import normalize_colour_label
    variants = [dict(v, color=normalize_colour_label(v.get('color'))) for v in variants]
    validate_prices(product, variants)
    if not variants or len({sku(v) for v in variants}) != len(variants) or any(not sku(v) for v in variants):
        raise ValueError('Missing/duplicate variant SKUs')
    if not defer_images.get() and not any(i.get('media_type', 'image') == 'image' and (i.get('url') or i.get('image_base64')) for i in images):
        raise ValueError('No source images; refresh supplier media')
    variants = sort_variants(variants)
    key = product['id']; domain = ls.domain_prefix
    lock = 'export-review:' + key
    async with deps.pool.acquire() as conn:
        acquired = await conn.fetchval('SELECT pg_try_advisory_lock(hashtext($1))', lock)
        if not acquired:
            raise ValueError('This product is already exporting; wait for that job')
        try:
            groups = [dict(r) for r in await conn.fetch('SELECT * FROM lightspeed_export_groups WHERE product_id=$1 AND store_domain=$2 ORDER BY group_number', key, domain)]
            ids = [str(i) for g in groups for i in decode(g['variant_ids'])]
            if not groups or len(ids) != len(set(ids)) or set(ids) != {str(v['id']) for v in variants}:
                raise ValueError('Save batches covering every eligible variant exactly once before syncing')
            if any(g['state'] == 'running' for g in groups):
                raise ValueError('An older export is running; stop that worker before resuming')
            await conn.execute('INSERT INTO lightspeed_family_exports(product_id,store_domain) VALUES($1,$2) ON CONFLICT DO NOTHING', key, domain)
            saved = dict(await conn.fetchrow('SELECT * FROM lightspeed_family_exports WHERE product_id=$1 AND store_domain=$2', key, domain))
            destination = saved.get('destination_id') or product.get('lightspeed_product_id')
            known = {str(g['lightspeed_product_id']) for g in groups if g.get('lightspeed_product_id')}
            if destination: known.add(str(destination))
            found = await asyncio.to_thread(ls.lookup_skus, [v['variant_sku'] for v in variants])
            if known:
                deleted = [await asyncio.to_thread(ls.remote_product_deleted, ref) for ref in sorted(known)]
                live_stored = {ref for ref, gone in zip(sorted(known), deleted) if not gone}
                if not live_stored and not found:
                    # Second successful catalog read confirms no source SKU is still live.
                    found = await asyncio.to_thread(ls.lookup_skus, [v['variant_sku'] for v in variants])
                    if not found:
                        async with conn.transaction():
                            await conn.execute("UPDATE lightspeed_family_exports SET family_id=NULL,destination_id=NULL,state='planned',message='Verified deleted destination; recreating on next write',updated_at=NOW() WHERE product_id=$1 AND store_domain=$2", key, domain)
                            await conn.execute("UPDATE lightspeed_export_groups SET lightspeed_product_id=NULL,state='planned',message='Previous destination verified deleted',updated_at=NOW() WHERE product_id=$1 AND store_domain=$2", key, domain)
                            await conn.execute('DELETE FROM lightspeed_family_additions WHERE product_id=$1 AND store_domain=$2', key, domain)
                            await conn.execute("UPDATE products SET lightspeed_product_id=NULL,lightspeed_sync_status='pending' WHERE id=$1", key)
                        saved.update(state='planned',destination_id=None,family_id=None)
                        for group in groups: group.update(state='planned',lightspeed_product_id=None)
                        destination = None
                        log.info('Verified deleted family references; old IDs cleared for %s', product['supplier_sku'])
                known = live_stored
                if destination and str(destination) not in known: destination = None
            known.update(str(item['id']) for item in found.values())
            family = None
            # Search records normally carry family_id. Fetch only one full family; verify every found ID belongs to it.
            if known:
                family = await asyncio.to_thread(ls.remote_family, str(destination or sorted(known)[0]))
                remote = verify_owner(family, product, variants)
                remote_ids = {str(row['id']) for row in remote.values()}
                if not known.issubset(remote_ids):
                    raise ValueError('Variants are already in multiple families; automatic merge is blocked')
                destination = str(next(iter(remote.values()))['id'])
            elif saved['state'] in ('creating', 'create_uncertain') or any(g['state'] == 'uncertain' for g in groups):
                raise ValueError('Earlier creation outcome is unknown and no family was found; inspect Lightspeed before retrying')
            # Existing family ownership and uncertain-creation recovery are
            # read-only checks. Require complete image coverage before any
            # metadata, product, inventory, or channel mutation.
            from media_links import prepare_variant_images
            images, missing_image_skus = prepare_variant_images(images, variants, product.get('supplier_sku'))
            if missing_image_skus:
                raise ValueError('Verified individual images are required before export; missing: ' + ', '.join(missing_image_skus[:20]))
            await conn.execute("UPDATE lightspeed_export_groups SET state='running',message='Exporting batches into one family',updated_at=NOW() WHERE product_id=$1 AND store_domain=$2 AND state!='done'", key, domain)
            supplier_id = await asyncio.to_thread(ls._get_or_create_supplier, product.get('supplier_name')) if product.get('supplier_name') else None
            brand_id = await asyncio.to_thread(ls._get_or_create_brand, product.get('brand')) if product.get('brand') else None
            attrs = await asyncio.to_thread(ls._ensure_variant_attributes, ['Color', 'Size'])
            outlet = await asyncio.to_thread(ls._get_inventory_outlet_id)
            if not outlet:
                raise ValueError('No destination inventory outlet configured')
            name = export_name(product['product_name'], product['supplier_sku'])
            if not family:
                first_ids = set(str(i) for i in decode(groups[0]['variant_ids']))
                first = [v for v in variants if str(v['id']) in first_ids]
                if not 0 < len(first) <= 199:
                    raise ValueError('Initial batch must contain at most 199 variants')
                await conn.execute("UPDATE lightspeed_family_exports SET state='creating',updated_at=NOW() WHERE product_id=$1 AND store_domain=$2", key, domain)
                payload = dict(product, product_name=name, supplier_sku=product['supplier_sku'], category_id=category_id, effective_markup_percentage=markup)
                cost = min(float(v['price']) for v in first)
                from deps import calculate_sale_price
                try:
                    created = await ls._create_product(payload, first, cost, calculate_sale_price(cost, markup), supplier_id, brand_id)
                    destination = created.get('_existing_product_id') or created.get('id') if isinstance(created, dict) else created
                    if not destination:
                        raise ValueError('Creation did not return a member ID')
                    # Persist immediately, before inventory, media or family reads can fail.
                    await conn.execute("UPDATE lightspeed_family_exports SET destination_id=$3,state='created',updated_at=NOW() WHERE product_id=$1 AND store_domain=$2", key, domain, str(destination))
                except Exception:
                    await conn.execute("UPDATE lightspeed_family_exports SET state='create_uncertain' WHERE product_id=$1 AND store_domain=$2 AND destination_id IS NULL", key, domain)
                    raise
                family = await asyncio.to_thread(ls.remote_family, str(destination))
                verify_owner(family, product, variants)
            await conn.execute("UPDATE lightspeed_family_exports SET family_id=$3,destination_id=$4,state='syncing',updated_at=NOW() WHERE product_id=$1 AND store_domain=$2", key, domain, str(family['id']), str(destination))
            await conn.execute('UPDATE products SET lightspeed_product_id=$2 WHERE id=$1', key, str(destination))
            order = attribute_order(family, attrs)
            family = await asyncio.to_thread(ls.update_family_metadata, str(destination), name, category_id, brand_id)
            remote = members(family)
            for group in groups:
                batch_ids = {str(i) for i in decode(group['variant_ids'])}
                batch = [v for v in variants if str(v['id']) in batch_ids]
                if not 0 < len(batch) <= 199: raise ValueError('Batch exceeds 199 variants')
                missing = [variant for variant in batch if sku(variant) not in remote]
                if len(remote) + len(missing) > 200:
                    raise ValueError('Appending this batch would exceed the 200-member family limit')
                for variant in missing:
                    variant_key = sku(variant)
                    journal = await conn.fetchrow('SELECT * FROM lightspeed_family_additions WHERE product_id=$1 AND store_domain=$2 AND variant_sku=$3', key, domain, variant_key)
                    if journal and journal['state'] in ('adding', 'uncertain', 'done'):
                        raise ValueError('Addition outcome unknown for ' + variant_key + '; no duplicate POST sent')
                if missing:
                    bodies = [append_payload(v, order, markup, supplier_id, str(outlet)) for v in sort_export_variants(missing)]
                    for variant in missing:
                        await conn.execute("INSERT INTO lightspeed_family_additions(product_id,store_domain,variant_sku,state) VALUES($1,$2,$3,'adding') ON CONFLICT(product_id,store_domain,variant_sku) DO UPDATE SET state='adding',message='',updated_at=NOW()", key, domain, sku(variant))
                    try:
                        # The documented endpoint accepts an ARRAY, not one object.
                        await asyncio.to_thread(ls.family_request, 'POST', f"product_families/{family['id']}/products", bodies)
                    except Exception as exc:
                        rejected = isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code in (400,401,403,404,413,415,422,429)
                        rejected = rejected or str(exc).startswith('Lightspeed rejected request:')
                        for variant in missing:
                            await conn.execute('UPDATE lightspeed_family_additions SET state=$4,message=$5 WHERE product_id=$1 AND store_domain=$2 AND variant_sku=$3', key, domain, sku(variant), 'rejected' if rejected else 'uncertain', str(exc)[:1500])
                        raise
                    for variant in missing:
                        await conn.execute("UPDATE lightspeed_family_additions SET state='done',updated_at=NOW() WHERE product_id=$1 AND store_domain=$2 AND variant_sku=$3", key, domain, sku(variant))
                family = await asyncio.to_thread(ls.remote_family, str(destination))
                remote = members(family)
                if any(sku(v) not in remote for v in batch):
                    raise ValueError('Added variants are not yet visible; retry reconciliation later')
                await ls._sync_existing_variants(str(destination), batch, 0, name, supplier_id, True, markup)
                await conn.execute("UPDATE lightspeed_export_groups SET state='done',lightspeed_product_id=$3,message='Batch verified in shared family',updated_at=NOW() WHERE id=$1 AND store_domain=$2", group['id'], domain, str(destination))
                log.info('Completed batch %s: %s variants in family %s', group['group_number'], len(batch), family['id'])
            if any(sku(v) not in remote for v in variants):
                raise ValueError('Remote family is missing source variants')
            result = await repair_assets(ls, str(destination), images, variants=variants)
            pending = result['failed'] or result['uncertain']
            await conn.execute('UPDATE lightspeed_family_exports SET state=$3,message=$4,updated_at=NOW() WHERE product_id=$1 AND store_domain=$2', key, domain, 'images_pending' if pending else 'done', '; '.join(result['messages'])[:1500])
            return {'success': True, 'lightspeed_id': str(destination), 'destination_ids': [str(destination)], 'image_warnings': result['messages'] if pending else []}
        except Exception as exc:
            await conn.execute("UPDATE lightspeed_export_groups SET state='uncertain',message=$3,updated_at=NOW() WHERE product_id=$1 AND store_domain=$2 AND state!='done'", key, domain, str(exc)[:1500])
            await conn.execute("UPDATE lightspeed_family_exports SET message=$3,updated_at=NOW() WHERE product_id=$1 AND store_domain=$2", key, domain, str(exc)[:1500])
            return {'success': False, 'error': str(exc)}
        finally:
            await conn.execute('SELECT pg_advisory_unlock(hashtext($1))', lock)


class MemberImages:
    """Reuse durable image reconciliation without mutating the shared service."""
    def __init__(self, service, target, snapshot_images=None):
        self.service, self.target = service, str(target)
        self.domain_prefix = service.domain_prefix
        self._snapshot_images = snapshot_images if isinstance(snapshot_images, list) else None
    def __getattr__(self, name): return getattr(self.service, name)
    def remote_family_images(self, ignored):
        if self._snapshot_images is not None: return self._snapshot_images
        row = self.service.family_request('GET', 'products/' + self.target).get('data')
        if not isinstance(row, dict) or str(row.get('id') or '') != self.target:
            raise ValueError('Member image read returned the wrong product')
        if isinstance(row, dict) and 'images' in row and row['images'] is None: return []
        if not isinstance(row, dict) or not isinstance(row.get('images'), list):
            raise ValueError('Member image collection is unavailable')
        return row['images']
    def _upload_family_image(self, ignored, data, filename, content_type):
        ls = self.service
        # Resolve all local dependencies BEFORE the request, so a missing method cannot fail after POST.
        assert_service_compatible(ls)
        self._snapshot_images = None
        ls._throttle()
        response = ls._http_session().post(f'https://{ls.domain_prefix}.retail.lightspeed.app/api/2026-10/products/{self.target}/images',
            headers={k:v for k,v in ls._headers().items() if k.lower() != 'content-type'},
            files={'image': (filename, data, content_type)}, timeout=120)
        ls._handle_rate_limit(response)
        result = ls._handle_response(response)
        return normalize_image_ack(result, 'product_id', self.target)
    def _upload_images(self, destination, images):
        return type(self.service)._upload_images(self, destination, images)


class FamilyImages(MemberImages):
    def remote_family_images(self, ignored):
        if self._snapshot_images is not None: return self._snapshot_images
        return self.service.remote_family_images(self.target)
    def _upload_family_image(self, ignored, data, filename, content_type):
        assert_service_compatible(self.service)
        self._snapshot_images = None
        return self.service._upload_family_image(self.target, data, filename, content_type)


def matched_images(variant, images):
    matched = []
    for image in images:
        parts = image.get('source_part_ids') or []
        if isinstance(parts, str): parts = json.loads(parts)
        from media_links import usable
        parts = [p for p in parts if usable(p)]
        from media_links import colour_key
        color = colour_key(image.get('source_color') or image.get('color'))
        # Explicit part links take precedence. Never guess colours from a filename.
        if not usable(color): color = ''
        if parts:
            match = sku(variant) in {str(p).strip().lower() for p in parts}
        else:
            match = bool(color and color == colour_key(variant.get('color')))
        if match: matched.append(image)
    return matched


def expand_colour_links(images, variants):
    """Resolve supplier part links against this product, sharing colours across sizes."""
    from media_links import resolved_links
    result = []
    for original in images:
        image = dict(original)
        color, parts, linked = resolved_links(image, variants)
        if linked:
            image.update(source_color=color, source_part_ids=parts)
        result.append(image)
    return result


async def repair_assets(ls, destination, images, variants=None, remote_snapshot=None):
    if defer_images.get():
        return {'uploaded':0,'skipped':0,'failed':0,'uncertain':0,'messages':[], 'deferred':True}
    from image_auto import sync_images, read_bytes, retry_read
    assert_service_compatible(ls)
    from media_links import matcher_runtime
    totals = {'uploaded':0,'skipped':0,'failed':0,'uncertain':0,'messages':[],
              'image_matcher': matcher_runtime()}
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow('SELECT product_id FROM lightspeed_family_exports WHERE store_domain=$1 AND destination_id=$2', ls.domain_prefix, destination)
        group = await conn.fetchrow('SELECT product_id,variant_ids FROM lightspeed_export_groups WHERE store_domain=$1 AND lightspeed_product_id=$2', ls.domain_prefix, destination)
        if group:
            row = group
            if variants is None:
                ids = group['variant_ids']
                if isinstance(ids, str): ids = json.loads(ids)
                variants = [dict(v) for v in await conn.fetch('SELECT * FROM product_variants WHERE product_id=$1 AND id=ANY($2::varchar[]) AND is_active IS NOT FALSE', group['product_id'], [str(i) for i in ids])]
        if not row:
            row = await conn.fetchrow('SELECT id AS product_id FROM products WHERE lightspeed_product_id=$1', destination)
        if variants is None and row:
            variants = [dict(v) for v in await conn.fetch('SELECT * FROM product_variants WHERE product_id=$1 AND is_active IS NOT FALSE', row['product_id'])]
        # A split group may contain only XL while the supplier image references XS.
        # Resolve links using the complete source product before selecting the group.
        colour_variants = [dict(v) for v in await conn.fetch('SELECT variant_sku,color FROM product_variants WHERE product_id=$1', row['product_id'])] if row else list(variants or [])
        source_product = await conn.fetchrow('SELECT supplier_sku FROM products WHERE id=$1', row['product_id']) if row else None
    if variants:
        # Image repair targets existing members, independently of stock and price.
        # Zero stock or missing price must not prevent an image being assigned.
        variants = [dict(v) for v in variants if v.get('is_active') is not False]
    if variants:
        # Reconstruct exact links from already-imported BulkData rows. No supplier
        # request, filename inference or colour guessing is involved.
        by_url = {str(i.get('url') or '').strip(): dict(i) for i in images if i.get('url')}
        for variant in variants:
            meta = variant.get('bulk_metadata') or {}
            if isinstance(meta, str): meta = json.loads(meta)
            if not isinstance(meta, dict): continue
            if str(meta.get('product_id') or '').strip().casefold() != sku(variant): continue
            urls = str(meta.get('image_url') or (meta.get('raw_fields') or {}).get('image') or '').splitlines()
            for url in urls:
                url = url.strip()
                if not url.startswith(('https://', 'http://')): continue
                image = by_url.setdefault(url, {'url': url, 'media_type': 'image'})
                parts = image.get('source_part_ids') or []
                if isinstance(parts, str): parts = json.loads(parts)
                from media_links import usable
                image['source_part_ids'] = list(dict.fromkeys([str(p) for p in parts if usable(p)] + [str(variant['variant_sku'])]))
        images = list(by_url.values()) + [dict(i) for i in images if not i.get('url')]
        images = expand_colour_links(images, colour_variants)
        from media_links import associate_sanmar_images
        images = associate_sanmar_images(images, colour_variants, source_product['supplier_sku'] if source_product else '')
        def general(i):
            parts = i.get('source_part_ids') or []
            if isinstance(parts, str): parts = json.loads(parts)
            return not parts and not str(i.get('source_color') or i.get('color') or '').strip()
        images = [i for i in images if general(i) or any(matched_images(v, [i]) for v in variants)]
    from routes.media import stored_export_images
    if images:
        if not row:
            raise ValueError('Cannot resolve source product for stored image export')
        images = await stored_export_images(row['product_id'], images)
    family = remote_snapshot or await asyncio.to_thread(ls.remote_family, destination)
    remote = members(family, expected_skus=[sku(v) for v in variants or []])
    ls._repair_digest_cache = {}
    cached = {}; semaphore = asyncio.Semaphore(3)
    async def prepare(image):
        async with semaphore:
            from export_safety import image_key
            key = image_key(image)
            try:
                import hashlib
                data=await retry_read(read_bytes,image)
                normalized=dict(image,image_base64=base64.b64encode(data).decode())
                # Hash/decode each source once, shared by every size using the image.
                normalized.update(_image_bytes=data,_source_sha256=hashlib.sha256(data).hexdigest(),
                                  _source_image_key=image_key(normalized))
                cached[key]=normalized
            except Exception: cached[key]=image
    await asyncio.gather(*(prepare(i) for i in images if i.get('media_type', 'image') == 'image'))
    from export_safety import image_key
    totals = await sync_images(FamilyImages(ls, destination, family.get('images')), destination, [dict(cached.get(image_key(i), i), _source_image_key=image_key(i)) for i in images])
    if not variants: return totals
    if totals.get('_new_uncertain_write'):
        totals['messages'].append('Family gallery has an unverified write; checking variant images independently without repeating that gallery upload')
    abort = asyncio.Event()
    async def repair_variant(variant):
        async with semaphore:
            if abort.is_set():
                return {'uploaded':0,'skipped':0,'failed':1,'uncertain':0,'messages':['Image batch stopped after a local configuration error']}
            from export_safety import image_key
            selected = matched_images(variant, images)
            if not selected:
                return {'uploaded':0,'skipped':0,'failed':1,'uncertain':0,'messages':['No explicit colour/part image association for '+sku(variant)+'; refresh supplier media']}

            item = remote.get(sku(variant))
            if not item: raise ValueError('Missing destination member for image assignment: ' + sku(variant))
            target = str(item['id'])
            # Always audit the member itself. Gallery membership and an old journal
            # acknowledgement do not prove the variant still has its image.
            outcome = await sync_images(MemberImages(ls, target), 'variant:' + target, [cached.get(image_key(i), i) for i in selected], audit_completed=True)
            if outcome.get('_fatal_local_error'): abort.set()
            return outcome
    outcomes = await asyncio.gather(*(repair_variant(v) for v in variants), return_exceptions=True)
    for outcome in outcomes:
        if isinstance(outcome, Exception):
            totals['failed'] += 1; totals['messages'].append(str(outcome))
        elif outcome:
            for key in ('uploaded', 'skipped', 'failed', 'uncertain'): totals[key] += outcome[key]
            totals['messages'].extend(outcome['messages'])
    if totals['failed'] or totals['uncertain']:
        totals['messages'].append('Images pending; retry Sync Selected to reconcile without recreating variants')
    return totals





