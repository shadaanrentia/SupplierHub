"""Independent size families; verified ownership, durable writes and safe resumption."""
from sync_context import defer_images
import asyncio
import json
import math
import time
import deps
from size_order import sort_variants, sort_export_variants
from single_family import members, sku, repair_assets, append_payload, attribute_order


def family_name(product, group, variants):
    from export_format import family_title
    if group.get('export_mode') != 'size_families':
        return family_title(product['product_name'], product['supplier_sku'], group['group_number'])
    from size_order import size_key
    from export_format import product_title
    sizes = sorted({str(v.get('size') or 'Unspecified') for v in variants}, key=size_key)
    label = sizes[0] if len(sizes) == 1 else sizes[0] + '–' + sizes[-1]
    return f"{product_title(product['product_name'],product['supplier_sku'])} — Sizes {label} ({int(group['group_number']):02d})"


def verify_group_destination(family, expected_skus, found, destination, expected_name, group_number):
    """Verify ownership using source SKU aliases; retain all conflict checks."""
    expected = {str(value).strip().lower() for value in expected_skus}
    remote = members(family, expected_skus=expected)
    remote_ids = {str(value['id']) for value in remote.values()}
    saved_verified = destination is not None and str(destination) in remote_ids
    outside = sorted(set(remote) - expected)
    conflicting_ids = sorted({str(value['id']) for value in found.values()} - remote_ids)
    reasons = []
    if outside:
        reasons.append('SKUs outside this group: ' + ', '.join(outside[:8]))
    if conflicting_ids:
        reasons.append('SKU searches found members in another family: ' + ', '.join(conflicting_ids[:4]))
    # A complete, exact SKU set identifies a renamed family independently of its title.
    complete_sku_match = bool(expected) and set(remote) == expected
    if not saved_verified and not complete_sku_match and family.get('name') != expected_name:
        reasons.append('expected name=' + repr(expected_name) + '; actual name=' + repr(family.get('name')))
    if not remote:
        reasons.append('destination family has no identifiable members')
    if reasons:
        raise ValueError('Destination ownership could not be verified; no writes made. '
                         + 'Group ' + str(group_number) + '; family=' + str(family.get('id') or 'unknown')
                         + '; ' + '; '.join(reasons))
    return remote


