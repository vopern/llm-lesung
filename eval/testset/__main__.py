"""Entry point: ``python -m eval.testset <fetch|lint|export|score>``.

``fetch`` downloads the pinned texts; the rest are free and offline. ``score db``
reads the database, ``score redteam`` the run artefacts under ``data/redteam/out/``.
"""

import sys

from . import export, fetch, lint, score

_COMMANDS = {
    "fetch": fetch.main,
    "lint": lint.main,
    "export": export.main,
    "score": score.main,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in _COMMANDS:
        print(f"usage: python -m eval.testset {{{'|'.join(_COMMANDS)}}} [options]")
        return 2
    return _COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
