"""Entry point: ``python -m eval.gg <fetch|build|run|score|report>``."""

import sys

from . import dataset, fetch, report, run, score

_COMMANDS = {
    "fetch": fetch.main,
    "build": dataset.main,
    "run": run.main,
    "score": score.main,
    "report": report.main,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in _COMMANDS:
        print(f"usage: python -m eval.gg {{{'|'.join(_COMMANDS)}}} [options]")
        return 2
    return _COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
