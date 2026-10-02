"""Entry point: ``python -m eval.harness <run|report|html>``.

``run`` costs money (one call per document); ``report`` and ``html`` are
offline. ``--task lektor|angreifer`` picks the pass.
"""

import sys

from . import html, report, run

_COMMANDS = {"run": run.main, "report": report.main, "html": html.main}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in _COMMANDS:
        print(f"usage: python -m eval.harness {{{'|'.join(_COMMANDS)}}} [options]")
        return 2
    return _COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
