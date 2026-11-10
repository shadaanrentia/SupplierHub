"""Review split families and repair images without changing product prices."""
import asyncio
import hashlib
import json
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel, Field
import deps
from deps import get_admin_user, get_current_user, new_id, row_to_dict
from export_safety import decode, grouped_variants, validate_prices, repair_images, image_key, export_name, LIMIT

from product_readiness import load_readiness, public_state
from sku_eligibility import (
    eligible_variants,
    eligibility_reason,
    new_export_eligible_variants,
)

router = APIRouter(prefix='/api/export-review', tags=['Export review'])


async def init_export_review_schema(conn):
    await conn.execute('''CREATE TABLE IF NOT EXISTS lightspeed_review_jobs (
        id VARCHAR(64) PRIMARY KEY, product_id VARCHAR(64) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        store_domain TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
        result JSONB NOT NULL DEFAULT '{}'::jsonb, updated_at TIMESTAMP DEFAULT NOW()
    )''')
    await conn.execute("UPDATE lightspeed_review_jobs SET status='interrupted' WHERE status='running'")


async def service():
    from routes.lightspeed import _get_ls_service
    ls = await _get_ls_service()
    if ls.mock_mode:
        raise HTTPException(400, 'Configure a real Lightspeed connection')
    return ls


async def snapshot(conn, product_id):
    row = await conn.fetchrow('SELECT p.*,s.supplier_name FROM products p LEFT JOIN suppliers s ON s.id=p.supplier_id WHERE p.id=$1',product_id)
    if not row:
        raise HTTPException(404,'Product not found')
    product = row_to_dict(row)
    product['product_name'] = export_name(product.get('product_name'),product.get('supplier_sku'))
    variants = [row_to_dict(r) for r in await conn.fetch('SELECT * FROM product_variants WHERE product_id=$1 AND is_active IS DISTINCT FROM FALSE ORDER BY variant_sku,id',product_id)]
    images = [row_to_dict(r) for r in await conn.fetch("SELECT * FROM product_media WHERE product_id=$1 AND media_type='image' ORDER BY is_primary DESC,created_at",product_id)]
    return product, eligible_variants(variants), images

async def new_split_snapshot(conn, product_id):
    """
    Return a strict snapshot for creating new Lightspeed split groups.

    Every active supplier variant must be eligible for a new export.
    Zero-stock and otherwise ineligible variants must not silently
    disappear from a split plan.
    """
    product, _, images = await snapshot(conn, product_id)

    raw_rows = await conn.fetch(
        """
        SELECT *
        FROM product_variants
        WHERE product_id = $1
          AND is_active IS DISTINCT FROM FALSE
        ORDER BY variant_sku, id
        """,
        product_id,
    )

    active_variants = [row_to_dict(row) for row in raw_rows]
    eligible = new_export_eligible_variants(active_variants)

    eligible_ids = {str(v["id"]) for v in eligible}

    excluded = [
        v for v in active_variants
        if str(v["id"]) not in eligible_ids
    ]

    if excluded:
        details = []
        for variant in excluded[:20]:
            sku = variant.get("variant_sku") or variant.get("id")
            reason = eligibility_reason(variant) or "not eligible for new export"
            details.append(f"{sku}: {reason}")

        suffix = (
            f"; and {len(excluded) - 20} more"
            if len(excluded) > 20
            else ""
        )

        raise HTTPException(
            400,
            "Split plan blocked. Resolve all ineligible active variants "
            "before creating new Lightspeed groups: "
            + "; ".join(details)
            + suffix,
        )

    return product, eligible, images


def fingerprint(product, variants):
    return hashlib.sha256(json.dumps([product['id'],product.get('lightspeed_product_id'),[(v['id'],v['variant_sku'],v.get('color'),v.get('size')) for v in variants], 'size_families'],sort_keys=True).encode()).hexdigest()


