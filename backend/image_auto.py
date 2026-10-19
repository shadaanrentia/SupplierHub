"""Automatic image reconciliation. Unknown POST outcomes are never blindly repeated."""
import asyncio
import base64
import hashlib
import json
import os
from urllib.parse import unquote
import requests
import deps


def read_bytes(image):
    raw=image.get('image_base64')
    if raw:
        data=raw if isinstance(raw,bytes) else base64.b64decode(str(raw).split(',',1)[-1])
    elif image.get('local_path') and os.path.isfile(image['local_path']):
        with open(image['local_path'],'rb') as stream:data=stream.read()
    else:
        response=requests.get(str(image.get('url') or ''),timeout=30,headers={'User-Agent':'SupplierHub/1.0'})
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


def remote_urls(image):
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


async def sync_images(ls,destination_id,images):
    from export_safety import image_key
    destination_id=str(destination_id)
    totals={'uploaded':0,'skipped':0,'failed':0,'uncertain':0,'messages':[]}
    images = [i for i in images if i.get('media_type','image') == 'image']
    if not images: return totals
    # Skip completed journals before any remote image GET/hash download.
    async with deps.pool.acquire() as conn:
        finished = await conn.fetch("SELECT image_key FROM lightspeed_export_image_results WHERE store_domain=$1 AND destination_id=$2 AND status='uploaded' AND image_key=ANY($3::text[])", ls.domain_prefix, destination_id, [image_key(i) for i in images])
    finished = {r['image_key'] for r in finished}
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
    urls=list(dict.fromkeys(u for row in remote for u in remote_urls(row)))
    for digest in await asyncio.gather(*(digest_url(u) for u in urls)):
        if digest:remote_hashes.add(digest)
        else:remote_complete=False
    if remote and any(not remote_urls(row) for row in remote):remote_complete=False
    sources_seen=set()
    for image_index, image in enumerate(images):
        if image.get('media_type','image')!='image':continue
        token=image_key(image)
        async with deps.pool.acquire() as conn:
            previous=await conn.fetchrow('SELECT status,message FROM lightspeed_export_image_results WHERE store_domain=$1 AND destination_id=$2 AND image_key=$3',ls.domain_prefix,destination_id,token)
        if previous and previous['status']=='uploaded':totals['skipped']+=1;continue
        try:data=await retry_read(read_bytes,image)
        except Exception as exc:
            totals['failed']+=1;totals['messages'].append(f'Source image download failed: {exc}')
            async with deps.pool.acquire() as conn:
                await conn.execute("INSERT INTO lightspeed_export_image_results(store_domain,destination_id,image_key,status,message) VALUES($1,$2,$3,'failed',$4) ON CONFLICT DO NOTHING",ls.domain_prefix,destination_id,token,'Source read failed before upload: '+str(exc)[:900])
            continue
        digest=hashlib.sha256(data).hexdigest();marker='sh-'+digest
        names=unquote(json.dumps(remote, ensure_ascii=False, default=str))
        matched=digest in remote_hashes or marker in names or digest in sources_seen
        read_hold=previous and str(previous['message']).startswith(('Existing remote images or unavailable inventory:','Image inventory check blocked:','Source read failed before upload:','Read-only pending:'))
        unknown_write=previous and previous['status'] in ('uncertain','running') and not read_hold
        if matched:
            async with deps.pool.acquire() as conn:
                await conn.execute("INSERT INTO lightspeed_export_image_results(store_domain,destination_id,image_key,status,message) VALUES($1,$2,$3,'uploaded','Verified existing image content') ON CONFLICT(store_domain,destination_id,image_key) DO UPDATE SET status='uploaded',message=EXCLUDED.message,updated_at=NOW() ",ls.domain_prefix,destination_id,token)
            totals['skipped']+=1;continue
        if unknown_write or (remote and not remote_complete):
            totals['uncertain']+=1
            totals['messages'].append('Previous image write needs reconciliation: '+marker+'; remote image IDs='+','.join(str(r.get('id') or '?') for r in remote)+'; no repeat POST sent')
            continue
        async with deps.pool.acquire() as conn:
            claimed=await conn.fetchval("INSERT INTO lightspeed_export_image_results(store_domain,destination_id,image_key,status,message) VALUES($1,$2,$3,'running','Upload in progress') ON CONFLICT(store_domain,destination_id,image_key) DO UPDATE SET status='running',message='Upload in progress',updated_at=NOW() WHERE lightspeed_export_image_results.status IN ('failed','retry','uncertain') AND lightspeed_export_image_results.message=$4 RETURNING image_key",ls.domain_prefix,destination_id,token,str(previous['message']) if previous else '')
        if not claimed:totals['uncertain']+=1;continue
        kind='png' if data.startswith(b'\x89PNG') else 'gif' if data.startswith(b'GIF8') else 'webp' if data[:4]==b'RIFF' and data[8:12]==b'WEBP' else 'jpeg'
        prepared=dict(image,image_base64=base64.b64encode(data).decode(),upload_filename=marker+'.'+kind,upload_content_type='image/'+kind)
        prepared.pop('local_path',None)
        try:
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
        if status=='uncertain' and await verify_arrival(ls,destination_id,digest,marker):
            totals['uncertain']-=1;totals['uploaded']+=1;status,message='uploaded','Upload verified automatically after uncertain response';sources_seen.add(digest)
        if status != 'uploaded' and ('has no attribute' in message or 'Incompatible export files' in message):
            totals['_fatal_local_error'] = True
        if status!='uploaded':totals['messages'].append(message)
        async with deps.pool.acquire() as conn:
            await conn.execute('UPDATE lightspeed_export_image_results SET status=$4,message=$5,updated_at=NOW() WHERE store_domain=$1 AND destination_id=$2 AND image_key=$3',ls.domain_prefix,destination_id,token,status,message)
        if status == 'uncertain':
            totals['_new_uncertain_write'] = True
            totals['uncertain'] += len(images) - image_index - 1
            totals['messages'].append('Stopped this image batch after an unverified write; retry reconciles it before more uploads')
            break
    return totals
