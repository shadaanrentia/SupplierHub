"""Read-only directional history over durable supplier jobs and destination batches."""
import json
from fastapi import APIRouter, Depends, HTTPException, Query
import deps
from deps import get_current_user

router = APIRouter(prefix='/sync-history', tags=['Sync history'])
ACTIVE = ('pending', 'queued', 'planning', 'running', 'stopping', 'in_progress')


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


def status(value):
    return {'pending':'queued','done':'completed','synced':'completed','success':'completed',
            'images_pending':'completed_with_issues','needs_review':'completed_with_issues',
            'completed_with_errors':'completed_with_issues','error':'failed'}.get(value, value)


def public(row):
    item = decode(row['data'])
    item['key'] = row['key']
    item['raw_status'] = item.get('status')
    item['status'] = status(item.get('status'))
    return item


async def sources(conn):
    """Optional history tables never make a fresh installation fail to load."""
    names = ('sync_logs','supplier_sync_details','lightspeed_sync_batches',
             'lightspeed_sync_items','lightspeed_review_jobs','outbound_sync_events')
    present = {name:bool(await conn.fetchval('SELECT to_regclass($1)', 'public.'+name)) for name in names}
    parts = []
    if present['sync_logs']:
        join = 'LEFT JOIN supplier_sync_details d ON d.log_id=l.id' if present['supplier_sync_details'] else ''
        details = 'to_jsonb(d)' if join else "'{}'::jsonb"
        outbound = "(l.sync_type IN ('odoo','lightspeed','export_odoo','export_lightspeed') OR l.sync_type LIKE '%_push')"
        parts.append(f"""SELECT 'supplier:'||l.id AS key, to_jsonb(l)||jsonb_build_object(
            'direction',CASE WHEN {outbound} THEN 'outbound' ELSE 'inbound' END,
            'platform',CASE WHEN {outbound} THEN CASE WHEN l.sync_type ILIKE '%odoo%' THEN 'odoo' ELSE 'lightspeed' END ELSE 'supplier' END,
            'operation',l.sync_type,'supplier_ids',jsonb_build_array(l.supplier_id),
            'supplier_names',jsonb_build_array(l.supplier_name),
            'started_at',l.start_time AT TIME ZONE 'UTC','finished_at',l.end_time AT TIME ZONE 'UTC',
            'total',l.total_items,'succeeded',({details})->'succeeded','failed',({details})->'failed',
            'skipped',({details})->'skipped','managed',{'d.log_id IS NOT NULL' if join else 'FALSE'},
            'stage',({details})->'stage','message',l.message) AS data
            FROM sync_logs l {join}""")
    if present['lightspeed_sync_batches'] and present['lightspeed_sync_items']:
        parts.append("""SELECT 'batch:'||b.id, to_jsonb(b)||jsonb_build_object(
            'direction','outbound','platform','lightspeed','operation','catalogue batch',
            'supplier_ids',COALESCE(a.supplier_ids,CASE WHEN b.selection->>'supplier_id' IS NOT NULL THEN jsonb_build_array(b.selection->>'supplier_id') ELSE '[]'::jsonb END),
            'supplier_names',COALESCE(a.supplier_names,(SELECT jsonb_build_array(s.supplier_name) FROM suppliers s WHERE s.id=b.selection->>'supplier_id'),'[]'::jsonb),
            'started_at',b.created_at,'finished_at',CASE WHEN b.status NOT IN ('queued','running','stopping') THEN b.updated_at END,
            'succeeded',a.succeeded,'failed',a.failed,'images_completed',a.images_completed,'images_pending',a.images_pending,
            'managed',FALSE) FROM lightspeed_sync_batches b
            LEFT JOIN LATERAL (SELECT
                jsonb_agg(DISTINCT p.supplier_id) FILTER(WHERE p.supplier_id IS NOT NULL) supplier_ids,
                jsonb_agg(DISTINCT s.supplier_name) FILTER(WHERE s.supplier_name IS NOT NULL) supplier_names,
                COUNT(*) FILTER(WHERE i.details_status='completed') succeeded,
                COUNT(*) FILTER(WHERE i.details_status IN ('failed','interrupted')) failed,
                COUNT(*) FILTER(WHERE i.images_status='completed') images_completed,
                COUNT(*) FILTER(WHERE i.images_status IN ('pending','interrupted')) images_pending
                FROM lightspeed_sync_items i LEFT JOIN products p ON p.id=i.product_id
                LEFT JOIN suppliers s ON s.id=p.supplier_id WHERE i.batch_id=b.id) a ON TRUE
            WHERE LOWER(BTRIM(b.store_domain))=(SELECT LOWER(BTRIM(lightspeed_store_id)) FROM settings WHERE id='system_settings')""")
    if present['lightspeed_review_jobs']:
        parts.append("""SELECT 'review:'||j.id, to_jsonb(j)||jsonb_build_object(
            'direction','outbound','platform','lightspeed','operation',j.kind,
            'supplier_ids',jsonb_build_array(p.supplier_id),'supplier_names',jsonb_build_array(s.supplier_name),
            'sku',p.supplier_sku,'product_name',p.product_name,
            'recorded_at',j.updated_at,'managed',FALSE)
            FROM lightspeed_review_jobs j LEFT JOIN products p ON p.id=j.product_id
            LEFT JOIN suppliers s ON s.id=p.supplier_id
            WHERE LOWER(BTRIM(j.store_domain))=(SELECT LOWER(BTRIM(lightspeed_store_id)) FROM settings WHERE id='system_settings')""")
    if present['outbound_sync_events']:
        parts.append("SELECT 'outbound:'||e.id, to_jsonb(e)||jsonb_build_object('direction','outbound','managed',FALSE) FROM outbound_sync_events e")
    return ' UNION ALL '.join(parts) if parts else "SELECT ''::text key,'{}'::jsonb data WHERE FALSE"


