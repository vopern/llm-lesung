"""Recreate the pinned texts in ``texts/`` from the public Drucksache PDFs.

Every ``{file, sha256}`` pin in the case files and ``inputs.yaml`` (drafts and
Beschlussempfehlungen) names a Drucksache by its file name (``21-1497.txt`` is
BT-Drs. 21/1497). Its PDF is
downloaded from dserver.bundestag.de, extracted with the pipeline's own
``extract_text`` and written only if the result matches the pinned hash. A file
already present with the right hash is left alone.

    uv run python -m eval.testset fetch
"""

import argparse
import hashlib
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from backend.dip.pdf_text import extract_text

from .lint import MANIFEST, PATHS, TEXTS, load, load_manifest, sha256

_TIMEOUT = 60.0
_FILE = re.compile(r"(\d{1,2})-(\d{1,5})\.txt")


def pdf_url(file: str) -> str:
    """dserver URL of the Drucksache a text file is named after."""
    m = _FILE.fullmatch(Path(file).name)
    if not m:
        raise ValueError(f"{file}: not a Drucksache file name like 21-1497.txt")
    wp, nr = m.group(1), int(m.group(2))
    return f"https://dserver.bundestag.de/btd/{wp}/{nr // 100:03d}/{wp}{nr:05d}.pdf"


def pins(cases: list[dict], manifest: dict[str, dict]) -> dict[str, str]:
    """Pinned sha256 per text file; a file pinned to two hashes raises."""
    found: dict[str, str] = {}
    texts = [c.get("text") for c in cases]
    for entry in manifest.values():
        if isinstance(entry, dict):
            texts += [entry.get("gesetzentwurf"), *(entry.get("beschlussempfehlungen") or [])]
    for text in texts:
        if not isinstance(text, dict):
            continue
        file, digest = text["file"], text["sha256"]
        if found.setdefault(file, digest) != digest:
            raise ValueError(f"{file}: pinned to two different hashes")
    return found


def fetch(file: str, digest: str, texts: Path) -> str | None:
    """Download and extract one text; the problem as a message, or None."""
    url = pdf_url(file)
    try:
        resp = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True)
    except httpx.HTTPError as exc:
        return f"{file}: GET {url} failed: {exc}"
    if resp.status_code != 200:
        return f"{file}: GET {url} -> {resp.status_code}"
    data = extract_text(resp.content).encode("utf-8")
    if hashlib.sha256(data).hexdigest() != digest:
        return f"{file}: extracted text does not match the pinned sha256"
    path = texts / file
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp-{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.testset fetch")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)

    cases = [case for path in PATHS for case in load(path)]
    wanted = pins(cases, load_manifest(MANIFEST))
    TEXTS.mkdir(exist_ok=True)
    todo = {f: d for f, d in sorted(wanted.items())
            if not (TEXTS / f).is_file() or sha256(TEXTS / f) != d}
    with ThreadPoolExecutor(args.workers) as pool:
        errors = [e for e in pool.map(lambda f: fetch(f, todo[f], TEXTS), todo) if e]
    for e in errors:
        print(e)
    print(f"{len(wanted)} pinned, {len(todo) - len(errors)} fetched, {len(errors)} errors")
    return 1 if errors else 0
