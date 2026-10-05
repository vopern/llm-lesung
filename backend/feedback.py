"""Reader feedback on findings and exploits, as append-only JSONL.

One file per calendar month (UTC) in ``FEEDBACK_DIR``, e.g. ``2026-10.jsonl``;
no file is ever rewritten or deleted. The database is replaced wholesale by
uploads, so feedback lives beside it, not in it.
"""

import json
import os
import threading
from datetime import datetime, timezone

from backend import config

# Longest free text a record may carry.
MAX_TEXT_CHARS = 2000

# A month's file stops growing here, so feedback can never fill the disk.
MAX_FILE_BYTES = 20 * 1024 * 1024

_lock = threading.Lock()


def append(record: dict) -> bool:
    """Append ``record`` with an ``at`` timestamp to this month's file.

    Returns ``False``, writing nothing, when the file has reached ``MAX_FILE_BYTES``.
    """
    now = datetime.now(timezone.utc)
    line = json.dumps({"at": now.isoformat(timespec="seconds"), **record}, ensure_ascii=False)
    path = os.path.join(config.FEEDBACK_DIR, f"{now:%Y-%m}.jsonl")
    with _lock:
        os.makedirs(config.FEEDBACK_DIR, exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) >= MAX_FILE_BYTES:
            return False
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return True
