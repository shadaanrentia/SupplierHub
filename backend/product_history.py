"""Paginated history for one product. Saved evidence only; no external API calls."""
import json
from fastapi import APIRouter, Depends, HTTPException, Query
import deps
from deps import get_current_user

router=APIRouter(prefix='/products',tags=['Product history'])


async def history_sources(conn, product, skus, store):
    parts=[]
    if await conn.fetchval("SELECT to_regclass('public.supplier_sync_items')"):
        parts.append("""SELECT 'supplier:'||i.log_id||':'||i.stage||':'||i.sku key,
            i.updated_at AT TIME ZONE 'UTC' recorded_at,
            jsonb_build_object('operation',i.stage,'status',i.status,'sku',i.sku,
                'result',jsonb_build_object('message',i.message,'error_code',i.error_code)) data
            FROM supplier_sync_items i JOIN sync_logs l ON l.id=i.log_id
            WHERE $4::text='inbound' AND l.supplier_id=$1
            AND LOWER(BTRIM(i.sku))=ANY($2::text[])""")
    if await conn.fetchval("SELECT to_regclass('public.lightspeed_sync_items')"):
        parts.append("""SELECT 'batch:'||i.batch_id key,i.updated_at recorded_at,
            jsonb_build_object('operation','Product sync','sku',i.sku,'status',
                CASE WHEN i.details_status IN ('failed','interrupted') THEN i.details_status
                WHEN i.images_status IN ('pending','interrupted') THEN 'images_pending'
                WHEN i.details_status='running' OR i.images_status='running' THEN 'running'
                WHEN i.details_status='completed' AND i.images_status='completed' THEN 'completed'
                ELSE b.status END,
                'result',jsonb_build_object('details',i.details_result,'images',i.images_result)) data
            FROM lightspeed_sync_items i JOIN lightspeed_sync_batches b ON b.id=i.batch_id
            WHERE $4::text='outbound' AND i.product_id=$3 AND LOWER(BTRIM(b.store_domain))=$5""")
    if await conn.fetchval("SELECT to_regclass('public.lightspeed_review_jobs')"):
        parts.append("""SELECT 'review:'||j.id key,j.updated_at AT TIME ZONE 'UTC' recorded_at,
            jsonb_build_object('operation',j.kind,'status',j.status,'sku',$6::text,'result',j.result) data
            FROM lightspeed_review_jobs j WHERE $4::text='outbound'
            AND j.product_id=$3 AND LOWER(BTRIM(j.store_domain))=$5""")
    # The false branch retains all bind positions, even on a fresh installation.
    return ' UNION ALL '.join(parts) if parts else """SELECT ''::text key,NULL::timestamptz recorded_at,'{}'::jsonb data
        WHERE FALSE AND $1::text IS NULL AND $2::text[] IS NULL AND $3::text IS NULL
        AND $4::text IS NULL AND $5::text IS NULL AND $6::text IS NULL"""


def mississauga_inventory(rows, saved_warehouse):
    """Use exact source stock; never relabel an unknown/other warehouse total."""
    from inventory_selection import select_inventory
    prepared=[]
    for original in rows:
        row=dict(original)
        warehouses=row.get('warehouse_inventory')
        if isinstance(warehouses,str):
            try:warehouses=json.loads(warehouses)
            except (ValueError,TypeError):warehouses=None
        if not warehouses and str(saved_warehouse or '').strip().casefold()!='mississauga/on':
            row['inventory']=None
        prepared.append(row)
    return select_inventory(prepared,'MISSISSAUGA/ON',strict=False)


@router.get('/{product_id}/history')
async def product_history(product_id:str,direction:str=Query('inbound',pattern='^(inbound|outbound)$'),
                          search:str='',page:int=Query(1,ge=1),user=Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        product=await conn.fetchrow('SELECT id,supplier_id,supplier_sku FROM products WHERE id=$1',product_id)
        if not product:raise HTTPException(404,'Product not found')
        variants=await conn.fetch('SELECT variant_sku FROM product_variants WHERE product_id=$1',product_id)
        skus=list({str(code).strip().casefold() for code in [product['supplier_sku'],*[v['variant_sku'] for v in variants]] if code})
        store=str(await conn.fetchval("SELECT lightspeed_store_id FROM settings WHERE id='system_settings'") or '').strip().lower()
        sql=await history_sources(conn,product,skus,store)
        # Declare every argument type independently of which optional tables exist.
        cte="""WITH scope AS (SELECT $1::text supplier,$2::text[] skus,$3::text product,
            $4::text direction,$5::text store,$6::text sku), events AS ("""+sql+"""),
            filtered AS (SELECT * FROM events WHERE concat_ws(' ',data->>'operation',data->>'sku',data->>'status',data->'result'->>'message') ILIKE $7) """
        args=(product['supplier_id'],skus,product_id,direction,store,product['supplier_sku'],'%'+search.strip()+'%')
        total=await conn.fetchval(cte+'SELECT COUNT(*) FROM filtered',*args)
        rows=await conn.fetch(cte+'SELECT * FROM filtered ORDER BY recorded_at DESC NULLS LAST,key LIMIT 25 OFFSET $8',*args,(page-1)*25)
    items=[]
    for row in rows:
        data=json.loads(row['data']) if isinstance(row['data'],str) else dict(row['data'])
        items.append({**data,'key':row['key'],'recorded_at':row['recorded_at']})
    return {'product_id':product_id,'direction':direction,'items':items,'total':total,'page':page,'page_size':25}
