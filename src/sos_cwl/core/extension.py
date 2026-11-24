"""The interface between the core (cwltool hooks, CLIs, run trace) and an extension.

An extension subclasses `Extension` and overrides what it needs. The core calls, per run:

    add_arguments(group)                 while building cwltool's argument parser
    configure(args)                      after parsing; set up clients, policies, ...
    on_tool(tool)                        for every CommandLineTool cwltool constructs (load time)
    before_job(ctx) -> Verdict           for every job, before its command runs
    after_job(ctx, outputs) -> Verdict   for every job, after its outputs are collected (if `wants_outputs`)
    close()                              when cwltool is done

and, for `sos-cwl-lint`, `add_lint_arguments(group)` and `lint(document, args)`.

The core creates one argument group per extension, titled `title` (or `name`), and passes it to both
`add_arguments` and `add_lint_arguments`.

`Verdict.fail(...)` from `before_job` ends the step `permanentFail` without running its command;
from `after_job` it fails the step after the command ran. Only `active` extensions are called per
job, so an inactive extension costs nothing at run time.

The core records the run itself (environment, versions, every extension's arguments, command and hook durations);
an extension adds its own observations of a job with `ctx.record(...)`.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

from .files import default_resolve
from .trace import Trace

if TYPE_CHECKING:
    from cwltool.command_line_tool import CommandLineTool
    from cwltool.job import JobBase


@dataclass
class JobContext:
    """One cwltool job, as an extension sees it."""

    tool: CommandLineTool
    job: JobBase
    step: str  # workflow step id (or the tool's id when run directly)
    _trace: Trace = field(repr=False)  # core-internal; extensions use record()

    @property
    def name(self) -> str:
        """cwltool's unique job name (`_2`, `_3`, ... for scatter elements)."""
        return self.job.name

    @property
    def inputs(self) -> Mapping[str, Any]:
        """Bound input values by short port name."""
        return self.job.builder.job

    def resolve(self, location: str) -> str:
        """Host path (or URL) of a File location, also for staged and containerised jobs."""
        try:
            return self.job.pathmapper.mapper(location).resolved
        except KeyError:
            return default_resolve(location)

    def record(self, kind: str, **fields: Any) -> None:
        """Add an observation of this job to the run trace (with `step` and `job`); a no-op without `--trace`."""
        self._trace.write(kind, step=self.step, job=self.name, **fields)


class UsageError(Exception):
    """Invalid arguments, found in `configure`; reported like an argparse error (exit code 2)."""


@dataclass(frozen=True)
class Verdict:
    """An extension's decision on a job: let it go on, or fail the step for the given reasons."""

    failed: bool = False
    reasons: tuple[str, ...] = ()

    @classmethod
    def ok(cls) -> Verdict:
        return cls()

    @classmethod
    def fail(cls, reason: str, *more: str) -> Verdict:
        return cls(True, (reason, *more))


class Severity(StrEnum):
    """How bad a design-time finding is: errors make `sos-cwl-lint` exit 1, warnings too with `--strict`."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Finding:
    """One result of a design-time check (`sos-cwl-lint`)."""

    severity: Severity
    location: str
    message: str


@dataclass
class LintResult:
    lines: list[str] = field(default_factory=list)  # report printed before the findings
    findings: list[Finding] = field(default_factory=list)


class Extension:
    name: ClassVar[str]  # short id, used in `--extension` and the run trace
    title: ClassVar[str] = ""  # argument group title (default: `name`)

    @property
    def group_title(self) -> str:
        return self.title or self.name

    # ---- runtime
    def add_arguments(self, group: argparse._ArgumentGroup) -> None:
        """Add this extension's flags to its group of cwltool's parser (prefix them, e.g. `--format-...`)."""

    def configure(self, args: argparse.Namespace) -> None:
        """Set up from the parsed arguments; raise `UsageError` for an invalid combination."""

    @property
    def active(self) -> bool:
        return True

    @property
    def wants_outputs(self) -> bool:
        return False

    def on_tool(self, tool: CommandLineTool) -> None:
        pass

    def before_job(self, ctx: JobContext) -> Verdict:
        return Verdict.ok()

    def after_job(self, ctx: JobContext, outputs: Mapping[str, Any]) -> Verdict:
        return Verdict.ok()

    def close(self) -> None:
        pass

    # ---- design time
    def add_lint_arguments(self, group: argparse._ArgumentGroup) -> None:
        pass

    def lint(self, document: str, args: argparse.Namespace) -> LintResult:
        return LintResult()
