"""Run the test set against a model through the Claude CLI.

One ``claude -p`` subprocess per item, so every item is an independent session
with no memory of the previous one. The CLI is pinned down deliberately:

* ``--system-prompt``      replaces the Claude Code system prompt entirely
* ``--disallowed-tools``   no WebSearch/WebFetch/Bash/Read — the "no lookup"
                           rule of the eval, enforced rather than requested
* ``--setting-sources ""`` and a cwd outside the repo, so no CLAUDE.md, no
                           project settings and no memory leak into the answer
* ``--strict-mcp-config``  no MCP servers

Results are appended to a JSONL file as they arrive; re-running skips ids that
are already there, so an interrupted run resumes.
"""

import argparse
import json
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config
from .dataset import SYSTEM_PROMPT_ABSTAIN, SYSTEM_PROMPT_FORCED

_BLOCKED_TOOLS = [
    "WebSearch", "WebFetch", "Bash", "Read", "Glob", "Grep",
    "Edit", "Write", "NotebookEdit", "Task", "TodoWrite",
]


def _command(prompt: str, model: str, system_prompt: str) -> list[str]:
    return [
        "claude", "-p", prompt,
        "--model", model,
        "--system-prompt", system_prompt,
        "--exclude-dynamic-system-prompt-sections",
        "--disallowed-tools", *_BLOCKED_TOOLS,
        "--strict-mcp-config",
        "--setting-sources", "",
        "--output-format", "json",
    ]


def ask(item: dict, model: str, system_prompt: str, cwd: str) -> dict:
    """Ask one item and return the raw record (never raises)."""
    started = time.monotonic()
    record = {
        "id": item["id"],
        "kind": item["kind"],
        "model": model,
        "raw": "",
        "error": None,
        "cost_usd": 0.0,
        "seconds": 0.0,
    }
    try:
        completed = subprocess.run(
            _command(item["prompt"], model, system_prompt),
            capture_output=True,
            text=True,
            timeout=config.GG_TIMEOUT,
            cwd=cwd,
        )
        if completed.returncode != 0:
            record["error"] = (completed.stderr or "").strip()[:500] or "non-zero exit"
        else:
            payload = json.loads(completed.stdout)
            record["raw"] = payload.get("result", "") or ""
            record["cost_usd"] = float(payload.get("total_cost_usd") or 0.0)
            if payload.get("is_error"):
                record["error"] = str(payload.get("subtype") or "cli error")
    except subprocess.TimeoutExpired:
        record["error"] = f"timeout after {config.GG_TIMEOUT}s"
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["seconds"] = round(time.monotonic() - started, 2)
    return record


def stratified_slice(items: list[dict], limit: int) -> list[dict]:
    """Take ``limit`` items round-robin across kind x stratum.

    A plain head slice would return 12 trap items and no ``zitat`` at all,
    because the set is sorted by id. A limited run has to stay representative
    or its numbers cannot be compared to a full one.
    """
    buckets: dict[tuple[str, str], list[dict]] = {}
    for item in items:
        buckets.setdefault((item["kind"], item["stratum"]), []).append(item)
    order = sorted(buckets)
    picked: list[dict] = []
    for index in range(max(len(b) for b in buckets.values())):
        for key in order:
            if index < len(buckets[key]):
                picked.append(buckets[key][index])
                if len(picked) == limit:
                    return sorted(picked, key=lambda i: i["id"])
    return sorted(picked, key=lambda i: i["id"])


def load_testset(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _already_done(path: Path) -> set[str]:
    if not path.exists():
        return set()
    done = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                if not record.get("error"):
                    done.add(record["id"])
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the GG-recall eval")
    parser.add_argument("--model", default=config.GG_MODEL)
    parser.add_argument("--tag", default=None, help="output tag (default: model)")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="N items, sampled evenly across kind and stratum",
    )
    parser.add_argument("--concurrency", type=int, default=config.GG_CONCURRENCY)
    parser.add_argument(
        "--abstention",
        choices=["on", "off"],
        default="on",
        help="on: the model may answer UNBEKANNT; off: it must always guess",
    )
    args = parser.parse_args(argv)

    tag = args.tag or f"{args.model}-{args.abstention}"
    out_path = config.responses_path(tag)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    items = load_testset(config.TESTSET)
    if args.limit:
        items = stratified_slice(items, args.limit)
    done = _already_done(out_path)
    pending = [i for i in items if i["id"] not in done]
    if not pending:
        print(f"{out_path}: nothing to do ({len(done)} answers present)")
        return 0

    system_prompt = (
        SYSTEM_PROMPT_ABSTAIN if args.abstention == "on" else SYSTEM_PROMPT_FORCED
    )
    print(
        f"{len(pending)} items -> {args.model} "
        f"(abstention {args.abstention}, {args.concurrency} parallel)"
    )

    # A cwd outside the repo keeps CLAUDE.md and project settings out of the
    # model's context; the eval must measure memory, not retrieval.
    with tempfile.TemporaryDirectory(prefix="gg-eval-") as cwd:
        with out_path.open("a", encoding="utf-8") as handle:
            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                futures = [
                    pool.submit(ask, item, args.model, system_prompt, cwd)
                    for item in pending
                ]
                for number, future in enumerate(futures, start=1):
                    record = future.result()
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    handle.flush()
                    flag = "!" if record["error"] else " "
                    print(f"  [{number}/{len(pending)}]{flag} {record['id']}", flush=True)

    print(f"{out_path}: written")
    return 0
