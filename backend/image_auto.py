"""Automatic image reconciliation. Unknown POST outcomes are never blindly repeated."""
import asyncio
import base64
import hashlib
import json
import os
import threading
from urllib.parse import unquote
import requests
import deps


_read_local = threading.local()


def _read_session():
    session=getattr(_read_local,'session',None)
    if session is None:
        session=requests.Session()
        _read_local.session=session
    return session


def read_bytes(image):
    if isinstance(image.get('_image_bytes'),bytes): return image['_image_bytes']
    raw=image.get('image_base64')
    if raw:
        data=raw if isinstance(raw,bytes) else base64.b64decode(str(raw).split(',',1)[-1])
    elif image.get('local_path') and os.path.isfile(image['local_path']):
        with open(image['local_path'],'rb') as stream:data=stream.read()
    else:
        response=_read_session().get(str(image.get('url') or ''),timeout=(10,30))
        response.raise_for_status()
        if not response.headers.get('content-type','').lower().startswith('image/'):
            raise ValueError('Image URL did not return image content')
        data=response.content
    if not data:raise ValueError('Source image is empty')
    return data


async def retry_read(fn,*args):
    last=None
    for attempt in range(3):
        try:return await asyncio.to_thread(fn,*args)
        except Exception as exc:
            last=exc
            if attempt<2:await asyncio.sleep(attempt+1)
    raise last


