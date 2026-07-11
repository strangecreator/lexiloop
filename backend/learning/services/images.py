"""Card image acquisition and storage.

Images arrive three ways: a direct file upload, a URL the server downloads, or
— when a plain download fails — an LLM that reads the linked page and points at
a direct image URL. Every stored image is re-encoded to JPEG (stripping the
original payload and metadata) with a tiny blurred-placeholder thumbnail.
"""
from __future__ import annotations

import io
import ipaddress
import re
import secrets
import socket
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_DOWNLOAD_BYTES = 12 * 1024 * 1024
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_DIMENSION = 1600
THUMB_DIMENSION = 40
MAX_PAGE_BYTES = 512 * 1024
REQUEST_TIMEOUT = 15
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'


class ImageError(Exception):
    """User-facing problem with fetching or decoding an image."""


def extract_direct_url(url: str) -> str:
    """Unwrap search-result links to the real image URL.

    Yandex (yandex.*, ya.ru) carries it in img_url, Google's /imgres in imgurl,
    Bing in mediaurl. The check is host-agnostic: whatever page embeds one of
    these parameters, the parameter is the picture the user chose.
    """
    query = parse_qs(urlparse(url).query)
    for key in ('img_url', 'imgurl', 'mediaurl'):
        values = query.get(key)
        # parse_qs already percent-decodes; decoding twice would corrupt
        # URLs that legitimately contain %-sequences.
        if values and values[0].startswith(('http://', 'https://')):
            return values[0]
    return url


SEARCH_HOSTS = ('google.', 'yandex.', 'ya.ru', 'bing.', 'duckduckgo.')


