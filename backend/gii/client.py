"""Downloads from GII, cached under ``config.GII_DIR``.

A law's ``xml.zip`` is kept as ``zips/<slug>.zip`` and fetched again only with
``refresh``. Non-200 responses raise ``RuntimeError``.
"""

import os
import threading
from pathlib import Path

import httpx

from backend import config
from backend.gii import BASE_URL

_TIMEOUT = 60.0


def get(path: str) -> bytes:
    resp = httpx.get(f"{BASE_URL}/{path}", timeout=_TIMEOUT, follow_redirects=True)
    if resp.status_code != 200:
        raise RuntimeError(f"GII {path}: HTTP {resp.status_code}")
    return resp.content


def zip_path(slug: str, refresh: bool = False) -> Path:
    """The cached ``xml.zip`` of the law ``slug``, downloaded when missing."""
    path = Path(config.GII_DIR) / "zips" / f"{slug}.zip"
    if refresh or not path.exists():
        data = get(f"{slug}/xml.zip")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Own name per writer: parallel resolutions may fetch the same law.
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.part")
        tmp.write_bytes(data)
        tmp.replace(path)
    return path
