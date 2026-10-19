"""Supplier-scoped taxonomy import, overrides and durable preview/execute jobs."""
import asyncio
import csv
import hashlib
import json
from pathlib import Path
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel, Field
import deps
from deps import get_current_user, get_admin_user, new_id
from sanmar_taxonomy import parse_csv, sku_key, key, category_path, is_brand_category_path
from taxonomy_extensions import (
    combined_nodes,
    read_config,
    checked_parent,
    destination_tree,
)

router = APIRouter(prefix='/api/taxonomy', tags=['SanMar category mapping'])


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


async def check_supplier(conn, supplier_id):
    name = await conn.fetchval('SELECT supplier_name FROM suppliers WHERE id=$1', supplier_id)
    if not name:
        raise HTTPException(404, 'Supplier not found')
    if 'sanmar' not in key(name):
        raise HTTPException(400, 'This importer is for a SanMar Canada supplier')
    return name


async def load_catalog(conn, supplier_id):
    await check_supplier(conn, supplier_id)
    imported = await conn.fetchrow('SELECT * FROM supplier_taxonomy_imports WHERE supplier_id=$1', supplier_id)
    if not imported:
        return {'digest': None, 'nodes': [], 'rows': [], 'labels': [], 'warnings': [], 'summary': {}}
    nodes = await combined_nodes(conn, supplier_id)
    rows = [decode(r['data']) for r in await conn.fetch('SELECT data FROM supplier_taxonomy_styles WHERE supplier_id=$1 ORDER BY sku_key', supplier_id)]
    csv_keys = {r['sku_key'] for r in rows}
    extra_skus = await conn.fetch('SELECT DISTINCT supplier_sku FROM products WHERE supplier_id=$1', supplier_id)
    for p in extra_skus:
        normalized = sku_key(p['supplier_sku'])
        if normalized not in csv_keys:
            rows.append({'sku': p['supplier_sku'], 'sku_key': normalized, 'labels': [],
                         'source_paths': [], 'paths': [], 'primary_path': None, 'status': 'review',
                         'source': 'not_in_csv', 'reason': 'Style missing from CSV; assign a primary manually'})
            csv_keys.add(normalized)
    overrides = {r['sku_key']: r['path'] for r in await conn.fetch('SELECT sku_key,path FROM supplier_taxonomy_overrides WHERE supplier_id=$1', supplier_id)}
    node_map = {n['path']: n for n in nodes}
    for row in rows:
        if row['sku_key'] in overrides:
            row['primary_path'] = overrides[row['sku_key']]
            row['reason'] = 'Manual override (preserved on reimport)'
            row['manual'] = True
        node = node_map.get(row['primary_path'])
        if not node or not node['leaf'] or not node['verified']:
            row['primary_path'] = None
            row['status'] = 'review'
            if row.get('manual'):
                row['reason'] = 'Manual override needs review: destination was removed or is no longer a verified leaf'
        else:
            row['status'] = 'ready'
    return {'digest': imported['digest'], 'filename': imported['filename'], 'nodes': nodes, 'rows': rows,
            'labels': decode(imported['labels']), 'warnings': decode(imported['warnings']),
            'summary': {**decode(imported['summary']), 'categories': len(nodes), 'ready': sum(r['status']=='ready' and r.get('source')!='not_in_csv' for r in rows),
                        'review': sum(r['status']=='review' and r.get('source')!='not_in_csv' for r in rows),
                        'additional_hub_styles': sum(r.get('source')=='not_in_csv' for r in rows)}}


