"""Unit tests for the PDF download cache. Fully offline: httpx is patched."""

import pytest

from backend import config
from backend.dip import pdf_text


class _Resp:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code


@pytest.fixture()
def cache_dir(tmp_path, monkeypatch):
    d = tmp_path / "pdf-cache"
    monkeypatch.setattr(config, "PDF_CACHE_DIR", str(d))
    return d


def test_download_is_cached(cache_dir, monkeypatch):
    calls = {"n": 0}

    def _get(url, **kwargs):
        calls["n"] += 1
        return _Resp(b"%PDF-1")

    monkeypatch.setattr(pdf_text.httpx, "get", _get)

    url = "https://example.org/btd/21/069/2106916.pdf"
    assert pdf_text.download_pdf(url, cache_key="hash-a") == b"%PDF-1"
    assert pdf_text.download_pdf(url, cache_key="hash-a") == b"%PDF-1"
    assert calls["n"] == 1  # second call served from cache
    assert (cache_dir / "hash-a-2106916.pdf").exists()


def test_changed_pdf_hash_busts_cache(cache_dir, monkeypatch):
    responses = iter([_Resp(b"old"), _Resp(b"new")])
    monkeypatch.setattr(pdf_text.httpx, "get", lambda url, **kw: next(responses))

    url = "https://example.org/2106916.pdf"
    assert pdf_text.download_pdf(url, cache_key="hash-old") == b"old"
    # DIP reports a new pdf_hash for the same URL -> fresh download.
    assert pdf_text.download_pdf(url, cache_key="hash-new") == b"new"


def test_cache_disabled_via_empty_dir(monkeypatch):
    monkeypatch.setattr(config, "PDF_CACHE_DIR", "")
    calls = {"n": 0}

    def _get(url, **kwargs):
        calls["n"] += 1
        return _Resp(b"%PDF-1")

    monkeypatch.setattr(pdf_text.httpx, "get", _get)

    url = "https://example.org/2106916.pdf"
    pdf_text.download_pdf(url)
    pdf_text.download_pdf(url)
    assert calls["n"] == 2  # no caching


def test_get_text_extracts_once_per_cache_key(cache_dir, monkeypatch):
    monkeypatch.setattr(pdf_text.httpx, "get", lambda url, **kw: _Resp(b"%PDF-1"))
    calls = {"n": 0}

    def _extract(pdf_bytes):
        calls["n"] += 1
        return "Ein Gesetzestext."

    monkeypatch.setattr(pdf_text, "extract_text", _extract)

    url = "https://example.org/btd/21/069/2106916.pdf"
    assert pdf_text.get_text(url, cache_key="hash-a") == "Ein Gesetzestext."
    assert pdf_text.get_text(url, cache_key="hash-a") == "Ein Gesetzestext."
    assert calls["n"] == 1  # second call served from the .txt sidecar
    assert (cache_dir / "hash-a-2106916.pdf.txt").exists()


def test_get_text_changed_pdf_hash_reextracts(cache_dir, monkeypatch):
    responses = iter([_Resp(b"old"), _Resp(b"new")])
    monkeypatch.setattr(pdf_text.httpx, "get", lambda url, **kw: next(responses))
    monkeypatch.setattr(pdf_text, "extract_text", lambda b: b.decode())

    url = "https://example.org/2106916.pdf"
    assert pdf_text.get_text(url, cache_key="hash-old") == "old"
    # DIP reports a new pdf_hash for the same URL -> fresh extraction.
    assert pdf_text.get_text(url, cache_key="hash-new") == "new"


def test_get_text_cache_disabled_via_empty_dir(monkeypatch):
    monkeypatch.setattr(config, "PDF_CACHE_DIR", "")
    monkeypatch.setattr(pdf_text.httpx, "get", lambda url, **kw: _Resp(b"%PDF-1"))
    calls = {"n": 0}

    def _extract(pdf_bytes):
        calls["n"] += 1
        return "Text"

    monkeypatch.setattr(pdf_text, "extract_text", _extract)

    url = "https://example.org/2106916.pdf"
    pdf_text.get_text(url)
    pdf_text.get_text(url)
    assert calls["n"] == 2  # no caching


def test_non_200_raises_and_writes_no_cache(cache_dir, monkeypatch):
    monkeypatch.setattr(pdf_text.httpx, "get", lambda url, **kw: _Resp(b"", 404))
    with pytest.raises(RuntimeError, match="404"):
        pdf_text.download_pdf("https://example.org/missing.pdf", cache_key="h")
    assert not cache_dir.exists() or not any(cache_dir.iterdir())
