"""Bounded supplier-image proxy with validated redirects, retries and caching."""
import asyncio
import logging
import time
from collections import OrderedDict
from urllib.parse import urlparse, urljoin

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api')
ALLOWED_DOMAINS = (
    'media.sanmarcanada.com', 'sanmarcanada.com', 'cdn-atc.ca',
    'images.atc.ca', 'atc.ca', 'cdn.ssactivewear.com', 'ssactivewear.com',
    'media.alphabroder.com', 'alphabroder.com',
    'athleticknit.com', 'caldwellrecognition.com',
)
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_CACHE_BYTES = 48 * 1024 * 1024
CACHE_SECONDS = 3600
_cache = OrderedDict()
_cache_bytes = 0
_slots = asyncio.Semaphore(6)
_flights = {}


def validate_url(url):
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or '').lower()
        valid = (parsed.scheme in ('http', 'https') and not parsed.username
                 and not parsed.password and parsed.port in (None, 80, 443)
                 and any(host == allowed or host.endswith('.' + allowed)
                         for allowed in ALLOWED_DOMAINS))
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(403, 'Supplier image URL is not allowed')
    return host


def cache_get(url):
    global _cache_bytes
    entry = _cache.get(url)
    if not entry:
        return None
    expires, content, kind = entry
    if expires <= time.monotonic():
        _cache.pop(url)
        _cache_bytes -= len(content)
        return None
    _cache.move_to_end(url)
    return content, kind


def cache_put(url, content, kind):
    global _cache_bytes
    previous = _cache.pop(url, None)
    if previous:
        _cache_bytes -= len(previous[1])
    _cache[url] = (time.monotonic() + CACHE_SECONDS, content, kind)
    _cache_bytes += len(content)
    while _cache_bytes > MAX_CACHE_BYTES or len(_cache) > 200:
        _, old = _cache.popitem(last=False)
        _cache_bytes -= len(old[1])


def image_type(header, content):
    kind = header.split(';', 1)[0].strip().lower()
    if content.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if content.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if content.startswith((b'GIF87a', b'GIF89a')): return 'image/gif'
    if content.startswith(b'RIFF') and content[8:12] == b'WEBP': return 'image/webp'
    # SVG is deliberately excluded from this public supplier proxy.
    if kind in ('image/avif', 'image/heic', 'image/heif') and content[4:8] == b'ftyp': return kind
    raise HTTPException(502, 'Supplier returned an unsupported or invalid image')


async def fetch_image(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 SupplierHub/1.0',
        'Accept': 'image/*', 'Accept-Language': 'en-CA,en;q=0.9',
        'Referer': 'https://' + validate_url(url) + '/',
    }
    async with _slots:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=False, trust_env=False,
        ) as client:
            for attempt in range(2):
                try:
                    current = url
                    for hop in range(5):
                        validate_url(current)
                        async with client.stream('GET', current, headers=headers) as upstream:
                            status = upstream.status_code
                            if status in (301, 302, 303, 307, 308):
                                location = upstream.headers.get('location')
                                if not location: raise HTTPException(502, 'Supplier image redirect has no destination')
                                current = urljoin(current, location)
                                validate_url(current)
                                continue
                            if status in (502, 503, 504) and attempt == 0:
                                break
                            if status != 200:
                                raise HTTPException(status if status in (403, 404, 429) else 502,
                                                    f'Supplier image returned HTTP {status}')
                            content = bytearray()
                            async for chunk in upstream.aiter_bytes():
                                content.extend(chunk)
                                if len(content) > MAX_IMAGE_BYTES:
                                    raise HTTPException(413, 'Supplier image exceeds the size limit')
                            data = bytes(content)
                            kind = image_type(upstream.headers.get('content-type', ''), data)
                            cache_put(url, data, kind)
                            return data, kind
                    else:
                        raise HTTPException(502, 'Too many supplier image redirects')
                except httpx.TimeoutException as exc:
                    logger.warning('Image timeout [%s] host=%s attempt=%s', type(exc).__name__, validate_url(url), attempt + 1)
                    if attempt == 1: raise HTTPException(504, 'Supplier image timed out after two attempts') from exc
                except httpx.RequestError as exc:
                    logger.warning('Image network error [%s] host=%s attempt=%s', type(exc).__name__, validate_url(url), attempt + 1)
                    if attempt == 1: raise HTTPException(502, 'Could not reach the supplier image server after two attempts') from exc
                await asyncio.sleep(1)
    raise HTTPException(502, 'Supplier image could not be downloaded')


@router.get('/media_proxy')
async def media_proxy(url: str):
    validate_url(url)
    cached = cache_get(url)
    if cached:
        content, kind = cached
    else:
        # Concurrent browser requests for one image share the same download.
        task = _flights.get(url)
        if task is None:
            if len(_flights) >= 100:
                raise HTTPException(503, 'Image queue is busy. Retry shortly.')
            task = asyncio.create_task(fetch_image(url))
            _flights[url] = task
            def finished(done):
                if _flights.get(url) is done: _flights.pop(url, None)
                if not done.cancelled(): done.exception()
            task.add_done_callback(finished)
        content, kind = await asyncio.shield(task)
    return Response(content, media_type=kind, headers={
        'Cache-Control': 'public, max-age=3600',
        'Access-Control-Allow-Origin': '*', 'X-Content-Type-Options': 'nosniff',
    })



