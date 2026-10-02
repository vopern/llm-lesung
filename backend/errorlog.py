"""Per-run error log for the pipeline.

Every pipeline run writes ``errors.jsonl`` into its run folder under
``config.PIPELINE_RUNS_DIR`` so failed and retried bills can be analyzed
later. One line per failed attempt — both attempts that will be retried and
attempts that hit the final threshold — with the phase, attempt counter,
full traceback and, for a failed Claude call, its per-turn attempts.

The file is created lazily on the first record, so error-free runs leave no
empty files behind. ``record()`` is thread-safe; the pipeline's worker threads
call it directly.
"""

import json
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path


class ErrorLog:
    """Append-only JSONL error log for one pipeline run."""

    def __init__(self, run_dir: str | Path):
        self._lock = threading.Lock()
        self.count = 0
        self.path = Path(run_dir) / "errors.jsonl"

    def record(
        self,
        bill: dict,
        phase: str,
        attempt: int,
        max_attempts: int,
        error: BaseException,
    ) -> None:
        """Append one failed attempt. ``attempt`` is 1-based."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "bill_id": bill.get("id"),
            "dokumentnummer": bill.get("dokumentnummer"),
            "titel": bill.get("titel"),
            "phase": phase,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "final": attempt >= max_attempts,
            "error_type": type(error).__name__,
            "error": str(error),
            "traceback": "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            ),
        }
        # A failed Claude call (``StructuredOutputError``) carries what each
        # turn sent and why it was rejected.
        for key in ("session_id", "attempts"):
            if getattr(error, key, None) is not None:
                entry[key] = getattr(error, key)
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            self.count += 1
