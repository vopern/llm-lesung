"""Export the test set as one sample per document, in JSONL.

The YAML stays the source: one record per expectation, hand-edited, commented.
A run reads a document, not an expectation, so every framework wants the
opposite shape — ``input`` is the draft, ``target`` everything expected of it.
This builds that shape; nothing reads it back.

Sample fields follow Inspect AI's ``Sample`` (``id``, ``input``, ``target``,
``metadata``), so ``json_dataset`` loads a file without a record mapping, and
the ``<suite>/<split>.jsonl`` layout is what a Hugging Face dataset repo uses
for configs and splits.

    uv run python -m eval.testset export
"""

import argparse
import json
from pathlib import Path

from . import config
from .lint import CANARY, PATHS, PREFIX, TEXTS, documents, load

# Held per document, so a sample carries them once instead of per case.
DOC_FIELDS = ("suite", "doc", "drucksachetyp", "text", "split")


def sample(suite: str, file: str, cases: list[dict], text: str) -> dict:
    """One document with every expectation on it."""
    first = cases[0]
    return {
        "id": PREFIX[suite] + file.removesuffix(".txt"),
        "input": text,
        # What a grader compares against. Negative and inverse cases have no
        # target: what they score is the ``forbidden_claim`` in the metadata.
        "target": [c["expected_defect"] for c in cases if c["kind"] == "positiv"],
        "metadata": {
            "suite": suite,
            "doc": first["doc"],
            "drucksachetyp": first["drucksachetyp"],
            "split": first["split"],
            "text_file": file,
            "text_sha256": first["text"]["sha256"],
            "canary": CANARY,
            "cases": [{k: v for k, v in c.items() if k not in DOC_FIELDS} for c in cases],
        },
    }


def build(cases: list[dict], texts: Path = TEXTS) -> dict[tuple[str, str], list[dict]]:
    """Samples keyed by ``(suite, split)``, in YAML order."""
    out: dict[tuple[str, str], list[dict]] = {}
    for (suite, file), group in documents(cases).items():
        text = (texts / file).read_text(encoding="utf-8")
        out.setdefault((suite, group[0]["split"]), []).append(sample(suite, file, group, text))
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eval.testset export",
        description="Write one JSONL sample per document. Offline, free.",
    )
    parser.add_argument("--out", type=Path, default=config.EXPORT_DIR)
    args = parser.parse_args(argv)

    cases = [c for path in PATHS for c in load(path)]
    for (suite, split), samples in sorted(build(cases).items()):
        path = args.out / suite / f"{split}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for s in samples:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        n_cases = sum(len(s["metadata"]["cases"]) for s in samples)
        print(f"{path}: {len(samples)} documents, {n_cases} cases")
    return 0
