"""Download images from the web: by search words, or from a page URL.

Safety, because the URLs come from the open internet:
- only http/https; the host must resolve to a public address (no localhost / LAN / metadata IPs),
  and redirects are re-checked hop by hop;
- each file is size-capped, must declare an image content type AND decode as a real image,
  and is saved under a fresh name (never a name taken from the server) in one folder;
- counts are capped and duplicates (same bytes) are skipped.
"""
from __future__ import annotations

import hashlib
import io
import ipaddress
import logging
import os
import re
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests

from utils.config import Config

MAX_IMAGES = 20
MAX_BYTES = 15 * 1024 * 1024
_TIMEOUT = 10
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Flexie/2.0"
_EXT = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp", "BMP": ".bmp"}
_log = logging.getLogger("Flexie.ImageDownloader")


@dataclass
class DownloadResult:
    folder: str = ""
    saved: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)   # reasons, one per failed URL
    source: str = ""

    def summary(self) -> str:
        if not self.saved:
            why = f" ({self.skipped[0]})" if self.skipped else ""
            return f"I couldn't download any images from {self.source}{why}."
        extra = f" {len(self.skipped)} could not be downloaded." if self.skipped else ""
        n = len(self.saved)
        return f"Downloaded {n} image{'s' if n != 1 else ''} from {self.source} to {self.folder}.{extra}"


def _public_host(host: str) -> bool:
    """True only if every address the host resolves to is a public one."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False
    return bool(infos)


def is_safe_url(url: str) -> bool:
    p = urlparse(url or "")
    return p.scheme in ("http", "https") and bool(p.hostname) and _public_host(p.hostname)


def _get(url: str, *, stream: bool = False, max_redirects: int = 4) -> requests.Response:
    """GET with manual redirects so every hop is checked against ``is_safe_url``."""
    for _ in range(max_redirects + 1):
        if not is_safe_url(url):
            raise ValueError("blocked address or scheme")
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=_TIMEOUT, stream=stream, allow_redirects=False)
        if r.is_redirect or r.is_permanent_redirect:
            url = urljoin(url, r.headers.get("Location", ""))
            r.close()
            continue
        return r
    raise ValueError("too many redirects")


def search_image_urls(query: str, count: int) -> list[str]:
    """Image URLs for a search phrase (DuckDuckGo image search; safe-search on)."""
    try:
        from ddgs import DDGS
    except ImportError:
        return []
    out: list[str] = []
    try:
        with DDGS() as ddgs:
            for item in ddgs.images(query, max_results=min(count * 3, 60), safesearch="on"):
                u = item.get("image")
                if u and u not in out:
                    out.append(u)
    except Exception as e:
        _log.warning("image search failed: %s", e)
    return out


def page_image_urls(page_url: str, limit: int = 60) -> list[str]:
    """Image URLs found on a web page: <img> (largest srcset entry), og:image, links to image files."""
    from bs4 import BeautifulSoup
    r = _get(page_url, stream=True)
    try:
        if r.status_code != 200:
            raise ValueError(f"page returned HTTP {r.status_code}")
        html = r.raw.read(3 * 1024 * 1024, decode_content=True)
    finally:
        r.close()
    soup = BeautifulSoup(html, "lxml")
    found: list[str] = []

    def add(u):
        if u and not u.startswith("data:"):
            full = urljoin(page_url, u.strip())
            if full not in found:
                found.append(full)

    for meta in soup.find_all("meta", attrs={"property": "og:image"}):
        add(meta.get("content"))
    for img in soup.find_all("img"):
        srcset = img.get("srcset")
        if srcset:
            best = max((part.strip().split() for part in srcset.split(",") if part.strip()),
                       key=lambda p: float(re.sub(r"[^\d.]", "", p[1]) or 0) if len(p) > 1 else 0, default=None)
            if best:
                add(best[0])
        add(img.get("data-src") or img.get("src"))
    for a in soup.find_all("a", href=True):
        if re.search(r"\.(?:jpe?g|png|gif|webp|bmp)(?:\?|$)", a["href"], re.I):
            add(a["href"])
    return found[:limit]


def _save_image(url: str, folder: str, seen: set[str]) -> str:
    """Download one URL; returns the saved path or raises ValueError with a short reason."""
    r = _get(url, stream=True)
    try:
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if not ctype.startswith("image/"):
            raise ValueError("not an image")
        if int(r.headers.get("Content-Length") or 0) > MAX_BYTES:
            raise ValueError("too large")
        data = b""
        for chunk in r.iter_content(64 * 1024):
            data += chunk
            if len(data) > MAX_BYTES:
                raise ValueError("too large")
    finally:
        r.close()
    digest = hashlib.sha256(data).hexdigest()
    if digest in seen:
        raise ValueError("duplicate")
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
            fmt = im.format or ""
    except Exception as e:
        raise ValueError("not a valid image") from e
    ext = _EXT.get(fmt)
    if ext is None:
        raise ValueError(f"unsupported format {fmt or 'unknown'}")
    seen.add(digest)
    path = os.path.join(folder, f"img_{len(seen):02d}_{digest[:8]}{ext}")
    with open(path, "xb") as f:
        f.write(data)
    return path


def default_root() -> str:
    return os.path.join(getattr(Config, "USER_HOME", os.path.expanduser("~")), "Downloads", "Flexie Images")


def _folder_for(label: str, root: str | None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40] or "images"
    base = os.path.join(root or default_root(), f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}")
    os.makedirs(base, exist_ok=True)
    return base


def download(urls: list[str], count: int, label: str, source: str, root: str | None = None) -> DownloadResult:
    """Download up to ``count`` images from ``urls`` into a new folder."""
    count = max(1, min(int(count), MAX_IMAGES))
    res = DownloadResult(source=source)
    if not urls:
        res.skipped.append("no image links found")
        return res
    folder = _folder_for(label, root)
    seen: set[str] = set()
    for url in urls:
        if len(res.saved) >= count:
            break
        try:
            res.saved.append(_save_image(url, folder, seen))
        except (ValueError, requests.RequestException, OSError) as e:
            res.skipped.append(str(e))
    res.folder = folder
    if not res.saved:
        try:
            os.rmdir(folder)  # nothing downloaded: leave no empty folder behind
            res.folder = ""
        except OSError:
            pass
    return res


def download_by_search(query: str, count: int = 5, root: str | None = None) -> DownloadResult:
    urls = search_image_urls(query, count)
    return download(urls, count, query, f"a web search for {query}", root)


def download_from_page(url: str, count: int = 10, root: str | None = None) -> DownloadResult:
    host = urlparse(url).hostname or "page"
    try:
        urls = page_image_urls(url)
    except (ValueError, requests.RequestException) as e:
        res = DownloadResult(source=host)
        res.skipped.append(str(e))
        return res
    return download(urls, count, host, host, root)