def _all_remote_urls(image):
    urls=[]
    def walk(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if isinstance(item, str) and item.startswith(('https://', 'http://')):urls.append(item)
                elif isinstance(item,(dict,list)):walk(item)
        elif isinstance(value,list):
            for item in value:walk(item)
    walk(image)
    return list(dict.fromkeys(urls))


async def verify_arrival(ls,destination_id,digest,marker):
    for attempt in range(2):
        if attempt: await asyncio.sleep(2)
        try: rows=await retry_read(ls.remote_family_images,destination_id)
        except Exception: continue
        names=unquote(json.dumps(rows, ensure_ascii=False, default=str))
        if marker in names: return True
        for url in list(dict.fromkeys(u for row in rows for u in remote_urls(row))):
            try:
                if hashlib.sha256(await retry_read(read_bytes,{'url':url})).hexdigest()==digest:return True
            except Exception:pass
    return False


def acknowledged_image_ids(message):
    try:
        value = json.loads(message or '{}')
        return {str(i) for i in value.get('image_ids', []) if i} if isinstance(value, dict) else set()
    except (TypeError, ValueError):
        return set()


# DIAGNOSTICS_EMPTY_MEMBER_FIX
def remote_urls(image):
    # Hash one representation, preferably the unresized original bytes.
    sizes = image.get('sizes') if isinstance(image, dict) else None
    if isinstance(sizes, dict):
        for key in ('raw', 'original'):
            url = sizes.get(key)
            if isinstance(url, str) and url.startswith(('https://', 'http://')):
                return [url]
    return _all_remote_urls(image)[:1]


async def confirmed_empty_member(ls, destination_id):
    if not str(destination_id).startswith('variant:'):
        return False
    # Do not reuse a possibly stale snapshot while deciding whether to retry.
    if not getattr(ls, 'target', None):
        return False
    for attempt in range(2):
        ls._snapshot_images = None
        if attempt:
            await asyncio.sleep(1)
        try:
            result = await retry_read(ls.service.family_request, 'GET', 'products/' + str(ls.target))
            row = result.get('data') if isinstance(result, dict) else None
            if not isinstance(row, dict) or str(row.get('id') or '') != str(ls.target) or 'images' not in row:
                return False
            rows = [] if row['images'] is None else row['images']
        except Exception:
            return False
        if not isinstance(rows, list) or rows:
            return False
    return True


async def sync_images(ls,destination_id,images,audit_completed=False):
    from export_safety import image_key
    destination_id=str(destination_id)
    totals={'uploaded':0,'skipped':0,'failed':0,'uncertain':0,'messages':[]}
    images = [i for i in images if i.get('media_type','image') == 'image']
    if not images: return totals
    # Skip completed journals before any remote image GET/hash download.
    async with deps.pool.acquire() as conn:
        finished = await conn.fetch("SELECT image_key,message FROM lightspeed_export_image_results WHERE store_domain=$1 AND destination_id=$2 AND status='uploaded' AND image_key=ANY($3::text[])", ls.domain_prefix, destination_id, [image_key(i) for i in images])
    finished = {r['image_key']:r for r in finished}
    if not audit_completed:
        totals['skipped'] = sum(image_key(i) in finished for i in images)
        images = [i for i in images if image_key(i) not in finished]
    if not images: return totals
    try:remote=await retry_read(ls.remote_family_images,destination_id)
    except Exception as exc:
        totals['failed']=len(images);totals['messages']=[f'Lightspeed image read failed: {exc}'];return totals
    # Download each remote representation only once per repair pass.
    remote_hashes=set();remote_complete=True
    semaphore=asyncio.Semaphore(4)
    async def digest_url(url):
        cache = getattr(ls, '_repair_digest_cache', {})
        if url not in cache:
            async def download():
                async with semaphore:
                    try:return hashlib.sha256(await retry_read(read_bytes,{'url':url})).hexdigest()
                    except Exception:return None
            cache[url] = asyncio.create_task(download())
        return await cache[url]
    remote_names=unquote(json.dumps(remote,ensure_ascii=False,default=str))
    remote_ids={str(r['id']) for r in remote if r.get('id')}
    markers_verified=all((i.get('_source_sha256') and ('sh-'+i['_source_sha256']) in remote_names) or
                         bool(acknowledged_image_ids(finished.get(image_key(i), {}).get('message')) & remote_ids) for i in images)
    urls=[] if markers_verified else list(dict.fromkeys(u for row in remote for u in remote_urls(row)))
    for digest in await asyncio.gather(*(digest_url(u) for u in urls)):
        if digest:remote_hashes.add(digest)
        else:remote_complete=False
    if remote and any(not remote_urls(row) for row in remote):remote_complete=False
    sources_seen=set()
    async def process_image(image_index, image):
        if image.get('media_type','image')!='image':return
        token=image_key(image)
        async with deps.pool.acquire() as conn:
            previous=await conn.fetchrow('SELECT status,message FROM lightspeed_export_image_results WHERE store_domain=$1 AND destination_id=$2 AND image_key=$3',ls.domain_prefix,destination_id,token)
        if previous and previous['status']=='uploaded' and not audit_completed:totals['skipped']+=1;return
        try:data=await retry_read(read_bytes,image)
        except Exception as exc:
            totals['failed']+=1;totals['messages'].append(f'Source image download failed: {exc}')
            async with deps.pool.acquire() as conn:
                await conn.execute("INSERT INTO lightspeed_export_image_results(store_domain,destination_id,image_key,status,message) VALUES($1,$2,$3,'failed',$4) ON CONFLICT DO NOTHING",ls.domain_prefix,destination_id,token,'Source read failed before upload: '+str(exc)[:900])
            return
        digest=image.get('_source_sha256') or hashlib.sha256(data).hexdigest();marker='sh-'+digest
        names=unquote(json.dumps(remote, ensure_ascii=False, default=str))
        ack_ids=acknowledged_image_ids(previous['message']) if previous else set()
        matched=digest in remote_hashes or marker in names or digest in sources_seen or bool(ack_ids & remote_ids)
        read_hold=previous and str(previous['message']).startswith(('Existing remote images or unavailable inventory:','Image inventory check blocked:','Source read failed before upload:','Read-only pending:'))
        unknown_write=previous and previous['status'] in ('uncertain','running') and not read_hold
        if matched:
            async with deps.pool.acquire() as conn:
                await conn.execute("INSERT INTO lightspeed_export_image_results(store_domain,destination_id,image_key,status,message) VALUES($1,$2,$3,'uploaded',$4) ON CONFLICT(store_domain,destination_id,image_key) DO UPDATE SET status='uploaded',message=EXCLUDED.message,updated_at=NOW() ",ls.domain_prefix,destination_id,token,previous['message'] if ack_ids else 'Verified existing image content')
            totals['skipped']+=1;return
        if previous and previous['status']=='uploaded':
            # Only an acknowledged, now absent image is eligible for replacement.
            # Unknown writes are handled below and never enter this branch.
            try:
                confirmation=await retry_read(ls.remote_family_images,destination_id)
            except Exception as exc:
                totals['uncertain']+=1;totals['messages'].append('Variant image verification failed: '+str(exc));return
            confirmation_ids={str(r['id']) for r in confirmation if r.get('id')}
            if ack_ids & confirmation_ids or marker in unquote(json.dumps(confirmation,default=str)):
                totals['skipped']+=1;return
            if confirmation or remote:
                absent=bool(ack_ids) and not (ack_ids & confirmation_ids) and remote_complete
            else:
                absent=True
            if not absent:
                totals['uncertain']+=1;totals['messages'].append('Variant image no longer verifiable: '+marker+'; no repeat POST sent');return
            async with deps.pool.acquire() as conn:
                await conn.execute("UPDATE lightspeed_export_image_results SET status='retry',updated_at=NOW() WHERE store_domain=$1 AND destination_id=$2 AND image_key=$3 AND status='uploaded' AND message=$4",ls.domain_prefix,destination_id,token,previous['message'])
        if unknown_write and previous['status']=='uncertain' and not remote:
            # Only a finished uncertain attempt on a confirmed empty variant can
            # be retried. Running writes and nonempty galleries remain protected.
            if await confirmed_empty_member(ls, destination_id):
                async with deps.pool.acquire() as conn:
                    await conn.execute("UPDATE lightspeed_export_image_results SET status='retry',updated_at=NOW() WHERE store_domain=$1 AND destination_id=$2 AND image_key=$3 AND status='uncertain' AND message=$4",ls.domain_prefix,destination_id,token,previous['message'])
                unknown_write = False
        if unknown_write or (remote and not remote_complete):
            totals['uncertain']+=1
            totals['messages'].append('Previous image write needs reconciliation: '+marker+'; remote image IDs='+','.join(str(r.get('id') or '?') for r in remote)+'; no repeat POST sent')
            return
        async with deps.pool.acquire() as conn:
            claimed=await conn.fetchval("INSERT INTO lightspeed_export_image_results(store_domain,destination_id,image_key,status,message) VALUES($1,$2,$3,'running','Upload in progress') ON CONFLICT(store_domain,destination_id,image_key) DO UPDATE SET status='running',message='Upload in progress',updated_at=NOW() WHERE lightspeed_export_image_results.status IN ('failed','retry','uncertain') AND lightspeed_export_image_results.message=$4 RETURNING image_key",ls.domain_prefix,destination_id,token,str(previous['message']) if previous else '')
        if not claimed:totals['uncertain']+=1;return
        kind='png' if data.startswith(b'\x89PNG') else 'gif' if data.startswith(b'GIF8') else 'webp' if data[:4]==b'RIFF' and data[8:12]==b'WEBP' else 'jpeg'
        prepared=dict(image,image_base64=base64.b64encode(data).decode(),upload_filename=marker+'.'+kind,upload_content_type='image/'+kind)
        prepared.pop('local_path',None)
        try:
            async with ls._image_sync_slots:
                result=await asyncio.to_thread(ls._upload_images,destination_id,[prepared])
            if result.get('uploaded')==1 and not result.get('failed'):
                status='uploaded'
                message=json.dumps({'acknowledged':True,'image_ids':[r.get('image_id') for r in result.get('outcomes',[]) if r.get('image_id')],'source_sha256':digest},separators=(',',':'))
                totals['uploaded']+=1;sources_seen.add(digest)
            elif result.get('outcomes') and all(not r.get('write_attempted',True) for r in result['outcomes']):
                status,message='failed',json.dumps(result,default=str)[:1200];totals['failed']+=1
            else:
                status,message='uncertain',json.dumps(result,default=str)[:1200];totals['uncertain']+=1
        except Exception as exc:
            status,message='uncertain',str(exc)[:1200];totals['uncertain']+=1
        if status=='uploaded' and audit_completed:
            # A successful upload response must be visible on this exact member.
            expected_ids=acknowledged_image_ids(message)
            confirmed=False
            for attempt in range(2):
                if attempt: await asyncio.sleep(1)
                try:
                    rows=await retry_read(ls.remote_family_images,destination_id)
                    confirmed=bool(expected_ids & {str(r['id']) for r in rows if r.get('id')}) or marker in unquote(json.dumps(rows,default=str))
                except Exception:
                    confirmed=False
                if confirmed: break
            if not confirmed:
                totals['uploaded']-=1;totals['uncertain']+=1;status='uncertain'
                sources_seen.discard(digest)
                message=json.dumps({'image_ids':sorted(expected_ids),'source_sha256':digest,
                                    'error':'Upload acknowledged but not yet visible on the destination variant'})
        if status=='uncertain' and await verify_arrival(ls,destination_id,digest,marker):
            totals['uncertain']-=1;totals['uploaded']+=1;status,message='uploaded','Upload verified automatically after uncertain response';sources_seen.add(digest)
        if status != 'uploaded' and ('has no attribute' in message or 'Incompatible export files' in message):
            totals['_fatal_local_error'] = True
        if status!='uploaded':totals['messages'].append(message)
        async with deps.pool.acquire() as conn:
            await conn.execute('UPDATE lightspeed_export_image_results SET status=$4,message=$5,updated_at=NOW() WHERE store_domain=$1 AND destination_id=$2 AND image_key=$3',ls.domain_prefix,destination_id,token,status,message)
        if status == 'uncertain':
            totals['_new_uncertain_write'] = True
            totals['messages'].append('Stopped this image batch after an unverified write; retry reconciles it before more uploads')
            return
    # Serialize writes to one destination; different variants still run concurrently.
    # Every in-flight POST owns a durable journal claim before it is sent.
    # Finish in-flight writes, then pause unsent work after an uncertain outcome.
    digest_locks={}
    async def run_one(index,image):
        digest=image.get('_source_sha256') or image_key(image)
        async with digest_locks.setdefault(digest,asyncio.Lock()):
            await process_image(index,image)
    for offset in range(0,len(images),1):
        batch=images[offset:offset+1]
        outcomes=await asyncio.gather(*(run_one(offset+i,image) for i,image in enumerate(batch)),return_exceptions=True)
        for outcome in outcomes:
            if isinstance(outcome,Exception):
                totals['failed']+=1;totals['messages'].append(str(outcome))
        if totals.get('_new_uncertain_write') or totals.get('_fatal_local_error'):
            remaining=len(images)-offset-len(batch)
            totals['uncertain']+=remaining
            if remaining:totals['messages'].append(f'{remaining} images paused; reconcile the pending write before continuing')
            break
    return totals