def search_query_from_url(url: str) -> str:
    """The text query of an image-search page URL, or '' when it is not one."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if not any(marker in host for marker in SEARCH_HOSTS):
        return ''
    query = parse_qs(parsed.query)
    for key in ('q', 'text'):
        values = query.get(key)
        if values and values[0].strip():
            return values[0].strip()
    return ''


def search_image_candidates(query: str) -> list[dict]:
    """Candidate images for a search query from keyless public APIs.

    Google/Yandex image pages render only through JavaScript, so the selected
    picture cannot be scraped from them. Instead the same query is run against
    Openverse and Wikimedia Commons and the image assistant picks the best fit.
    """
    candidates: list[dict] = []
    headers = {'User-Agent': 'LexiLoop/1.0 (vocabulary flashcards)'}
    try:
        response = requests.get('https://api.openverse.org/v1/images/',
                                params={'q': query, 'page_size': 12}, headers=headers, timeout=REQUEST_TIMEOUT)
        for item in (response.json().get('results') or []):
            if item.get('url'):
                candidates.append({'url': item['url'], 'title': str(item.get('title') or '')[:120]})
    except (requests.RequestException, ValueError):
        pass
    try:
        response = requests.get('https://commons.wikimedia.org/w/api.php', params={
            'action': 'query', 'generator': 'search', 'gsrsearch': f'filetype:bitmap {query}',
            'gsrnamespace': 6, 'gsrlimit': 8, 'prop': 'imageinfo', 'iiprop': 'url',
            'iiurlwidth': 1280, 'format': 'json',
        }, headers=headers, timeout=REQUEST_TIMEOUT)
        pages = (response.json().get('query') or {}).get('pages', {})
        for page in pages.values():
            info = (page.get('imageinfo') or [{}])[0]
            image_url = info.get('thumburl') or info.get('url')
            if image_url:
                title = str(page.get('title') or '').removeprefix('File:')[:120]
                candidates.append({'url': image_url, 'title': title})
    except (requests.RequestException, ValueError):
        pass
    if not candidates:
        raise ImageError(f'No images could be found for “{query}”.')
    return candidates[:30]


def _check_host(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ImageError('Only http(s) links are supported.')
    host = parsed.hostname or ''
    if not host:
        raise ImageError('The link has no host.')
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ImageError(f'Could not resolve {host}.') from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            raise ImageError('Links to private or internal addresses are not allowed.')


def _get(url: str, *, max_bytes: int) -> requests.Response:
    _check_host(url)
    try:
        response = requests.get(
            url, timeout=REQUEST_TIMEOUT, stream=True, allow_redirects=True,
            headers={'User-Agent': USER_AGENT, 'Accept': 'image/*,text/html;q=0.8,*/*;q=0.5'},
        )
    except requests.RequestException as exc:
        raise ImageError(f'The link could not be fetched: {exc.__class__.__name__}.') from exc
    if response.status_code >= 400:
        raise ImageError(f'The link answered with HTTP {response.status_code}.')
    declared = response.headers.get('Content-Length')
    if declared and int(declared) > max_bytes:
        raise ImageError('The file is larger than 12 MB.')
    return response


def _read_limited(response: requests.Response, max_bytes: int, *, truncate: bool = False) -> bytes:
    chunks, size = [], 0
    for chunk in response.iter_content(chunk_size=65536):
        size += len(chunk)
        if size > max_bytes:
            if truncate:
                chunks.append(chunk[:max_bytes - (size - len(chunk))])
                break
            raise ImageError('The file is larger than 12 MB.')
        chunks.append(chunk)
    return b''.join(chunks)


def download_image(url: str) -> bytes:
    """Download and return raw bytes that PIL can decode, or raise ImageError."""
    direct = extract_direct_url(url.strip())
    response = _get(direct, max_bytes=MAX_DOWNLOAD_BYTES)
    content_type = (response.headers.get('Content-Type') or '').split(';')[0].strip().lower()
    if content_type.startswith('text/') or content_type in ('application/xhtml+xml', 'application/xml'):
        raise ImageError('The link points to a web page, not an image file.')
    data = _read_limited(response, MAX_DOWNLOAD_BYTES)
    _decode(data)  # raises ImageError when the payload is not an image
    return data


def _decode(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageError('The file could not be read as an image.') from exc
    image = ImageOps.exif_transpose(image)
    if image.mode not in ('RGB', 'L'):
        background = Image.new('RGB', image.size, (255, 255, 255))
        converted = image.convert('RGBA')
        background.paste(converted, mask=converted.getchannel('A'))
        return background
    return image.convert('RGB')


def _encode_jpeg(image: Image.Image, *, max_dimension: int, quality: int) -> bytes:
    copy = image.copy()
    copy.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
    buffer = io.BytesIO()
    copy.save(buffer, format='JPEG', quality=quality, optimize=True, progressive=True)
    return buffer.getvalue()


def store_card_image(card, data: bytes) -> None:
    """Re-encode and attach the image + blur-up thumbnail to the card."""
    image = _decode(data)
    if image.width < 32 or image.height < 32:
        raise ImageError('The image is too small to be useful (under 32px).')
    full = _encode_jpeg(image, max_dimension=MAX_DIMENSION, quality=84)
    thumb = _encode_jpeg(image, max_dimension=THUMB_DIMENSION, quality=60)
    remove_card_image(card, save=False)
    stem = f'{card.id}-{secrets.token_hex(6)}'
    card.image.save(f'{stem}.jpg', ContentFile(full), save=False)
    card.image_thumb.save(f'{stem}.thumb.jpg', ContentFile(thumb), save=False)
    card.save(update_fields=['image', 'image_thumb', 'updated_at'])


def remove_card_image(card, *, save: bool = True) -> None:
    for field in (card.image, card.image_thumb):
        if field:
            field.delete(save=False)
    card.image = ''
    card.image_thumb = ''
    if save:
        card.save(update_fields=['image', 'image_thumb', 'updated_at'])


class _CandidateParser(HTMLParser):
    """Collect plausible image URLs from a page: og/twitter meta first, then <img>."""

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.meta: list[str] = []
        self.images: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            key = (attrs.get('property') or attrs.get('name') or '').lower()
            if key in ('og:image', 'og:image:url', 'og:image:secure_url', 'twitter:image', 'twitter:image:src'):
                content = (attrs.get('content') or '').strip()
                if content:
                    self.meta.append(urljoin(self.base_url, content))
        elif tag == 'img':
            src = (attrs.get('src') or attrs.get('data-src') or '').strip()
            if src and not src.startswith('data:'):
                self.images.append(urljoin(self.base_url, src))


def page_image_candidates(url: str) -> tuple[str, list[str]]:
    """Fetch a page and return (title, candidate image URLs), meta images first."""
    response = _get(url, max_bytes=MAX_DOWNLOAD_BYTES)
    # Pages larger than the cap are truncated, not rejected: og:image and the
    # first content images live near the top of the document anyway.
    html = _read_limited(response, MAX_PAGE_BYTES, truncate=True).decode(response.encoding or 'utf-8', errors='replace')
    parser = _CandidateParser(response.url or url)
    try:
        parser.feed(html)
    except Exception:
        pass
    title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    title = re.sub(r'\s+', ' ', title_match.group(1)).strip()[:200] if title_match else ''
    seen, ordered = set(), []
    for candidate in parser.meta + parser.images:
        if candidate not in seen and candidate.startswith(('http://', 'https://')):
            seen.add(candidate)
            ordered.append(candidate)
    return title, ordered[:40]