async def revision(conn, supplier_id, catalog):
    overrides = [dict(r) for r in await conn.fetch('SELECT sku_key,path FROM supplier_taxonomy_overrides WHERE supplier_id=$1 ORDER BY sku_key', supplier_id)]
    destinations = [dict(r) for r in await conn.fetch('SELECT path,store_domain,category_id FROM supplier_taxonomy_destinations WHERE supplier_id=$1 ORDER BY path,store_domain', supplier_id)]
    config = await read_config(conn, supplier_id)

    return hashlib.sha256(
        json.dumps(
            [
                catalog["digest"],
                'product-only-two-level-audience-v3',
                sorted(catalog["nodes"], key=lambda node: node["path"]),
                overrides,
                destinations,
                config,
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()


@router.get('/{supplier_id}')
async def catalog(supplier_id: str, user=Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        data = await load_catalog(conn, supplier_id)
        products = [dict(r) for r in await conn.fetch('SELECT id,supplier_sku,product_name,category,lightspeed_product_id FROM products WHERE supplier_id=$1 ORDER BY supplier_sku', supplier_id)]
        matched = {sku_key(p['supplier_sku']) for p in products}
        csv_skus = {r['sku_key'] for r in data['rows'] if r.get('source') != 'not_in_csv'}
        data['summary'].update({'local_products': len(products), 'matched_products': sum(sku_key(p['supplier_sku']) in csv_skus for p in products),
                                'unmatched_products': sum(sku_key(p['supplier_sku']) not in csv_skus for p in products),
                                'styles_not_in_hub': len(csv_skus - matched)})
        by_sku = {r['sku_key']: r for r in data['rows']}
        data['products'] = [{**p, 'assignment': by_sku.get(sku_key(p['supplier_sku']))} for p in products]
        data['destinations'] = [dict(r) for r in await conn.fetch('SELECT path,store_domain,category_id FROM supplier_taxonomy_destinations WHERE supplier_id=$1', supplier_id)]
        data['revision'] = await revision(conn, supplier_id, data)
        return data


async def import_bytes(supplier_id, raw, filename, dry_run, expected_digest, user):
    try:
        parsed = await asyncio.to_thread(parse_csv, raw)
    except (ValueError, UnicodeError, csv.Error) as e:
        raise HTTPException(400, str(e))
    async with deps.pool.acquire() as conn:
        await check_supplier(conn, supplier_id)
        if dry_run:
            return {**parsed, 'dry_run': True}
        if not expected_digest or expected_digest != parsed['digest']:
            raise HTTPException(409, 'Preview this exact CSV before importing')
        async with conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock(hashtext($1))', 'taxonomy:' + supplier_id)
            running = await conn.fetchval("SELECT COUNT(*) FROM supplier_taxonomy_jobs WHERE supplier_id=$1 AND status='running'", supplier_id)
            if running:
                raise HTTPException(409, 'Wait for the category job to finish before importing')
            custom_rows = await conn.fetch(
                """
                SELECT data
                FROM supplier_taxonomy_custom_nodes
                WHERE supplier_id=$1
                """,
                supplier_id,
            )
            custom_nodes = [decode(row["data"]) for row in custom_rows]

            invalid_custom = [node['path'] for node in custom_nodes
                              if len(node['path'].split(' > ')) > 2 or is_brand_category_path(node['path'])]
            if invalid_custom:
                raise HTTPException(409, 'Existing custom categories need correction before import: ' + ', '.join(invalid_custom[:5]))

            imported_paths = {node["path"] for node in parsed["nodes"]}
            custom_paths = {node["path"] for node in custom_nodes}

            normalized_imported = {
                tuple(key(part) for part in path.split(" > "))
                for path in imported_paths
            }

            if any(
                tuple(key(part) for part in path.split(" > "))
                in normalized_imported
                for path in custom_paths
            ):
                raise HTTPException(
                    409,
                    "The new CSV conflicts with a custom category path",
                )

            all_paths = imported_paths | custom_paths
            if any(
                node["parent_path"]
                and node["parent_path"] not in all_paths
                for node in custom_nodes
            ):
                raise HTTPException(
                    409,
                    "The new CSV removes a parent used by a custom category",
                )
            await conn.execute('DELETE FROM supplier_taxonomy_nodes WHERE supplier_id=$1', supplier_id)
            await conn.execute('DELETE FROM supplier_taxonomy_styles WHERE supplier_id=$1', supplier_id)
            await conn.executemany('INSERT INTO supplier_taxonomy_nodes(supplier_id,path,data) VALUES($1,$2,$3::jsonb)',
                                  [(supplier_id, n['path'], json.dumps(n)) for n in parsed['nodes']])
            await conn.executemany('INSERT INTO supplier_taxonomy_styles(supplier_id,sku_key,data) VALUES($1,$2,$3::jsonb)',
                                  [(supplier_id, r['sku_key'], json.dumps(r)) for r in parsed['rows']])
            # Remap manual non-brand third-level assignments to their two-level
            # product category; removed brand assignments require selection.
            valid_leaves = {n['path'] for n in parsed['nodes'] if n['leaf'] and n['verified']}
            valid_leaves |= {n['path'] for n in custom_nodes if n['leaf'] and n['verified']}
            overrides = await conn.fetch('SELECT sku_key,path FROM supplier_taxonomy_overrides WHERE supplier_id=$1', supplier_id)
            for override in overrides:
                old = override['path']
                revised = category_path(old)
                if revised not in valid_leaves:
                    revised = None
                if old != revised:
                    await conn.execute('UPDATE supplier_taxonomy_overrides SET path=$3,updated_at=NOW() WHERE supplier_id=$1 AND sku_key=$2', supplier_id, override['sku_key'], revised)
            previous_summary = await conn.fetchval('SELECT summary FROM supplier_taxonomy_imports WHERE supplier_id=$1', supplier_id)
            previous_summary = decode(previous_summary) or {}
            if previous_summary.get('category_policy') != 'product-only-two-level-audience-v3':
                # Invalidate local cached IDs; no remote categories/products are deleted.
                await conn.execute('DELETE FROM supplier_taxonomy_destinations WHERE supplier_id=$1', supplier_id)
            await conn.execute('''INSERT INTO supplier_taxonomy_imports(supplier_id,digest,filename,summary,labels,warnings,imported_by)
                VALUES($1,$2,$3,$4::jsonb,$5::jsonb,$6::jsonb,$7)
                ON CONFLICT(supplier_id) DO UPDATE SET digest=EXCLUDED.digest,filename=EXCLUDED.filename,
                summary=EXCLUDED.summary,labels=EXCLUDED.labels,warnings=EXCLUDED.warnings,
                imported_by=EXCLUDED.imported_by,updated_at=NOW()''', supplier_id, parsed['digest'], filename,
                json.dumps(parsed['summary']), json.dumps(parsed['labels']), json.dumps(parsed['warnings']), str(user['id']))
    return {'success': True, 'summary': parsed['summary']}



@router.post('/{supplier_id}/import')
async def import_csv(supplier_id: str, file: UploadFile = File(...), dry_run: bool = Form(True),
                     expected_digest: Optional[str] = Form(None), user=Depends(get_admin_user)):
    raw = await file.read(10 * 1024 * 1024 + 1)
    return await import_bytes(supplier_id, raw, Path(file.filename or 'Categories.csv').name, dry_run, expected_digest, user)


class BundledImport(BaseModel):
    dry_run: bool = True
    expected_digest: Optional[str] = None


@router.post('/{supplier_id}/import-bundled')
async def import_bundled(supplier_id: str, body: BundledImport, user=Depends(get_admin_user)):
    csv_path = Path(__file__).resolve().parents[1] / "data" / "SanMar_Categories.csv"

    if not csv_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=(
                "Bundled SanMar CSV is missing. Place SanMar_Categories.csv "
                "in backend/data, or upload Categories.csv through the category mapping page."
            ),
        )

    raw = csv_path.read_bytes()
    return await import_bytes(supplier_id, raw, 'SanMar_Categories.csv', body.dry_run, body.expected_digest, user)


class Override(BaseModel):
    sku: str = Field(min_length=1, max_length=200)
    path: Optional[str] = None
    reset: bool = False


class BulkOverride(BaseModel):
    skus: list[str] = Field(min_length=1, max_length=1000)
    path: Optional[str] = None
    reset: bool = False


async def save_overrides(supplier_id, skus, path, reset, user):
    keys = list(dict.fromkeys(sku_key(sku) for sku in skus))
    if any(not sku or len(sku)>200 for sku in keys):
        raise HTTPException(400, 'Invalid style SKU')
    async with deps.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock(hashtext($1))', 'taxonomy:' + supplier_id)
            data = await load_catalog(conn, supplier_id)
            if await conn.fetchval("SELECT COUNT(*) FROM supplier_taxonomy_jobs WHERE supplier_id=$1 AND status='running'", supplier_id):
                raise HTTPException(409, 'A category job is running')
            known = {r['sku_key'] for r in data['rows']}
            if any(sku not in known for sku in keys):
                raise HTTPException(404, 'One or more styles are absent from both the CSV and this supplier catalogue')
            if path and not any(n['path']==path and n['leaf'] and n['verified'] for n in data['nodes']):
                raise HTTPException(400, 'Select a verified leaf category')
            if reset:
                await conn.execute('DELETE FROM supplier_taxonomy_overrides WHERE supplier_id=$1 AND sku_key=ANY($2::varchar[])', supplier_id, keys)
            else:
                await conn.executemany("""INSERT INTO supplier_taxonomy_overrides(supplier_id,sku_key,path,updated_by) VALUES($1,$2,$3,$4)
                    ON CONFLICT(supplier_id,sku_key) DO UPDATE SET path=EXCLUDED.path,updated_by=EXCLUDED.updated_by,updated_at=NOW()""",
                    [(supplier_id, sku, path, str(user['id'])) for sku in keys])
    return {'success': True, 'updated': len(keys)}


@router.put('/{supplier_id}/override')
async def override(supplier_id: str, body: Override, user=Depends(get_admin_user)):
    return await save_overrides(supplier_id, [body.sku], body.path, body.reset, user)


@router.put('/{supplier_id}/bulk-overrides')
async def bulk_override(supplier_id: str, body: BulkOverride, user=Depends(get_admin_user)):
    return await save_overrides(supplier_id, body.skus, body.path, body.reset, user)


def remote_index(categories):
    by_id = {c['lightspeed_category_id']: c for c in categories}
    index = {}
    def path_for(cid, seen=None):
        seen = set(seen or ())
        if cid in seen or cid not in by_id:
            raise ValueError('Lightspeed category tree has a cycle or missing parent')
        seen.add(cid); c = by_id[cid]
        parent = c.get('parent_id')
        return (path_for(parent, seen) + ' > ' if parent else '') + c['category_name']
    for cid, category in by_id.items():
        path = path_for(cid)
        normalized = tuple(key(p) for p in path.split(' > '))
        if normalized in index:
            raise ValueError('Duplicate Lightspeed category path: ' + path)
        index[normalized] = {**category, 'full_path': path}
    return index


async def service():
    from routes.lightspeed import _get_ls_service
    ls = await _get_ls_service()
    if ls.mock_mode:
        raise HTTPException(400, 'Configure a real Lightspeed connection in Settings')
    return ls


async def get_remote(ls):
    result = await asyncio.to_thread(ls.get_categories)
    if not result.get('success'):
        raise HTTPException(502, result.get('error', 'Unable to fetch Lightspeed categories'))
    try:
        return remote_index(result['categories'])
    except ValueError as e:
        raise HTTPException(409, str(e))


class PlanRequest(BaseModel):
    kind: Literal['categories', 'products']


@router.post("/{supplier_id}/preview")
async def preview(
    supplier_id: str,
    body: PlanRequest,
    user=Depends(get_admin_user),
):
    ls = await service()
    remote = await get_remote(ls)

    async with deps.pool.acquire() as conn:
        data = await load_catalog(conn, supplier_id)

        if not data["digest"]:
            raise HTTPException(400, "Import the SanMar CSV first")
        if data['summary'].get('category_policy') != 'product-only-two-level-audience-v3':
            raise HTTPException(409, 'Refresh the SanMar catalogue before publishing categories')

        parent = await checked_parent(conn, supplier_id, ls, remote)
        parent_path = parent["full_path"]
        parent_id = parent["lightspeed_category_id"]

        destination_nodes, assignment_paths = destination_tree(
            data["nodes"],
            parent_path,
        )

        anchor = {
            "anchor_path": parent_path,
            "anchor_id": parent_id,
        }

        items = []

        if body.kind == "categories":
            for node in destination_nodes:
                target = remote.get(
                    tuple(key(part) for part in node["path"].split(" > "))
                )

                message = ""
                if not node["verified"]:
                    message = "Unverified translation"
                elif (
                    node["source_paths"]
                    and target
                    and not target["leaf_category"]
                ):
                    message = "Destination already has children"

                items.append({
                    **anchor,
                    "path": node["path"],
                    "parent_path": node["parent_path"],
                    "name": node["name"],
                    "source_paths": node["source_paths"],
                    "category_id": (
                        target["lightspeed_category_id"] if target else None
                    ),
                    "status": (
                        "blocked"
                        if message
                        else "reuse" if target else "create"
                    ),
                    "message": message,
                })

        else:
            by_sku = {row["sku_key"]: row for row in data["rows"]}

            products = await conn.fetch(
                """
                SELECT id,supplier_sku,product_name,category,
                       lightspeed_product_id
                FROM products
                WHERE supplier_id=$1
                ORDER BY supplier_sku
                """,
                supplier_id,
            )

            for product in products:
                row = by_sku.get(sku_key(product["supplier_sku"]))
                source_path = row.get("primary_path") if row else None
                path = assignment_paths.get(source_path)

                target = (
                    remote.get(
                        tuple(key(part) for part in path.split(" > "))
                    )
                    if path else None
                )

                if not row:
                    message = "Style missing from catalogue"
                elif not source_path:
                    message = row["reason"]
                elif not target:
                    message = "Publish category first"
                elif not target["leaf_category"]:
                    message = "Destination is not a leaf"
                elif not product["lightspeed_product_id"]:
                    message = "Product has not been pushed to Lightspeed"
                else:
                    message = ""

                items.append({
                    **anchor,
                    "product_id": product["id"],
                    "sku": product["supplier_sku"],
                    "name": product["product_name"],
                    "previous_category": product["category"],
                    "source_path": source_path,
                    "path": path,
                    "lightspeed_product_id": product["lightspeed_product_id"],
                    "category_id": (
                        target["lightspeed_category_id"] if target else None
                    ),
                    "status": "blocked" if message else "update",
                    "message": message,
                })

        digest = await revision(conn, supplier_id, data)
        job_id = new_id()

        await conn.execute(
            """
            INSERT INTO supplier_taxonomy_jobs
                (id,supplier_id,kind,status,digest,store_domain,items,created_by)
            VALUES ($1,$2,$3,'preview',$4,$5,$6::jsonb,$7)
            """,
            job_id,
            supplier_id,
            body.kind,
            digest,
            ls.domain_prefix,
            json.dumps(items),
            str(user["id"]),
        )

    return {
        "id": job_id,
        "kind": body.kind,
        "status": "preview",
        "items": items,
        "counts": {
            status: sum(item["status"] == status for item in items)
            for status in ("create", "reuse", "update", "blocked")
        },
    }

@router.get('/{supplier_id}/jobs')
async def jobs(supplier_id: str, user=Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        await check_supplier(conn, supplier_id)
        rows = await conn.fetch('SELECT id,kind,status,updated_at FROM supplier_taxonomy_jobs WHERE supplier_id=$1 ORDER BY updated_at DESC LIMIT 20', supplier_id)
        return {'jobs': [dict(r) for r in rows]}


@router.get('/{supplier_id}/jobs/{job_id}')
async def get_job(supplier_id: str, job_id: str, user=Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow('SELECT * FROM supplier_taxonomy_jobs WHERE id=$1 AND supplier_id=$2', job_id, supplier_id)
        if not row:
            raise HTTPException(404, 'Category job not found')
        return {**dict(row), 'items': decode(row['items'])}


@router.post('/{supplier_id}/jobs/{job_id}/execute')
async def execute(supplier_id: str, job_id: str, background_tasks: BackgroundTasks, user=Depends(get_admin_user)):
    ls = await service()
    async with deps.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock(hashtext($1))', 'taxonomy:' + supplier_id)
            await conn.execute('SELECT pg_advisory_xact_lock(hashtext($1))', 'taxonomy-store:' + ls.domain_prefix)
            row = await conn.fetchrow('SELECT * FROM supplier_taxonomy_jobs WHERE id=$1 AND supplier_id=$2 FOR UPDATE', job_id, supplier_id)
            if not row or row['status'] != 'preview':
                raise HTTPException(409, 'Create a new preview before executing')
            if await conn.fetchval("SELECT COUNT(*) FROM supplier_taxonomy_jobs WHERE status='running' AND store_domain=$1", ls.domain_prefix):
                raise HTTPException(409, 'Another category job is running for this store')
            data = await load_catalog(conn, supplier_id)
            if row['digest'] != await revision(conn, supplier_id, data) or row['store_domain'] != ls.domain_prefix:
                raise HTTPException(409, 'CSV, overrides, mappings or store changed; generate a new preview')
            items = decode(row['items'])
            # Ensure hub IDs have not been repointed since the user reviewed them.
            if row['kind'] == 'products':
                for item in items:
                    if item['status'] == 'update':
                        pid = await conn.fetchval('SELECT lightspeed_product_id FROM products WHERE id=$1 AND supplier_id=$2', item['product_id'], supplier_id)
                        if pid != item['lightspeed_product_id']:
                            raise HTTPException(409, 'Product destination changed; generate a new preview')
            await conn.execute("UPDATE supplier_taxonomy_jobs SET status='running',updated_at=NOW() WHERE id=$1", job_id)
    background_tasks.add_task(run_job, job_id, supplier_id, row['kind'], ls, items)
    return {'id': job_id, 'status': 'running'}


async def save_job(job_id, items, status='running'):
    async with deps.pool.acquire() as conn:
        await conn.execute('UPDATE supplier_taxonomy_jobs SET items=$1::jsonb,status=$2,updated_at=NOW() WHERE id=$3', json.dumps(items), status, job_id)


async def run_job(job_id, supplier_id, kind, ls, items):
    try:
        remote = await get_remote(ls)

        for item in items:
            if not item.get("anchor_path") or not item.get("anchor_id"):
                raise ValueError(
                    "This preview predates parent-category support. "
                    "Generate a new preview"
                )

            anchor = remote.get(
                tuple(
                    key(part)
                    for part in item["anchor_path"].split(" > ")
                )
            )

            if (
                not anchor
                or anchor["lightspeed_category_id"] != item["anchor_id"]
            ):
                raise ValueError(
                    "The selected parent changed or was deleted. "
                    "Generate a new preview"
                )

        for item in items:
            if item['status'] == 'blocked':
                continue
            try:
                target = remote.get(tuple(key(p) for p in item['path'].split(' > ')))
                if kind == 'categories':
                    if item['status'] == 'reuse' and (not target or target['lightspeed_category_id'] != item['category_id']):
                        raise ValueError('Previously reviewed category changed or was deleted; generate a new preview')
                    if target:
                        if item.get('source_paths') and not target['leaf_category']:
                            raise ValueError('Destination now has children; generate a new preview')
                        cid = target['lightspeed_category_id']
                    else:
                        parent = remote.get(tuple(key(p) for p in item['parent_path'].split(' > '))) if item['parent_path'] else None
                        if item['parent_path'] and not parent:
                            raise ValueError('Parent category failed or is missing')
                        result = await asyncio.to_thread(ls.create_category, item['name'], parent['lightspeed_category_id'] if parent else None)
                        if not result.get('success'):
                            raise ValueError(result.get('error', 'Category creation failed'))
                        cid = result['id']
                        remote[tuple(key(p) for p in item['path'].split(' > '))] = {'lightspeed_category_id': cid, 'leaf_category': True}
                    async with deps.pool.acquire() as conn:
                        for source_path in item.get("source_paths", []):
                            await conn.execute(
                                """
                                INSERT INTO supplier_taxonomy_destinations
                                    (supplier_id,path,store_domain,category_id)
                                VALUES ($1,$2,$3,$4)
                                ON CONFLICT(supplier_id,path,store_domain)
                                DO UPDATE SET
                                    category_id=EXCLUDED.category_id,
                                    updated_at=NOW()
                                """,
                                supplier_id,
                                source_path,
                                ls.domain_prefix,
                                cid,
                            )
                    item['category_id'] = cid
                else:
                    if not target or not target['leaf_category'] or target['lightspeed_category_id'] != item['category_id']:
                        raise ValueError('Remote category changed after preview; generate a new preview')
                    result = await asyncio.to_thread(ls.update_product_category, item['lightspeed_product_id'], item['category_id'])
                    if not result.get('success'):
                        raise ValueError(result.get('error', 'Product category update failed'))
                item['status'] = 'done'; item['message'] = 'Confirmed by Lightspeed'
            except Exception as e:
                item['status'] = 'failed'; item['message'] = str(e)[:1500]
                # A timed-out create may have succeeded remotely. Refresh avoids repeating an unknown write.
                if kind == 'categories':
                    remote = await get_remote(ls)
            await save_job(job_id, items)
        await save_job(job_id, items, 'completed_with_errors' if any(i['status']=='failed' for i in items) else 'completed')
    except Exception as e:
        for item in items:
            if item['status'] not in ('done','blocked','failed'):
                item['status'] = 'failed'; item['message'] = str(e)[:1500]
        await save_job(job_id, items, 'failed')
