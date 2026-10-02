"""PDF download and text extraction for Drucksachen.

The bill PDFs live on dserver.bundestag.de and are public (no auth), unlike the
DIP search API. Downloads are cached on disk (``config.PDF_CACHE_DIR``) so
re-runs and ``--force`` re-analyses never re-download an unchanged Drucksache.
Text is extracted locally with ``pypdf`` and cached as a ``.txt`` sidecar next
to the PDF, so re-analyses of an unchanged Drucksache skip extraction too.
"""

import io
import os
from pathlib import Path

import httpx
from pypdf import PdfReader

from backend import config

_TIMEOUT = 30.0


def _cache_path(cache_dir: str, url: str, cache_key: str | None) -> Path:
    """Cache file for a PDF, keyed by URL filename plus the DIP ``pdf_hash``.

    Including the hash means a Drucksache that is corrected and republished
    under the same URL (new ``pdf_hash`` in DIP) is fetched fresh instead of
    served stale from the cache.
    """
    name = os.path.basename(url) or "drucksache.pdf"
    if cache_key:
        name = f"{cache_key[:16]}-{name}"
    return Path(cache_dir) / name


def _write_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` via a per-process temp file + atomic rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp-{os.getpid()}-{id(data)}")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def download_pdf(url: str, cache_key: str | None = None) -> bytes:
    """Download a Drucksache PDF (public host, no auth). Raises on non-200.

    Served from the on-disk cache when possible; a fresh download is written
    back to the cache. ``cache_key`` should be the DIP ``pdf_hash`` so cache
    entries invalidate when the published PDF changes. Safe under concurrent
    callers: writes go to a per-process temp file and are atomically renamed.
    """
    path = _cache_path(config.PDF_CACHE_DIR, url, cache_key) if config.PDF_CACHE_DIR else None
    if path is not None and path.exists():
        return path.read_bytes()

    resp = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True)
    if resp.status_code != 200:
        raise RuntimeError(
            f"PDF download failed: GET {url} -> {resp.status_code}"
        )

    if path is not None:
        _write_atomic(path, resp.content)
    return resp.content


def extract_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes, joining page texts with '\\n'."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def get_text(url: str, cache_key: str | None = None) -> str:
    """Text of a Drucksache PDF, extracting at most once per ``cache_key``.

    Served from a ``.txt`` sidecar next to the cached PDF when present;
    otherwise the PDF is downloaded (or read from its cache), extracted with
    ``pypdf`` and the text written back. The sidecar shares the PDF's cache
    name — keyed by the DIP ``pdf_hash`` — so a republished Drucksache is
    re-extracted while ``--force``/prompt-version re-runs skip extraction.
    """
    pdf_path = _cache_path(config.PDF_CACHE_DIR, url, cache_key) if config.PDF_CACHE_DIR else None
    txt_path = pdf_path.with_suffix(pdf_path.suffix + ".txt") if pdf_path is not None else None
    if txt_path is not None and txt_path.exists():
        return txt_path.read_text(encoding="utf-8")

    text = extract_text(download_pdf(url, cache_key))
    if txt_path is not None:
        _write_atomic(txt_path, text.encode("utf-8"))
    return text
