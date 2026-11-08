"""Record aggregate Odoo exports without storing credentials or changing responses."""
import functools
import inspect
import json
import logging
import deps
from deps import new_id

log=logging.getLogger(__name__)

async def init_schema(conn):
    await conn.execute('''CREATE TABLE IF NOT EXISTS outbound_sync_events(
        id VARCHAR(64) PRIMARY KEY, platform TEXT NOT NULL, operation TEXT NOT NULL,
        status TEXT NOT NULL, supplier_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        supplier_names JSONB NOT NULL DEFAULT '[]'::jsonb, started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        finished_at TIMESTAMPTZ, total INTEGER, succeeded INTEGER, failed INTEGER,
        message TEXT NOT NULL DEFAULT '', result JSONB NOT NULL DEFAULT '{}'::jsonb)''')


def outcome(result):
    if not isinstance(result,dict):return 'completed',None,None,None
    total=result.get('total',result.get('products_to_push'))
    succeeded=result.get('synced')
    failed=result.get('failed')
    if failed is None and isinstance(total,int) and isinstance(succeeded,int):failed=max(0,total-succeeded)
    state='failed' if result.get('success') is False or result.get('status')=='failed' else ('completed_with_issues' if failed else 'completed')
    return state,total,succeeded,failed


def record(operation):
    def decorate(function):
        signature=inspect.signature(function)
        @functools.wraps(function)
        async def wrapped(*args,**kwargs):
            bound=signature.bind_partial(*args,**kwargs).arguments
            body=bound.get('data') or {}
            ids=body.get('product_ids') or []
            identity=new_id()
            async with deps.pool.acquire() as conn:
                if ids:
                    suppliers=await conn.fetch('SELECT DISTINCT s.id,s.supplier_name FROM products p JOIN suppliers s ON s.id=p.supplier_id WHERE p.id=ANY($1::varchar[])',ids)
                else:
                    suppliers=await conn.fetch("SELECT DISTINCT s.id,s.supplier_name FROM products p JOIN suppliers s ON s.id=p.supplier_id WHERE p.selected_for_odoo=TRUE AND (p.odoo_sync_status='pending' OR $1::boolean)",bool(body.get('sync_all')))
                await conn.execute("INSERT INTO outbound_sync_events(id,platform,operation,status,supplier_ids,supplier_names) VALUES($1,'odoo',$2,'running',$3::jsonb,$4::jsonb)",identity,operation,json.dumps([r['id'] for r in suppliers]),json.dumps([r['supplier_name'] for r in suppliers]))
            try:
                result=await function(*args,**kwargs)
            except BaseException as exc:
                try:
                    async with deps.pool.acquire() as conn:await conn.execute("UPDATE outbound_sync_events SET status='failed',finished_at=NOW(),message=$2 WHERE id=$1",identity,str(getattr(exc,'detail',None) or exc)[:2000])
                except Exception:log.exception('Could not finalize Odoo history %s',identity)
                raise
            state,total,succeeded,failed=outcome(result)
            try:
                async with deps.pool.acquire() as conn:
                    await conn.execute('UPDATE outbound_sync_events SET status=$2,finished_at=NOW(),total=$3,succeeded=$4,failed=$5,result=$6::jsonb WHERE id=$1',identity,state,total,succeeded,failed,json.dumps(result,default=str))
            except Exception:log.exception('Export returned but history finalization failed: %s',identity)
            return result
        return wrapped
    return decorate
