"""Paths and settings for the eval harness.

Project convention: env vars only, all optional. Model, effort and prompt
version come from ``backend.config`` through the task, so a run measures what
the pass ships.
"""

import os
from pathlib import Path

EVAL_DIR = Path(os.environ.get("EVAL_DIR", "./data/eval"))

# Parallel calls; every one is a paid Claude call.
CONCURRENCY = int(os.environ.get("EVAL_CONCURRENCY", "4"))

# The Agent SDK's reasoning-effort levels.
EFFORTS = ["low", "medium", "high", "xhigh", "max"]


def default_tag(task, model: str, effort: str | None = None,
                max_turns: int | None = None, oracle: bool = False,
                committee: bool = False) -> str:
    """Prompt version, model, effort, turn limit and input set: a run directory never mixes them.

    The task's own turn limit adds nothing to the name; neither does the draft
    alone, so its samples serve every context run on the same settings.
    """
    tag = f"{task.prompt_version}-{model}"
    if effort is not None:
        tag += f"-effort-{effort}"
    if max_turns not in (None, task.max_turns):
        tag += f"-turns-{max_turns}"
    if oracle:
        tag += "-oracle-bestandsrecht"
    if committee:
        tag += "-beschlussempfehlung"
    return tag


def run_dir(task: str, tag: str) -> Path:
    return EVAL_DIR / "runs" / f"{task}-{tag}"
