"""`sos-cwl-lint`: design-time checks of all installed extensions on CWL documents."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from .extension import Extension, Severity
from .runner import load_extensions


def main(argv: Sequence[str] | None = None, extensions: Sequence[Extension] | None = None) -> int:
    extensions = load_extensions() if extensions is None else list(extensions)
    names = [ext.name for ext in extensions]
    parser = argparse.ArgumentParser(prog="sos-cwl-lint", description=__doc__)
    parser.add_argument("documents", nargs="+", help="CWL tools or workflows")
    parser.add_argument(
        "--extension",
        action="append",
        choices=names,
        help="Run only these extensions' checks; repeatable (default: all).",
    )
    parser.add_argument("--strict", action="store_true", help="Exit 1 on warnings too.")
    for ext in extensions:
        ext.add_lint_arguments(parser.add_argument_group(ext.group_title))
    args = parser.parse_args(argv)
    for name in ("cwltool", "salad"):
        logging.getLogger(name).setLevel(logging.ERROR)
    # enable all if no `--extension` specified
    selected = [ext for ext in extensions if not args.extension or ext.name in args.extension]
    counts = dict.fromkeys(Severity, 0)
    for document in args.documents:
        for ext in selected:
            result = ext.lint(document, args)
            if not result.lines and not result.findings:
                continue
            print(f"[{ext.name}] {document}")
            for line in result.lines:
                print(f"  {line}")
            for f in result.findings:
                print(f"  {f.severity:8}{f.location}: {f.message}")
                counts[f.severity] += 1
    print(", ".join(f"{n} {s}(s)" for s, n in counts.items()))
    return 1 if counts[Severity.ERROR] or (args.strict and counts[Severity.WARNING]) else 0


if __name__ == "__main__":
    sys.exit(main())