async def cache_product_images(product_id, media_id=None):
    """Persist validated supplier bytes using the existing image_base64 column.

    Never hold a database connection while downloading. Existing copies are retained
    on failures, and existing URLs/variant associations are not changed.
    """
    import base64
    import deps
    async with deps.pool.acquire() as conn:
        rows = await conn.fetch("""SELECT id,url,
            COALESCE(image_base64,'')<>'' AS stored
            FROM product_media WHERE product_id=$1 AND media_type='image'
            AND ($2::text IS NULL OR id=$2)
            ORDER BY is_primary DESC,created_at""", product_id, media_id)

    async def save(row):
        if row['stored']:
            return 'cached', ''
        url = str(row['url'] or '').strip()
        try:
            validate_url(url)
            # A previous download can be shared across size/colour variants.
            cached = cache_get(url)
            content, kind = cached or await fetch_image(url)
            encoded = 'data:' + kind + ';base64,' + base64.b64encode(content).decode('ascii')
            async with deps.pool.acquire() as conn:
                await conn.execute("""UPDATE product_media SET image_base64=$3
                    WHERE id=$1 AND url=$2 AND COALESCE(image_base64,'')=''""",
                    row['id'],url,encoded)
            return 'downloaded', ''
        except HTTPException as exc:
            return 'failed', str(exc.detail)
        except Exception:
            logger.exception('Could not persist supplier image media_id=%s',row['id'])
            return 'failed', 'Image could not be saved; check backend logs'

    # Avoid creating one concurrent task per image in large catalogues.
    results = []
    for offset in range(0,len(rows),6):
        results.extend(await asyncio.gather(*(save(row) for row in rows[offset:offset+6])))
    return {'downloaded':sum(status=='downloaded' for status,_ in results),
            'cached':sum(status=='cached' for status,_ in results),
            'failed':sum(status=='failed' for status,_ in results),
            'errors':list(dict.fromkeys(error for status,error in results if status=='failed'))[:3]}


@router.get('/media/{media_id}/content')
async def stored_image(media_id: str):
    """Backfill a missing copy once, then serve persisted supplier bytes."""
    import base64
    import binascii
    import hashlib
    import deps
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT product_id,image_base64 FROM product_media WHERE id=$1 AND media_type='image'",media_id)
    if not row:
        raise HTTPException(404,'Image record not found')
    if not row['image_base64']:
        outcome = await cache_product_images(row['product_id'], media_id=media_id)
        if outcome['failed']:
            raise HTTPException(502, '; '.join(outcome['errors']) or 'Supplier image download failed')
        async with deps.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT image_base64 FROM product_media WHERE id=$1 AND media_type='image'",media_id)
        if not row or not row['image_base64']:
            raise HTTPException(409,'Image changed while saving; reload the product')
    try:
        encoded = str(row['image_base64'])
        header = ''
        if encoded.startswith('data:'):
            header,encoded = encoded.split(',',1)
        if len(encoded) > (MAX_IMAGE_BYTES * 4 // 3 + 8):
            raise ValueError('Image too large')
        content = base64.b64decode(encoded,validate=True)
        kind = image_type(header[5:].split(';',1)[0],content)
    except (ValueError,binascii.Error) as exc:
        raise HTTPException(502,'Stored image data is invalid; refresh supplier media') from exc
    return Response(content,media_type=kind,headers={
        'Cache-Control':'public, max-age=3600',
        'ETag':'"'+hashlib.sha256(content).hexdigest()+'"',
        'X-Content-Type-Options':'nosniff'})


async def stored_export_images(product_id, images):
    """Persist source records/links and bytes before any Lightspeed image write."""
    import json
    import deps
    from deps import new_id
    candidates = [dict(i) for i in images if i.get('media_type', 'image') == 'image']
    async with deps.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock(hashtext($1))', 'image-sources:' + str(product_id))
            for image in candidates:
                url = str(image.get('url') or '').strip()
                if not url:
                    continue
                old = await conn.fetchrow(
                    'SELECT id,source_part_ids FROM product_media WHERE product_id=$1 AND url=$2 ORDER BY created_at LIMIT 1',
                    product_id,url)
                parts = image.get('source_part_ids') or []
                if isinstance(parts,str): parts=json.loads(parts)
                if old:
                    prior = old['source_part_ids'] or []
                    if isinstance(prior,str): prior=json.loads(prior)
                    parts = list(dict.fromkeys([str(p) for p in prior + list(parts)]))
                    await conn.execute(
                        "UPDATE product_media SET source_part_ids=$2::jsonb WHERE id=$1",
                        old['id'],json.dumps(parts))
                else:
                    await conn.execute(
                        """INSERT INTO product_media
                        (id,product_id,media_type,url,description,is_primary,created_at,source_color,source_part_ids)
                        VALUES($1,$2,'image',$3,$4,$5,NOW(),$6,$7::jsonb)""",
                        new_id(),product_id,url,image.get('description') or '',
                        bool(image.get('is_primary')),image.get('source_color') or image.get('color') or '',json.dumps(list(parts)))
    outcome = await cache_product_images(product_id)
    async with deps.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM product_media WHERE product_id=$1 AND media_type='image' ORDER BY is_primary DESC,created_at",
            product_id)
    by_url = {str(r['url'] or '').strip():dict(r) for r in rows}
    prepared, missing = [], []
    for image in candidates:
        url = str(image.get('url') or '').strip()
        stored = by_url.get(url)
        if stored and stored.get('image_base64'):
            prepared.append(dict(image, image_base64=stored['image_base64'],
                                 id=stored['id']))
        elif not url and image.get('image_base64'):
            # Caller-provided bytes with no durable media identity are not export-ready.
            missing.append('Image has no saved supplier URL/record')
        else:
            missing.append(url or 'Image source URL missing')
    if missing:
        details = '; '.join(outcome['errors'])
        raise ValueError(
            f'{len(missing)} supplier images are not stored in SupplierHub; no Lightspeed image upload sent. '
            + (details + '; ' if details else '') + 'First source: ' + missing[0])
    return prepared

