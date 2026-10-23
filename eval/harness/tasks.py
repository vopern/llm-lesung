"""The two passes the harness runs: the Lektor and the red-team pass.

A task names everything that differs between them — the case files, the call,
the prompt version, the default model and effort, and how the pass's output
becomes the ``category`` / ``severity`` / ``title`` / ``description`` / ``quote``
findings the scorer and the report read. Everything else — inputs, splits,
samples, traces, scoring, the report — is shared.
"""

from collections.abc import Callable
from dataclasses import dataclass
from types import ModuleType

from backend import config as backend_config
from backend.analysis import analyzer, redteam
from backend.analysis.schema import Finding, Severity
from eval.testset.lint import FILES

SEVERITY_ORDER = ["niedrig", "mittel", "hoch"]


@dataclass(frozen=True)
class Task:
    name: str  # also the testset suite and the run directory prefix
    # Case set name -> YAML file; the first is the default.
    case_sets: dict
    prompt_version: str
    model: str
    effort: str
    # The pass's module: ``build_message``, ``run_query`` and ``MAX_TURNS`` are
    # looked up on it at call time, the functions the pass ships with.
    module: ModuleType
    findings: Callable[[dict], list[dict]]  # the stored analysis -> findings
    risk: Callable[[dict], Severity | None]  # the stored analysis -> severity
    # An unanchored negative means the draft offers nothing to find, so any
    # finding on it is a false alarm (``testset.score.score_case``).
    quiet_negatives: bool

    @property
    def default_cases(self) -> str:
        return next(iter(self.case_sets))

    @property
    def max_turns(self) -> int:
        return self.module.MAX_TURNS


def _lektor_findings(analysis: dict) -> list[dict]:
    return analysis["findings"]


def _lektor_risk(analysis: dict) -> Severity:
    return analyzer.derive_risk([Finding(**f) for f in analysis["findings"]])


def _exploit_description(e: dict) -> str:
    steps = " ".join(f"({i}) {s}" for i, s in enumerate(e["schritte"], 1))
    return (f"Akteur: {e['akteur']} Schritte: {steps} Vorteil: {e['vorteil']} "
            f"Aufwand: {e['aufwand']}. Fehlende Absicherung: {e['fehlende_absicherung']}")


def _exploit_findings(analysis: dict) -> list[dict]:
    return [{"category": e["muster"], "severity": e["severity"], "title": e["titel"],
             "description": _exploit_description(e), "quote": e["quote"]}
            for e in analysis["exploits"]]


def _exploit_risk(analysis: dict) -> Severity | None:
    """The highest exploit severity; ``None`` when nothing was reported."""
    found = [e["severity"] for e in analysis["exploits"]]
    return max(found, key=SEVERITY_ORDER.index) if found else None


def _case_sets(suite: str, prefix: str) -> dict:
    """``cases-lektor-beschlussempfehlungen.yaml`` -> ``beschlussempfehlungen``."""
    sets = {path.stem.removeprefix(prefix).lstrip("-") or suite: path for path in FILES[suite]}
    # The committee-repair file first: it is the Lektor's default.
    return dict(sorted(sets.items(), key=lambda kv: kv[0] == suite))


TASKS = {
    "lektor": Task(
        name="lektor",
        case_sets=_case_sets("lektor", "cases-lektor"),
        prompt_version=backend_config.PROMPT_VERSION,
        model=backend_config.ANALYSIS_MODEL, effort=backend_config.ANALYSIS_EFFORT,
        module=analyzer, findings=_lektor_findings, risk=_lektor_risk, quiet_negatives=False),
    "exploit": Task(
        name="exploit",
        case_sets=_case_sets("exploit", "cases-exploit"),
        prompt_version=backend_config.REDTEAM_PROMPT_VERSION,
        model=backend_config.REDTEAM_MODEL, effort=backend_config.REDTEAM_EFFORT,
        module=redteam, findings=_exploit_findings, risk=_exploit_risk, quiet_negatives=True),
}


def get(name: str) -> Task:
    return TASKS[name]
