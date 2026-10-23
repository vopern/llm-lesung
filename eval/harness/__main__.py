"""Entry point: ``python -m eval.harness <run|report|html|select>``.

``run`` costs money (one call per document); ``report`` and ``html`` are
offline. ``--task lektor|exploit`` picks the pass. ``select`` scores the
Bestandsrecht selection (one cheap call per document not yet sampled).
"""

import sys

from . import html, report, run, selection

_COMMANDS = {"run": run.main, "report": report.main, "html": html.main,
             "select": selection.main}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in _COMMANDS:
        print(f"usage: python -m eval.harness {{{'|'.join(_COMMANDS)}}} [options]")
        return 2
    return _COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