def filtered(sql):
    return 'WITH history AS ('+sql+'''), filtered AS (SELECT * FROM history WHERE
        data->>'direction'=$1
        AND ($2::text='' OR COALESCE(data->'supplier_ids','[]'::jsonb) ? $2)
        AND ($3::text='' OR data->>'platform'=$3)
        AND ($4::text='' OR data->>'status'=$4 OR
            ($4='queued' AND data->>'status'='pending') OR
            ($4='completed' AND data->>'status' IN ('done','synced','success')) OR
            ($4='completed_with_issues' AND data->>'status' IN ('images_pending','needs_review','completed_with_errors')) OR
            ($4='failed' AND data->>'status'='error'))
        AND ($5::text='' OR data->>'operation'=$5)
        AND ($6::date IS NULL OR COALESCE(data->>'started_at',data->>'recorded_at')::timestamptz>=($6::date::timestamp AT TIME ZONE 'UTC'))
        AND ($7::date IS NULL OR COALESCE(data->>'started_at',data->>'recorded_at')::timestamptz<(($7::date+1)::timestamp AT TIME ZONE 'UTC'))
        AND ($8::text='%%' OR concat_ws(' ',data->>'supplier_names',data->>'sku',data->>'product_name',data->>'operation',data->>'message',key) ILIKE $8)) '''


@router.get('')
async def history(direction:str=Query('inbound',pattern='^(inbound|outbound)$'),supplier_id:str='',platform:str='',
                  state:str='',operation:str='',date_from:str='',date_to:str='',search:str='',
                  page:int=Query(1,ge=1),user=Depends(get_current_user)):
    from datetime import date
    try:
        first=date.fromisoformat(date_from) if date_from else None
        last=date.fromisoformat(date_to) if date_to else None
    except ValueError:
        raise HTTPException(400,'Use YYYY-MM-DD for date filters')
    if first and last and first>last:raise HTTPException(400,'The start date must precede the end date')
    args=(direction,supplier_id,platform,state,operation,first,last,'%'+search.strip()+'%')
    async with deps.pool.acquire() as conn:
        sql=await sources(conn)
        cte=filtered(sql)
        summary=dict(await conn.fetchrow(cte+"""SELECT COUNT(*) total,
            COUNT(*) FILTER(WHERE data->>'status' IN ('pending','queued','running','planning','stopping','in_progress')) active,
            COUNT(*) FILTER(WHERE data->>'status' IN ('completed','done','synced','success')) completed,
            COUNT(*) FILTER(WHERE data->>'status' IN ('failed','error','interrupted','images_pending','needs_review','completed_with_issues','completed_with_errors')) attention FROM filtered""",*args))
        rows=await conn.fetch(cte+"SELECT * FROM filtered ORDER BY COALESCE(data->>'started_at',data->>'recorded_at')::timestamptz DESC NULLS LAST,key DESC LIMIT 50 OFFSET $9",*args,(page-1)*50)
        operations=await conn.fetch('WITH history AS ('+sql+") SELECT DISTINCT data->>'operation' operation FROM history WHERE data->>'direction'=$1 ORDER BY operation",direction)
    return {'items':[public(row) for row in rows],'total':summary['total'],'summary':summary,
            'operations':[r['operation'] for r in operations if r['operation']],'page':page,'page_size':50}


@router.get('/events/{event_key}')
async def detail(event_key:str,page:int=Query(1,ge=1),search:str='',state:str='',user=Depends(get_current_user)):
    if ':' not in event_key:raise HTTPException(404,'History record not found')
    source,identity=event_key.split(':',1)
    async with deps.pool.acquire() as conn:
        sql=await sources(conn)
        row=await conn.fetchrow('WITH history AS ('+sql+') SELECT * FROM history WHERE key=$1',event_key)
        if not row:raise HTTPException(404,'History record not found for the configured store')
        event=public(row)
        items=[];total=0
        if source=='supplier' and await conn.fetchval("SELECT to_regclass('public.supplier_sync_items')"):
            where="log_id=$1 AND ($2::text='' OR status=$2) AND (sku ILIKE $3 OR message ILIKE $3)"
            args=(identity,state,'%'+search.strip()+'%')
            total=await conn.fetchval('SELECT COUNT(*) FROM supplier_sync_items WHERE '+where,*args)
            rows=await conn.fetch('SELECT * FROM supplier_sync_items WHERE '+where+' ORDER BY updated_at DESC,stage,sku LIMIT 50 OFFSET $4',*args,(page-1)*50)
            items=[dict(r) for r in rows]
        elif source=='batch':
            where="batch_id=$1 AND ($2::text='' OR details_status=$2 OR images_status=$2) AND (sku ILIKE $3 OR product_name ILIKE $3)"
            args=(identity,state,'%'+search.strip()+'%')
            total=await conn.fetchval('SELECT COUNT(*) FROM lightspeed_sync_items WHERE '+where,*args)
            rows=await conn.fetch('SELECT * FROM lightspeed_sync_items WHERE '+where+' ORDER BY position LIMIT 50 OFFSET $4',*args,(page-1)*50)
            items=[{k:decode(v) if k in ('details_result','images_result') else v for k,v in dict(r).items()} for r in rows]
    return {'event':event,'items':items,'total':total,'page':page,'page_size':50}
