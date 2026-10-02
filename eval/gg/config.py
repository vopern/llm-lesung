"""Paths and settings for the GG-recall eval.

Follows the project convention: env vars only, all optional. Outputs land in
``data/gg/`` (``data/`` is gitignored) next to the other evaluation artefacts.
"""

import os
from pathlib import Path

# Official consolidated XML of the Grundgesetz (juris/BMJ, public domain).
GG_XML_URL = os.environ.get(
    "GG_XML_URL", "https://www.gesetze-im-internet.de/gg/xml.zip"
)

# Where the parsed GG, the test set and every run's artefacts are written.
GG_DATA_DIR = Path(os.environ.get("GG_DATA_DIR", "./data/gg"))

GG_JSON = GG_DATA_DIR / "gg.json"
TESTSET = GG_DATA_DIR / "testset.jsonl"

# Cached Drucksache texts, used to weight articles by how often real bills cite
# them (see dataset.py). Shared with the pipeline's PDF cache.
PDF_CACHE_DIR = Path(os.environ.get("PDF_CACHE_DIR", "./data/pdf-cache"))

# Model under test. Any id the Claude CLI accepts.
GG_MODEL = os.environ.get("GG_MODEL", "claude-sonnet-5")

# Parallel `claude -p` subprocesses and the per-call timeout in seconds.
GG_CONCURRENCY = int(os.environ.get("GG_CONCURRENCY", "4"))
GG_TIMEOUT = float(os.environ.get("GG_TIMEOUT", "180"))


def responses_path(tag: str) -> Path:
    return GG_DATA_DIR / f"responses-{tag}.jsonl"


def score_path(tag: str) -> Path:
    return GG_DATA_DIR / f"score-{tag}.json"


def report_path(tag: str) -> Path:
    return GG_DATA_DIR / f"report-{tag}.html"
