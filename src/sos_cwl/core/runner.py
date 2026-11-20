"""`sos-cwl-runner`: unmodified cwltool with the hooks of all installed extensions.

Extensions are found through the entry point group `sos_cwl.extensions` (see pyproject.toml), so
the core does not import them. Every cwltool flag works as usual; each extension adds its own.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, entry_points, version
from pathlib import Path

import cwltool.main
from cwltool.argparser import arg_parser
from cwltool.context import LoadingContext
from packaging.requirements import Requirement

from .extension import Extension, UsageError
from .tool import Runtime
from .trace import RunInfo, Trace

ENTRY_POINT_GROUP = "sos_cwl.extensions"

# The core's own dependencies; each extension's distribution and its requirements are added at run time.
CORE_PACKAGES = ("cwltool", "cwl-utils", "schema-salad")


def load_extensions() -> list[Extension]:
    """One instance of every installed extension, in entry point name order."""
    return [ep.load()() for ep in sorted(entry_points(group=ENTRY_POINT_GROUP), key=lambda ep: ep.name)]


def parse_args(argv: Sequence[str], extensions: Sequence[Extension]) -> tuple[argparse.Namespace, list[str]]:
    """cwltool's arguments plus the core's and every extension's group, configured; also the destinations of the
    core's and the extensions' arguments, for the run record."""
    parser = arg_parser()
    parser.prog = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "sos-cwl-runner"
    core = parser.add_argument_group("SOS runner")
    core.add_argument(
        "--trace",
        metavar="FILE.jsonl",
        default=None,
        help="Append a trace of the run: environment, arguments, job and hook durations, and the extensions' "
        "observations (one JSON object per line).",
    )
    core.add_argument("--run-id", default=None, help="Run id written to every trace record (default: random).")
    groups = [core]
    for ext in extensions:
        groups.append(parser.add_argument_group(ext.group_title))
        ext.add_arguments(groups[-1])
    addl = [x for x in os.environ.get("CWLTOOL_OPTIONS", "").split(" ") if x]
    args = parser.parse_args(addl + list(argv))
    # What cwltool.main.main does after parsing; it skips that when given parsed `args`.
    if args.record_container_id:
        if not args.cidfile_dir:
            args.cidfile_dir = os.getcwd()
        del args.record_container_id
    for ext in extensions:
        try:
            ext.configure(args)
        except UsageError as exc:
            parser.error(f"{ext.name}: {exc}")
    return args, [a.dest for g in groups for a in g._group_actions]


def package_versions(extensions: Sequence[Extension]) -> dict[str, str | None]:
    """The core's packages, plus every extension's distribution and its requirements."""
    names = list(CORE_PACKAGES)
    classes = {type(ext) for ext in extensions}
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        if ep.dist is not None and ep.load() in classes:
            names.append(ep.dist.name)
            requirements = [Requirement(r) for r in ep.dist.requires or []]
            names += [r.name for r in requirements if r.marker is None or r.marker.evaluate({"extra": ""})]
    versions: dict[str, str | None] = {}
    for name in dict.fromkeys(names):  # deduplicated, in order
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = None
    return versions


def main(argv: Sequence[str] | None = None, extensions: Sequence[Extension] | None = None) -> int:
    extensions = load_extensions() if extensions is None else list(extensions)
    args, recorded = parse_args(sys.argv[1:] if argv is None else argv, extensions)
    run = RunInfo(
        versions=package_versions(extensions),
        extensions=[ext.name for ext in extensions],
        arguments={dest: getattr(args, dest) for dest in recorded},
    )
    trace = Trace(args.trace, run, args.run_id)
    with contextlib.ExitStack() as cleanup:  # closes in reverse: every extension, then the trace
        cleanup.callback(trace.close)
        for ext in extensions:
            cleanup.callback(ext.close)
        runtime = Runtime(extensions, trace)
        loading_context = LoadingContext(vars(args))
        loading_context.construct_tool_object = runtime.make_tool
        return cwltool.main.main(args=args, loadingContext=loading_context)


if __name__ == "__main__":
    sys.exit(main())