async def export_families(ls, product, variants, images, markup, category_id):
    from export_format import assert_service_compatible
    assert_service_compatible(ls)
    from export_safety import decode, validate_prices, LIMIT
    validate_prices(product, variants)
    if not defer_images.get() and not any(i.get('media_type','image') == 'image' and (i.get('url') or i.get('image_base64')) for i in images):
        raise ValueError('No usable source images; refresh supplier media')
    for variant in variants:
        try:
            quantity = float(variant.get('inventory'))
            if not math.isfinite(quantity) or quantity < 0: raise ValueError()
        except (TypeError,ValueError,OverflowError):
            raise ValueError('Missing or invalid variant inventory: '+sku(variant))
    key, domain = product['id'], ls.domain_prefix
    started=time.perf_counter()
    completed, warnings = [], []
    async with deps.pool.acquire() as conn:
        lock = 'export-review:' + key
        if not await conn.fetchval('SELECT pg_try_advisory_lock(hashtext($1))', lock):
            raise ValueError('This product is already exporting')
        current = None
        try:
            from pricing_rules import prepare_export_pricing, variant_retail
            product, variants, markup = await prepare_export_pricing(conn, product, variants, markup)
            groups = [dict(r) for r in await conn.fetch('SELECT * FROM lightspeed_export_groups WHERE product_id=$1 AND store_domain=$2 ORDER BY group_number', key, domain)]
            ids = [str(i) for g in groups for i in decode(g['variant_ids'])]
            if not groups or len(ids) != len(set(ids)) or set(ids) != {str(v['id']) for v in variants}:
                raise ValueError('Review and save a plan covering every eligible variant exactly once')
            if any(g.get('export_mode') not in ('size_families','colour_families') for g in groups):
                raise ValueError('Old shared-family plan: use Verify deleted destinations, then preview and save size families')
            if any(g.get('export_mode') == 'colour_families' for g in groups) and not any(g.get('lightspeed_product_id') for g in groups):
                raise ValueError('Rebuild the unexported colour plan as size families in Export Review')
            if any(g['state'] == 'running' for g in groups):
                raise ValueError('Another worker is running; stop it before resuming')
            supplier = await asyncio.to_thread(ls._get_or_create_supplier, product.get('supplier_name')) if product.get('supplier_name') else None
            brand = await asyncio.to_thread(ls._get_or_create_brand, product.get('brand')) if product.get('brand') else None
            attrs = await asyncio.to_thread(ls._ensure_variant_attributes, ['Color', 'Size'])
            outlet = await asyncio.to_thread(ls._get_inventory_outlet_id)
            if not outlet: raise ValueError('Configure a Lightspeed inventory outlet')
            for group in groups:
                current = group
                group_started=time.perf_counter()
                selected = {str(i) for i in decode(group['variant_ids'])}
                batch = sort_variants([dict(v) for v in variants if str(v['id']) in selected])
                if not 0 < len(batch) <= LIMIT: raise ValueError(f'Each family must contain 1–{LIMIT} eligible variants')
                name = family_name(product, group, batch)
                destination = group.get('lightspeed_product_id')
                # A stored, live destination is reconciled by member IDs and exact SKUs,
                # not a global search that can return unrelated duplicates.
                family = None
                found = {}
                deleted = destination and await asyncio.to_thread(ls.remote_product_deleted, destination)
                if destination and not deleted:
                    family = await asyncio.to_thread(ls.remote_family, str(destination))
                    owned = members(family, expected_skus=[sku(v) for v in batch])
                    if str(destination) not in {str(v['id']) for v in owned.values()}:
                        raise ValueError('Saved destination is not a member of its returned family')
                    if not set(owned).issubset({sku(v) for v in batch}):
                        raise ValueError('Saved destination contains SKUs outside this reviewed group')
                    # Only missing members need conflict checks before an addition.
                    missing_skus = [v['variant_sku'] for v in batch if sku(v) not in owned]
                    if missing_skus:
                        found = await asyncio.to_thread(ls.lookup_skus, missing_skus)
                else:
                    found = await asyncio.to_thread(ls.lookup_skus, [v['variant_sku'] for v in batch] + [group['export_sku']])
                if deleted:
                    if found: raise ValueError('Deleted destination has SKUs still live elsewhere; migration review required')
                    found = await asyncio.to_thread(ls.lookup_skus, [v['variant_sku'] for v in batch] + [group['export_sku']])
                    if found: raise ValueError('Destination changed during deletion verification')
                    await conn.execute("UPDATE lightspeed_export_groups SET lightspeed_product_id=NULL,state='planned',message='Verified deleted destination',updated_at=NOW() WHERE id=$1",group['id'])
                    await conn.execute('DELETE FROM lightspeed_family_additions WHERE product_id=$1 AND store_domain=$2 AND variant_sku=ANY($3::text[])',key,domain,[sku(v) for v in batch])
                    group.update(state='planned',lightspeed_product_id=None)
                    destination = None
                if destination or found:
                    candidate = str(destination or next(iter(found.values()))['id'])
                    family = family or await asyncio.to_thread(ls.remote_family, candidate)
                    remote = verify_group_destination(
                        family, [sku(v) for v in batch], found, destination, name, group['group_number'])
                    destination = str(next(iter(remote.values()))['id'])
                    await conn.execute('UPDATE lightspeed_export_groups SET lightspeed_product_id=$2 WHERE id=$1',group['id'],destination)
                elif group['state'] in ('uncertain','creating','done','images_pending'):
                    raise ValueError('Previous creation outcome cannot be verified; no duplicate creation sent')
                await conn.execute("UPDATE lightspeed_export_groups SET state='running',message='Syncing reviewed family',updated_at=NOW() WHERE id=$1",group['id'])
                if not family:
                    from deps import calculate_sale_price
                    cost = min(float(v['price']) for v in batch)
                    payload = dict(product, product_name=name, supplier_sku=group['export_sku'], category_id=category_id, effective_markup_percentage=markup)
                    if len(batch) == 1:
                        # Legacy creation treats a single variant as STANDARD and loses its source SKU.
                        order = ['Color','Size']
                        body = append_payload(batch[0],order,markup,supplier,str(outlet))
                        body['codes'].append({'type':'CUSTOM','code':group['export_sku']})
                        created = await asyncio.to_thread(ls.family_request,'POST','product_families',
                            {'name':name,'classification':'VARIANT','variant_attribute_ids':[attrs[n] for n in order],'products':[body]})
                        ids = (created.get('data') or {}).get('product_ids') or []
                        destination = ids[0] if len(ids) == 1 else None
                    else:
                        created = await ls._create_product(payload,batch,cost,min(variant_retail(v,markup) for v in batch),supplier,brand)
                        destination = (created.get('_existing_product_id') or created.get('id')) if isinstance(created,dict) else created
                    if not destination: raise ValueError('Creation returned no destination ID; reconcile before retrying')
                    destination = str(destination)
                    # Save immediately: image/inventory failures must never lose creation identity.
                    await conn.execute("UPDATE lightspeed_export_groups SET lightspeed_product_id=$2,updated_at=NOW() WHERE id=$1",group['id'],destination)
                    family = await asyncio.to_thread(ls.remote_family,destination)
                    if family.get('name') != name or not set(members(family)).issubset({sku(v) for v in batch}):
                        raise ValueError('Created family readback did not match reviewed group')
                remote = members(family)
                missing = [v for v in batch if sku(v) not in remote]
                if len(remote) + len(missing) > LIMIT: raise ValueError(f'Family would exceed the maximum of {LIMIT} variants')
                if missing:
                    for v in missing:
                        journal = await conn.fetchrow('SELECT state FROM lightspeed_family_additions WHERE product_id=$1 AND store_domain=$2 AND variant_sku=$3',key,domain,sku(v))
                        if journal: raise ValueError('Previous variant addition is not visible; no duplicate POST sent')
                    async with conn.transaction():
                        for v in missing:
                            await conn.execute("INSERT INTO lightspeed_family_additions(product_id,store_domain,variant_sku,state) VALUES($1,$2,$3,'adding')",key,domain,sku(v))
                    order = attribute_order(family,attrs)
                    await asyncio.to_thread(ls.family_request,'POST',f"product_families/{family['id']}/products",[append_payload(v,order,markup,supplier,str(outlet)) for v in sort_export_variants(missing)])
                    family = await asyncio.to_thread(ls.remote_family,destination)
                    remote = members(family)
                # Only clear uncertain addition records after confirming the
                # complete reviewed SKU set in the remote destination.
                expected_skus = {sku(v) for v in batch}
                if set(remote) != expected_skus:
                    raise ValueError('Family variants do not exactly match the reviewed selection')

                await conn.execute(
                    """
                    DELETE FROM lightspeed_family_additions
                    WHERE product_id = $1
                      AND store_domain = $2
                      AND variant_sku = ANY($3::text[])
                      AND state = 'adding'
                    """,
                    key,
                    domain,
                    sorted(expected_skus),
                )

                family = await asyncio.to_thread(ls.update_family_metadata,destination,name,category_id,brand,product.get('description'),remote_snapshot=family)
                await ls._sync_existing_variants(destination,batch,0,name,supplier,True,markup,remote_snapshot=family)
                await conn.execute("UPDATE lightspeed_export_groups SET state='images_pending',message='Variants, prices and inventory confirmed; syncing images',updated_at=NOW() WHERE id=$1",group['id'])
                # Write channels per member, then verify the whole family once.
                activation_slots = asyncio.Semaphore(6)
                activation_members = [m for m in members(family).values()
                    if not (isinstance(m.get('active'),dict) and m['active'].get('in_store') is True and m['active'].get('ecwid') is True)]
                async def activate_member(member):
                    async with activation_slots:
                        if not await asyncio.to_thread(ls._activate_online_store_product,str(member['id'])):
                            raise ValueError('POS/eCommerce activation failed for variant ' + str(member.get('sku') or member['id']))
                activation_results = await asyncio.gather(
                    *(activate_member(member) for member in activation_members),return_exceptions=True)
                activation_errors=[str(e) for e in activation_results if isinstance(e,Exception)]
                if activation_errors: raise ValueError('; '.join(activation_errors[:5]))
                if activation_members:
                    confirmed=await asyncio.to_thread(ls.remote_family,destination)
                    confirmed_members=members(confirmed)
                    if set(confirmed_members)!={sku(v) for v in batch}:
                        raise ValueError('Family membership changed during channel verification')
                    # Some API representations omit channel fields. Fetch only
                    # those members rather than treating an omitted field as false.
                    async def fill_missing_channels(member):
                        active=member.get('active')
                        if isinstance(active,dict) and 'in_store' in active and 'ecwid' in active: return
                        async with activation_slots:
                            response=await asyncio.to_thread(ls.family_request,'GET','products/'+str(member['id']))
                        row=response.get('data') or {}
                        if str(row.get('id') or '')!=str(member['id']):
                            raise ValueError('Channel readback returned a different product')
                        member['active']=row.get('active')
                    await asyncio.gather(*(fill_missing_channels(m) for m in confirmed_members.values()))
                    unconfirmed=[m.get('sku') for m in confirmed_members.values()
                        if not (isinstance(m.get('active'),dict) and m['active'].get('in_store') is True and m['active'].get('ecwid') is True)]
                    if unconfirmed: raise ValueError('POS/eCommerce activation not confirmed for: '+', '.join(str(s) for s in unconfirmed[:5]))
                    family=confirmed
                import logging
                logging.getLogger(__name__).info('Export family %s: metadata, stock and channels took %.1fs; starting images',group['group_number'],time.perf_counter()-group_started)
                completed.append(destination)
                result = await repair_assets(ls,destination,images,variants=batch,remote_snapshot=family)
                pending = result['failed'] or result['uncertain']
                text = '; '.join(result['messages'])[:1500] if pending else 'Family, variant prices, inventory and images synchronized'
                await conn.execute("UPDATE lightspeed_export_groups SET state=$2,message=$3,updated_at=NOW() WHERE id=$1",group['id'],'images_pending' if pending else 'done',text)
                logging.getLogger(__name__).info('Export family %s finished in %.1fs; image uploads=%s, reused=%s, failed=%s, uncertain=%s',group['group_number'],time.perf_counter()-group_started,result['uploaded'],result['skipped'],result['failed'],result['uncertain'])
                if pending:
                    for detail in list(dict.fromkeys(result['messages']))[:12]:
                        logging.getLogger(__name__).warning('Family %s image pending: %s',group['group_number'],detail)
                    warnings.append(f"Family {group['group_number']}: {text}")
            return {'success':True,'lightspeed_id':completed[0],'destination_ids':completed,'image_warnings':warnings}
        except Exception as exc:
            if current:
                await conn.execute("UPDATE lightspeed_export_groups SET state='uncertain',message=$2,updated_at=NOW() WHERE id=$1",current['id'],str(exc)[:1500])
            return {'success':False,'error':str(exc),'completed_groups':completed}
        finally:
            await conn.execute('SELECT pg_advisory_unlock(hashtext($1))',lock)





