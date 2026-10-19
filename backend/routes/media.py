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
        'Referer': 'https://www.sanmarcanada.com/',
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
