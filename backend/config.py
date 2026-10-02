"""Configuration and constants for LLM-Lesung.

Loads a `.env` file (if present) via python-dotenv and exposes the settings
the rest of the backend depends on. Every value can be overridden through an
environment variable so deployments never need code changes.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# --- Claude / analysis ------------------------------------------------------
# The analyzer runs via the Claude Agent SDK, which authenticates like Claude
# Code: the local `claude login` (subscription) credentials by default, or
# ANTHROPIC_API_KEY / CLAUDE_CODE_OAUTH_TOKEN from the environment if set.
# No key is read here; the SDK's bundled CLI resolves credentials itself.

# Model used by the analyzer; overridable for cheaper/experimental runs.
ANALYSIS_MODEL = os.environ.get("ANALYSIS_MODEL", "claude-sonnet-5")

# Reasoning effort of the analysis call (low, medium, high, xhigh, max). Set
# explicitly because the model's default depends on the model and on the CLI.
ANALYSIS_EFFORT = os.environ.get("ANALYSIS_EFFORT", "high")

# Versioned prompt tag stored with every analysis so results stay interpretable
# as the prompt evolves.
PROMPT_VERSION = "v7"

# Model of the rescue call that transcribes a response the schema rejected
# (backend/analysis/structured.py). It copies text, and its result is checked
# verbatim against the response, so a cheaper model is safe.
RESCUE_MODEL = os.environ.get("RESCUE_MODEL", "claude-sonnet-5")

# --- Red team (docs/REDTEAM.md) ---------------------------------------------
# The adversarial second pass runs its own call with its own prompt, so it
# versions independently: iterating the attack prompt must not invalidate the
# stored Lektor analyses. Defaults to the analysis model.
REDTEAM_MODEL = os.environ.get("REDTEAM_MODEL", ANALYSIS_MODEL)

# Reasoning effort of the red-team call; defaults to the analysis effort.
REDTEAM_EFFORT = os.environ.get("REDTEAM_EFFORT", ANALYSIS_EFFORT)

# Versioned tag of the adversarial prompt, stored with every red-team result.
REDTEAM_PROMPT_VERSION = "v5"

# How many bills the pipeline analyzes concurrently. All SQLite writes stay on
# the main thread; workers only do network I/O and the Claude call.
PIPELINE_CONCURRENCY = int(os.environ.get("PIPELINE_CONCURRENCY", "10"))

# How often a bill's processing is attempted per run before giving up.
PIPELINE_MAX_ATTEMPTS = int(os.environ.get("PIPELINE_MAX_ATTEMPTS", "2"))

# --- Storage ----------------------------------------------------------------
# Path to the SQLite database file.
DB_PATH = os.environ.get("LLM_LESUNG_DB", "./data/llm-lesung.db")

# Directory for cached Drucksache PDFs (set empty to disable caching).
PDF_CACHE_DIR = os.environ.get("PDF_CACHE_DIR", "./data/pdf-cache")

# One folder per pipeline run, named by its UTC start: ``errors.jsonl`` (failed
# attempts) and ``traces/`` (the message stream of every Claude call).
PIPELINE_RUNS_DIR = os.environ.get("PIPELINE_RUNS_DIR", "./data/pipeline/runs")

# Folder of HTML evaluation reports the website lists and serves; whatever is in
# it is published. In production a symlink to the release `make push-eval` swapped in.
EVAL_PUBLIC_DIR = os.environ.get("EVAL_PUBLIC_DIR", "./data/eval-public")

# --- Website ----------------------------------------------------------------
# Contact address shown on the About page; empty hides the contact section.
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "").strip()

# --- DIP (Bundestag Dokumentations- und Informationssystem) -----------------
# Public portal API key. Referer-locked (see DIP_HEADERS). Rotates ~yearly;
# re-scrape from https://dip.bundestag.de/dip-config.js if it stops working.
DIP_API_KEY = os.environ.get(
    "DIP_API_KEY", "SbGXhWA.3cpnNdb8rkht7iWpvSgTP8XIG88LoCrGd4"
)

# Base URL for the DIP search API (v1).
DIP_BASE_URL = "https://search.dip.bundestag.de/api/v1"


def dip_headers() -> dict[str, str]:
    """Headers required on EVERY DIP request.

    The public key is referer-locked: without the Referer header the API
    returns 401.
    """
    return {
        "Authorization": f"ApiKey {DIP_API_KEY}",
        "Referer": "https://dip.bundestag.de/",
    }
