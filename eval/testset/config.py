"""Paths and thresholds for the test-set tools.

Project convention: env vars only, all optional. The YAML is version-controlled
next to this file, the pinned texts are fetched into ``texts/`` (gitignored) by
``fetch``; everything derived from them lands in ``data/`` (gitignored) next to
the other evaluation output.
"""

import os
from pathlib import Path

OUT_DIR = Path(os.environ.get("TESTSET_OUT_DIR", "./data/testset"))

# One JSONL file per suite and split, the layout ``datasets.load_dataset("json")``
# and Inspect's ``json_dataset`` read without a mapping.
EXPORT_DIR = OUT_DIR / "export"

# How far, in squashed characters, a finding's quote may sit from a case's
# anchor and still count as ``near``. Anchors are clause-length pointers into a
# provision the defect spans; 300 squashed characters is roughly the rest of
# the Absatz, short of the next paragraph.
NEAR_CHARS = int(os.environ.get("TESTSET_NEAR_CHARS", "300"))

# A non-verbatim quote is placed by its longest grounded run only if that run is
# at least clause length; anything shorter is a coincidental match.
MIN_PARTIAL_CHARS = 40


def score_path(source: str) -> Path:
    return OUT_DIR / f"score-{source}.json"