async def _review_listing(search, oversized, issues_only, page, supplier_id=None):
    """Read list summaries without loading image binaries or full asset metadata."""
    async with deps.pool.acquire() as conn:
        rows=[row_to_dict(r) for r in await conn.fetch("""SELECT
            p.id,p.supplier_id,p.supplier_sku,p.product_name,p.base_price,p.brand,p.category,
            p.lightspeed_product_id,p.lightspeed_sync_status,p.price_needs_review,s.supplier_name
            FROM products p LEFT JOIN suppliers s ON s.id=p.supplier_id
            WHERE (p.product_name ILIKE $1 OR p.supplier_sku ILIKE $1)
            AND ($2::text IS NULL OR p.supplier_id=$2)
            AND (NOT $3::boolean OR (SELECT COUNT(*) FROM product_variants v
                 WHERE v.product_id=p.id AND v.is_active IS DISTINCT FROM FALSE)>=200)
            ORDER BY p.supplier_sku,p.id""",'%'+search.strip()+'%',supplier_id if supplier_id and supplier_id!='all' else None,oversized)]
        visible=[];total=0;start=(page-1)*50
        for offset in range(0,len(rows),100):
            batch=rows[offset:offset+100]
            states=await load_readiness(conn,batch,include_assets=False)
            for product in batch:
                state=states[product['id']]
                if oversized and state['variants_count'] < LIMIT:continue
                if issues_only and state['is_valid'] and not state['previous_export_failed'] and state.get('status')!='images_pending':continue
                if start<=total<start+50:
                    product.update(public_state(state))
                    product['product_name']=export_name(product.get('product_name'),product.get('supplier_sku'))
                    product.update(variant_count=state['variants_count'],image_count=state['images_count'])
                    visible.append(product)
                total+=1
            # Release each batch's variant dictionaries before the next read.
            del states
    return {'products':visible,'page':page,'total':total}


@router.get('/products')
async def products(search: str='', oversized: bool=True, issues_only: bool=False, page: int=Query(1,ge=1), supplier_id:str=None, user=Depends(get_current_user)):
    try:
        return await asyncio.wait_for(_review_listing(search,oversized,issues_only,page,supplier_id),timeout=25)
    except asyncio.TimeoutError:
        raise HTTPException(503,'Export Review listing exceeded its read time limit. Check backend/database load and retry; no products were changed.')


@router.get('/products/{product_id}')
async def detail(product_id:str,user=Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        product, variants, images=await snapshot(conn,product_id)
        readiness=(await load_readiness(conn,[product]))[product_id]
        settings=await conn.fetchrow("SELECT lightspeed_store_id FROM settings WHERE id='system_settings'")
        domain=str(settings['lightspeed_store_id'] or '').strip() if settings else ''
        groups=[row_to_dict(r) for r in await conn.fetch('SELECT * FROM lightspeed_export_groups WHERE product_id=$1 AND store_domain=$2 ORDER BY group_number',product_id,domain)]
        for group in groups:
            group['variant_ids']=decode(group['variant_ids'])
        jobs=[row_to_dict(r) for r in await conn.fetch('SELECT * FROM lightspeed_review_jobs WHERE product_id=$1 ORDER BY updated_at DESC LIMIT 10',product_id)]
        image_results=[row_to_dict(r) for r in await conn.fetch('''SELECT * FROM lightspeed_export_image_results WHERE store_domain=$1 AND
            (destination_id=$2 OR destination_id IN (SELECT lightspeed_product_id FROM lightspeed_export_groups WHERE product_id=$3 AND store_domain=$1)) ORDER BY updated_at DESC''',domain,product.get('lightspeed_product_id') or '',product_id)]
    issue=''
    try:validate_prices(product,variants)
    except ValueError as exc:issue=str(exc)
    return {'readiness':public_state(readiness),'product':product,'groups':groups,'jobs':jobs,'image_results':image_results,'price_issue':issue,'images':len(images),'source_images':[{'key':image_key(i),'url':i.get('url'),'id':i.get('id')} for i in images],'variant_count':len(variants)}


@router.get('/products/{product_id}/destination-images')
async def destination_images(product_id: str, user=Depends(get_admin_user)):
    """Read-only remote image evidence for this product's stored destinations."""
    ls = await service()
    async with deps.pool.acquire() as conn:
        product, variants, source_images = await snapshot(conn, product_id)
        groups = await conn.fetch('SELECT group_number,lightspeed_product_id FROM lightspeed_export_groups WHERE product_id=$1 AND store_domain=$2 ORDER BY group_number', product_id, ls.domain_prefix)
    destinations = [{'group_number':g['group_number'], 'destination_id':str(g['lightspeed_product_id'])} for g in groups if g.get('lightspeed_product_id')]
    if not destinations and product.get('lightspeed_product_id'):
        destinations = [{'group_number':1, 'destination_id':str(product['lightspeed_product_id'])}]
    results = []
    for destination in destinations:
        try:
            family = await asyncio.to_thread(ls.remote_family, destination['destination_id'])
            results.append(dict(destination, family_id=family['id'], description=family.get('description'), images=family.get('images'),
                                members=[{'id':v.get('id'),'sku':v.get('sku'),'images':v.get('images')} for v in family['products']]))
        except Exception as exc:
            results.append(dict(destination, error=str(exc)))
    from single_family import matched_images, sku, expand_colour_links
    from media_links import associate_sanmar_images, matcher_runtime
    source_images = associate_sanmar_images(expand_colour_links(source_images, variants), variants, product.get('supplier_sku'))
    source_link_issues = []
    for variant in variants:
        meta = variant.get('bulk_metadata') or {}
        if isinstance(meta, str): meta = json.loads(meta)
        if not isinstance(meta, dict): meta = {}
        bulk_url = meta.get('image_url') or (meta.get('raw_fields') or {}).get('image') or ''
        linked = matched_images(variant, source_images)
        bulk_linked = str(meta.get('product_id') or '').strip().casefold() == sku(variant) and any(u.strip().startswith(('https://','http://')) for u in str(bulk_url).splitlines())
        if not linked and not bulk_linked:
            source_link_issues.append({'sku':variant.get('variant_sku'), 'color':variant.get('color'), 'size':variant.get('size'),
                                       'bulk_record_sku':meta.get('product_id'), 'bulk_image_url':bulk_url})
    journal_destinations = {d['destination_id'] for d in destinations}
    for result in results:
        journal_destinations.update('variant:' + str(v['id']) for v in result.get('members', []) if v.get('id'))
    async with deps.pool.acquire() as conn:
        journals = await conn.fetch('SELECT destination_id,image_key,status,message,updated_at FROM lightspeed_export_image_results WHERE store_domain=$1 AND destination_id=ANY($2::text[]) ORDER BY destination_id,image_key', ls.domain_prefix, sorted(journal_destinations))
    sources = [{**{k:i.get(k) for k in ('id','url','source_part_ids','source_color','color','media_type','association_source')}, 'image_key':image_key(i)} for i in source_images]
    return {'product_id':product_id,'read_only':True,'image_matcher':matcher_runtime(),
            'supplier_sku':product.get('supplier_sku'),'destinations':results,'source_images':sources,
            'image_journals':[dict(j) for j in journals],
            'source_variants':[{'sku':v.get('variant_sku'),'color':v.get('color'),'size':v.get('size'),
                                'matched_image_keys':[image_key(i) for i in matched_images(v,source_images)]} for v in variants],
            'source_link_issues':source_link_issues}


@router.get('/cleanup-preview')
async def cleanup_preview(search: str='', supplier_id: str=None, page: int=Query(1,ge=1), user=Depends(get_admin_user)):
    """Read-only report of remote variants whose current supplier data is ineligible."""
    ls=await service()
    from sku_eligibility import eligibility_reason
    from single_family import members
    limit=50
    async with deps.pool.acquire() as conn:
        products=[row_to_dict(r) for r in await conn.fetch("""SELECT p.id,p.product_name,p.supplier_sku,p.supplier_id,
            p.lightspeed_product_id,s.supplier_name FROM products p LEFT JOIN suppliers s ON s.id=p.supplier_id
            WHERE (p.product_name ILIKE $1 OR p.supplier_sku ILIKE $1)
            AND ($2::varchar IS NULL OR p.supplier_id=$2)
            AND (p.lightspeed_product_id IS NOT NULL OR EXISTS(
                SELECT 1 FROM lightspeed_export_groups g WHERE g.product_id=p.id AND g.store_domain=$3
                AND g.lightspeed_product_id IS NOT NULL))
            ORDER BY p.updated_at DESC,p.id""",'%'+search.strip()+'%',supplier_id,ls.domain_prefix)]
        total=len(products)
        visible=products[(page-1)*limit:page*limit]
        ids=[p['id'] for p in visible]
        variants_by_product={}
        for row in await conn.fetch("SELECT * FROM product_variants WHERE product_id=ANY($1::varchar[]) AND is_active IS DISTINCT FROM FALSE ORDER BY product_id,variant_sku",ids):
            variants_by_product.setdefault(row['product_id'],[]).append(row_to_dict(row))
        groups_by_product={}
        for row in await conn.fetch("SELECT product_id,lightspeed_product_id FROM lightspeed_export_groups WHERE product_id=ANY($1::varchar[]) AND store_domain=$2 AND lightspeed_product_id IS NOT NULL",ids,ls.domain_prefix):
            groups_by_product.setdefault(row['product_id'],[]).append(str(row['lightspeed_product_id']))
    results=[]
    for product in visible:
        variants=variants_by_product.get(product['id'],[])
        reasons={str(v.get('variant_sku') or '').strip().casefold():eligibility_reason(v) for v in variants}
        reasons={sku:reason for sku,reason in reasons.items() if sku and reason}
        destinations=set(groups_by_product.get(product['id'],[]))
        if product.get('lightspeed_product_id'):destinations.add(str(product['lightspeed_product_id']))
        remote=[];errors=[]
        for destination_id in sorted(destinations):
            try:
                family=await asyncio.to_thread(ls.remote_family,destination_id)
                source_skus={str(v.get('variant_sku') or '').strip().casefold() for v in variants if v.get('variant_sku')}
                remote_members=members(family,expected_skus=source_skus)
                if not remote_members or not set(remote_members).issubset(source_skus):
                    raise ValueError('Remote family contains SKUs that do not belong to this SupplierHub product; candidate matching was withheld')
                for sku,reason in reasons.items():
                    item=remote_members.get(sku)
                    if item:
                        remote.append({'variant_sku':sku,'lightspeed_variant_id':str(item.get('id')),
                            'reason':reason,'destination_id':destination_id,'product_name':product.get('product_name'),
                            'supplier_sku':product.get('supplier_sku')})
            except Exception as exc:
                errors.append({'destination_id':destination_id,'message':str(exc)[:1000]})
        if remote or errors:
            results.append({'product_id':product['id'],'product_name':product.get('product_name'),
                'supplier_sku':product.get('supplier_sku'),'supplier_name':product.get('supplier_name'),
                'candidates':remote,'errors':errors})
    return {'products':results,'page':page,'limit':limit,'total_products_checked':len(visible),
        'matched_products':len(results),'deletion_enabled':False,
        'notice':'Read-only preview. No Lightspeed variants were changed or deleted.'}


@router.post('/products/{product_id}/split-preview')
async def split_preview(product_id:str,user=Depends(get_admin_user)):
    ls=await service()
    async with deps.pool.acquire() as conn:
        product, variants, images = await new_split_snapshot(conn, product_id)
        existing=await conn.fetchval('SELECT COUNT(*) FROM lightspeed_export_groups WHERE product_id=$1 AND store_domain=$2',product_id,ls.domain_prefix)
    async with deps.pool.acquire() as conn:
        saved=[dict(r) for r in await conn.fetch('SELECT * FROM lightspeed_export_groups WHERE product_id=$1 AND store_domain=$2',product_id,ls.domain_prefix)]
        running=await conn.fetchval("SELECT COUNT(*) FROM lightspeed_review_jobs WHERE product_id=$1 AND status='running'",product_id)
    if product.get('lightspeed_product_id') or running or any(g.get('lightspeed_product_id') or g['state']!='planned' for g in saved):
        raise HTTPException(409,'Only unexported planned groups can be rebuilt. Exported/running/uncertain results need migration review')
    if len(variants)<=LIMIT:
        raise HTTPException(400,f'This page splits products with more than {LIMIT} eligible variants')
    if len({str(v['variant_sku']).strip().casefold() for v in variants})!=len(variants):
        raise HTTPException(400,'Resolve duplicate variant SKUs first')
    groups=grouped_variants(variants)
    if not groups or any(
        not 0 < len(group) <= LIMIT
        for group in groups
    ):
        raise HTTPException(
            400,
            f'Generated split groups must contain between 1 and {LIMIT} variants'
        )
    from multi_family import family_name
    return {'replaces_unexported_plan':bool(saved),'digest':fingerprint(product,variants),'store_domain':ls.domain_prefix,'groups':[
        {'number':i,'name':family_name(product, {'group_number':i,'export_mode':'size_families'}, rows),'count':len(rows),
         'sizes':sorted({str(v.get('size') or 'Unspecified') for v in rows},key=__import__('size_order').size_key),
         'colors':sorted({str(v.get('color') or 'Unspecified') for v in rows}),
         'variant_skus':[v['variant_sku'] for v in rows]}
        for i,rows in enumerate(groups,1)]}


class Commit(BaseModel):
    digest:str
    store_domain:str



@router.post('/products/{product_id}/split-plan')
async def split_plan(product_id: str, body: Commit, user=Depends(get_admin_user)):
    ls = await service()

    if ls.domain_prefix != body.store_domain:
        raise HTTPException(409, 'Store changed; preview again')

    async with deps.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                'SELECT pg_advisory_xact_lock(hashtext($1))',
                'export-review:' + product_id,
            )

            product, variants, images = await new_split_snapshot(
                conn, product_id
            )

            if fingerprint(product, variants) != body.digest:
                raise HTTPException(409, 'Variants changed; preview again')

            if product.get('lightspeed_product_id'):
                raise HTTPException(
                    409,
                    'Product already exported; migration review required'
                )

            if len(variants) <= LIMIT:
                raise HTTPException(
                    400,
                    f'No longer oversized; split plans require more than {LIMIT} eligible variants'
                )

            # Revalidate SKU uniqueness at commit time.
            skus = [
                str(v.get('variant_sku') or '').strip().casefold()
                for v in variants
            ]

            if any(not sku for sku in skus) or len(skus) != len(set(skus)):
                raise HTTPException(
                    400,
                    'Resolve missing or duplicate variant SKUs before saving the split plan'
                )

            groups = grouped_variants(variants)

            # Every group must respect the Lightspeed family limit.
            if not groups or any(
                not 0 < len(group) <= LIMIT
                for group in groups
            ):
                raise HTTPException(
                    400,
                    f'Generated split groups must contain between 1 and {LIMIT} variants'
                )

            # Every source variant must occur exactly once.
            source_ids = [str(v['id']) for v in variants]
            grouped_ids = [
                str(v['id'])
                for group in groups
                for v in group
            ]

            if (
                len(grouped_ids) != len(set(grouped_ids))
                or set(grouped_ids) != set(source_ids)
            ):
                raise HTTPException(
                    400,
                    'Generated groups do not contain every source variant exactly once'
                )

            # Only now inspect existing saved groups.
            saved = await conn.fetch(
                '''
                SELECT *
                FROM lightspeed_export_groups
                WHERE product_id=$1 AND store_domain=$2
                FOR UPDATE
                ''',
                product_id,
                ls.domain_prefix,
            )

            running = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM lightspeed_review_jobs
                WHERE product_id=$1 AND status='running'
                """,
                product_id,
            )

            if running or any(
                g.get('lightspeed_product_id')
                or g['state'] != 'planned'
                for g in saved
            ):
                raise HTTPException(
                    409,
                    'Exported/running/uncertain groups cannot be replaced'
                )

            # All validation has passed. Replace only unexported plans.
            if saved:
                await conn.execute(
                    '''
                    DELETE FROM lightspeed_export_groups
                    WHERE product_id=$1 AND store_domain=$2
                    ''',
                    product_id,
                    ls.domain_prefix,
                )

            for number, rows in enumerate(groups, 1):
                export_sku = f"SH-{product_id}-G{number:03d}"

                await conn.execute(
                    '''
                    INSERT INTO lightspeed_export_groups
                    (id, product_id, store_domain, group_number,
                     export_sku, variant_ids, export_mode)
                    VALUES ($1,$2,$3,$4,$5,$6::jsonb,'size_families')
                    ''',
                    new_id(),
                    product_id,
                    ls.domain_prefix,
                    number,
                    export_sku,
                    json.dumps([v['id'] for v in rows]),
                )

    return {'success': True}



class GroupResolution(BaseModel):
    group_id: str
    destination_id: str = ''


@router.post('/products/{product_id}/group-resolution')
async def resolve_group(product_id:str, body:GroupResolution, user=Depends(get_admin_user)):
    ls=await service()
    async with deps.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock(hashtext($1))','export-review:'+product_id)
            product,variants,_=await snapshot(conn,product_id)
            if await conn.fetchval("SELECT COUNT(*) FROM lightspeed_review_jobs WHERE product_id=$1 AND status='running'",product_id):
                raise HTTPException(409,'Wait for the running job')
            group=await conn.fetchrow("SELECT * FROM lightspeed_export_groups WHERE id=$1 AND product_id=$2 AND store_domain=$3 AND state='uncertain' FOR UPDATE",body.group_id,product_id,ls.domain_prefix)
            if not group:raise HTTPException(409,'Group is not uncertain; refresh')
            ids=set(str(i) for i in decode(group['variant_ids']))
            skus=[v['variant_sku'] for v in variants if str(v['id']) in ids]
            if len(skus)!=len(ids):raise HTTPException(409,'Source variants changed; migration review required')
            try:
                if body.destination_id:
                    family=await asyncio.to_thread(ls.remote_family,body.destination_id)
                    remote={str(v.get('sku') or '').casefold() for v in family.get('products',[])}
                    if remote != {str(s).casefold() for s in skus} or family.get('name') != product['product_name']+f" — Group {group['group_number']:02d}":
                        raise ValueError('Remote family name or variant SKUs do not match this group')
                else:
                    await asyncio.to_thread(ls.assert_split_skus_available,skus+[group['export_sku']])
            except Exception as exc:raise HTTPException(409,str(exc))
            await conn.execute("UPDATE lightspeed_export_groups SET state=$2,lightspeed_product_id=$3,message='Remote result verified; ready to resume',updated_at=NOW() WHERE id=$1",body.group_id,'done' if body.destination_id else 'planned',body.destination_id or None)
    return {'success':True}


class ImageResolution(BaseModel):
    destination_id: str
    image_key: str
    resolution: str


@router.post('/products/{product_id}/image-resolution')
async def resolve_image(product_id:str, body:ImageResolution, user=Depends(get_admin_user)):
    if body.resolution not in ('present','absent'):
        raise HTTPException(400,'Choose present or absent after checking Lightspeed')
    ls=await service()
    async with deps.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock(hashtext($1))','export-review:'+product_id)
            product,_,_=await snapshot(conn,product_id)
            if await conn.fetchval("SELECT COUNT(*) FROM lightspeed_review_jobs WHERE product_id=$1 AND status='running'",product_id):
                raise HTTPException(409,'Wait for the running job')
            permitted = body.destination_id == str(product.get('lightspeed_product_id') or '') or await conn.fetchval('SELECT COUNT(*) FROM lightspeed_export_groups WHERE product_id=$1 AND store_domain=$2 AND lightspeed_product_id=$3',product_id,ls.domain_prefix,body.destination_id)
            if not permitted:raise HTTPException(400,'Destination does not belong to this product')
            changed=await conn.fetchval("UPDATE lightspeed_export_image_results SET status=$4,message=$5,updated_at=NOW() WHERE store_domain=$1 AND destination_id=$2 AND image_key=$3 AND status IN ('uncertain','failed') RETURNING image_key",ls.domain_prefix,body.destination_id,body.image_key,'uploaded' if body.resolution=='present' else 'retry','Manually checked in Lightspeed: '+body.resolution)
            if not changed:raise HTTPException(409,'Image state changed; refresh')
    return {'success':True}


@router.post('/products/{product_id}/reset-deleted-plan')
async def reset_deleted_plan(product_id:str,user=Depends(get_admin_user)):
    ls=await service()
    async with deps.pool.acquire() as conn:
        lock='export-review:'+product_id
        if not await conn.fetchval('SELECT pg_try_advisory_lock(hashtext($1))',lock):
            raise HTTPException(409,'An export is running; wait for it to finish')
        try:
            product,variants,_=await snapshot(conn,product_id)
            groups=[dict(r) for r in await conn.fetch('SELECT * FROM lightspeed_export_groups WHERE product_id=$1 AND store_domain=$2',product_id,ls.domain_prefix)]
            family=await conn.fetchrow('SELECT * FROM lightspeed_family_exports WHERE product_id=$1 AND store_domain=$2',product_id,ls.domain_prefix)
            if any(g['state']=='running' for g in groups) or await conn.fetchval("SELECT COUNT(*) FROM lightspeed_review_jobs WHERE product_id=$1 AND status='running'",product_id):
                raise HTTPException(409,'Stop the running worker before verifying')
            refs={str(g['lightspeed_product_id']) for g in groups if g.get('lightspeed_product_id')}
            if product.get('lightspeed_product_id'):refs.add(str(product['lightspeed_product_id']))
            if family and family['destination_id']:refs.add(str(family['destination_id']))
            if not refs and any(g['state'] in ('uncertain','creating','done','images_pending') for g in groups):
                raise HTTPException(409,'Earlier creation has no verifiable destination ID; reset blocked. Inspect Lightspeed before resolving this plan')
            codes=[v['variant_sku'] for v in variants]+[g['export_sku'] for g in groups]+[product['supplier_sku']]
            try:
                for ref in refs:
                    if not await asyncio.to_thread(ls.remote_product_deleted,ref):
                        raise HTTPException(409,'A destination is still live. Its plan is preserved; do not reset it')
                for _ in range(2):
                    if await asyncio.to_thread(ls.lookup_skus,codes):
                        raise HTTPException(409,'Some SKUs remain live in Lightspeed. Reset blocked to prevent duplicates')
            except HTTPException:raise
            except Exception as exc:raise HTTPException(502,'Deletion verification failed; plan preserved: '+str(exc)[:500])
            async with conn.transaction():
                # Archive previous plan/errors rather than erase export history.
                await conn.execute("INSERT INTO lightspeed_review_jobs(id,product_id,store_domain,kind,status,result) VALUES($1,$2,$3,'old-plan-archive','completed',$4::jsonb)",new_id(),product_id,ls.domain_prefix,json.dumps({'groups':groups,'reason':'Destinations verified deleted'},default=str))
                await conn.execute('DELETE FROM lightspeed_export_groups WHERE product_id=$1 AND store_domain=$2',product_id,ls.domain_prefix)
                await conn.execute('DELETE FROM lightspeed_family_additions WHERE product_id=$1 AND store_domain=$2',product_id,ls.domain_prefix)
                await conn.execute('DELETE FROM lightspeed_family_exports WHERE product_id=$1 AND store_domain=$2',product_id,ls.domain_prefix)
                await conn.execute("UPDATE products SET lightspeed_product_id=NULL,lightspeed_sync_status='pending',updated_at=NOW() WHERE id=$1",product_id)
            return {'success':True,'message':'Old plan archived. Preview and save new size families'}
        finally:
            await conn.execute('SELECT pg_advisory_unlock(hashtext($1))',lock)


@router.post('/products/{product_id}/{action}')
async def action(product_id:str,action:str,background_tasks:BackgroundTasks,user=Depends(get_admin_user)):
    if action not in ('sync','repair-images'):raise HTTPException(404,'Unknown action')
    ls=await service()
    async with deps.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock(hashtext($1))','export-review:'+product_id)
            product,variants,images=await snapshot(conn,product_id)
            if await conn.fetchval("SELECT COUNT(*) FROM lightspeed_review_jobs WHERE product_id=$1 AND status='running'",product_id):raise HTTPException(409,'A job is already running')
            if action=='sync':
                state=(await load_readiness(conn,[product]))[product_id]
                if not state['is_valid']: raise HTTPException(400,'; '.join(state['validation_errors']))
            elif not product.get('lightspeed_product_id') and not await conn.fetchval('SELECT COUNT(*) FROM lightspeed_export_groups WHERE product_id=$1 AND store_domain=$2 AND lightspeed_product_id IS NOT NULL',product_id,ls.domain_prefix):
                raise HTTPException(400,'No existing Lightspeed destination to repair')
            job_id=new_id()
            await conn.execute("INSERT INTO lightspeed_review_jobs(id,product_id,store_domain,kind,status) VALUES($1,$2,$3,$4,'running')",job_id,product_id,ls.domain_prefix,action)
    background_tasks.add_task(run_action,job_id,product_id,action,ls)
    return {'id':job_id,'status':'running'}


async def run_action(job_id,product_id,kind,ls):
    try:
        async with deps.pool.acquire() as conn:
            product,variants,images=await snapshot(conn,product_id)
            if kind=='sync':
                state=(await load_readiness(conn,[product]))[product_id]
                if not state['is_valid']: raise ValueError('; '.join(state['validation_errors']))
                variants,images=state['variants'],state['images']
                product['lightspeed_category_id']=state['mapped_lightspeed_category_id']
            settings=await conn.fetchrow("SELECT markup_percentage,lightspeed_store_id FROM settings WHERE id='system_settings'")
            if not settings or str(settings['lightspeed_store_id'] or '').strip()!=ls.domain_prefix:
                raise ValueError('Configured store changed')
            markup=float(settings['markup_percentage']) if settings['markup_percentage'] is not None else 40.0
            destinations=await conn.fetch('SELECT lightspeed_product_id FROM lightspeed_export_groups WHERE product_id=$1 AND store_domain=$2 AND lightspeed_product_id IS NOT NULL',product_id,ls.domain_prefix)
        if kind=='sync':
            from routes.lightspeed import _process_lightspeed_product
            result=await _process_lightspeed_product(ls,product,variants,images,markup)
            if result.get('success'):
                async with deps.pool.acquire() as conn:
                    await conn.execute("UPDATE products SET lightspeed_product_id=$2,lightspeed_sync_status=$3,updated_at=NOW() WHERE id=$1",product_id,result['lightspeed_id'],'images_pending' if result.get('image_warnings') else 'synced')
        else:
            ids={str(r['lightspeed_product_id']) for r in destinations}
            if not ids and product.get('lightspeed_product_id'):ids.add(str(product['lightspeed_product_id']))
            results={pid:await repair_images(ls,pid,images) for pid in sorted(ids)}
            # Done/image-pending groups have already confirmed variants/prices/inventory.
            # Asset repair must never promote an uncertain creation to done.
            async with deps.pool.acquire() as conn:
                for destination, assets in results.items():
                    ok=not assets['uncertain'] and not assets['failed']
                    message='Images confirmed' if ok else '; '.join(assets.get('messages') or [])[:1500]
                    await conn.execute("UPDATE lightspeed_export_groups SET state=CASE WHEN $4 THEN 'done' ELSE 'images_pending' END,message=$5,updated_at=NOW() WHERE product_id=$1 AND store_domain=$2 AND lightspeed_product_id=$3 AND state IN ('images_pending','done')",product_id,ls.domain_prefix,destination,ok,message)
            result={'success':not any(r['uncertain'] or r['failed'] for r in results.values()),'images':results}
            if result['success']:
                async with deps.pool.acquire() as conn:
                    remaining=await conn.fetchval("SELECT COUNT(*) FROM lightspeed_export_groups WHERE product_id=$1 AND store_domain=$2 AND state!='done'",product_id,ls.domain_prefix)
                    if not remaining:
                        await conn.execute("UPDATE products SET lightspeed_sync_status='synced',updated_at=NOW() WHERE id=$1",product_id)
        status='completed' if result.get('success') and not result.get('image_warnings') else ('images_pending' if result.get('image_warnings') or kind=='repair-images' else 'needs_review')
    except Exception as exc:
        status,result='failed',{'success':False,'error':str(exc)[:1500]}
    async with deps.pool.acquire() as conn:
        await conn.execute('UPDATE lightspeed_review_jobs SET status=$2,result=$3::jsonb,updated_at=NOW() WHERE id=$1',job_id,status,json.dumps(result))



