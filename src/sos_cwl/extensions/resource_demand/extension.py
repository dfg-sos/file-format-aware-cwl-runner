"""Resource demand: parametric dependency annotations at design time and at run time.

Design time (`sos-cwl-lint`): read the annotations of every CommandLineTool, validate them with
the SHACL shapes (`shapes.ttl`) against the SOS vocabularies, and show each demand in Big O notation.

Run time (`--resource-demand log`, needs `--trace`): for every job of an annotated tool, add a
`demand` record to the run trace with the annotated demands and the values of the complexity variables that can be
measured from the job's inputs; with `--resource-demand-probes` also derived measures, by running their probes.
Together with the `job` record of the same job these are the samples an estimator fits its coefficients to. Nothing
is changed in the job.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import asdict
from enum import StrEnum
from typing import Any

from cwltool.command_line_tool import CommandLineTool
from cwltool.context import RuntimeContext
from cwltool.process import shortname

from sos_cwl.core import loading
from sos_cwl.core.extension import Extension, JobContext, LintResult, UsageError, Verdict

from . import probes
from .annotations import ToolAnnotation, Variable
from .lint import lint_document
from .measures import DirectMeasure, Instrument, Measurement
from .vocabulary import RD_VERSION, release_url

_logger = logging.getLogger("cwltool")


class Mode(StrEnum):
    OFF = "off"  # ignore the annotations
    LOG = "log"  # a `demand` record per job of an annotated tool


class ResourceDemandExtension(Extension):
    name = "resource-demand"
    title = "resource demand (parametric dependencies)"

    mode: Mode = Mode.OFF

    def __init__(self) -> None:
        self.tools: dict[str, ToolAnnotation] = {}  # tool id -> annotation, annotated tools only
        self.prober: probes.Prober | None = None  # with --resource-demand-probes

    # ---- runtime
    def add_arguments(self, group: argparse._ArgumentGroup) -> None:
        group.add_argument(
            "--resource-demand",
            type=Mode,
            choices=list(Mode),
            default=Mode.OFF,
            help="off: ignore the annotations (default); log: add a `demand` record per job of an annotated tool "
            "to the run trace (needs --trace).",
        )
        group.add_argument(
            "--resource-demand-probes",
            action="store_true",
            help="Run the probe of every derived measure (rd:DerivedMeasure) on the job's input, before the job; "
            "without, their value is null. Needs --resource-demand log.",
        )

    def configure(self, args: argparse.Namespace) -> None:
        self.mode = args.resource_demand
        if self.mode == Mode.LOG and not args.trace:
            raise UsageError("--resource-demand log needs --trace, where the demand records go")
        if args.resource_demand_probes:
            if self.mode != Mode.LOG:
                raise UsageError("--resource-demand-probes needs --resource-demand log")
            self.prober = probes.Prober(RuntimeContext(vars(args)))

    @property
    def active(self) -> bool:
        return self.mode == Mode.LOG and bool(self.tools)

    def on_tool(self, tool: CommandLineTool) -> None:
        if self.mode == Mode.OFF:
            return
        ann = ToolAnnotation.from_tool(tool.tool, loading.namespaces(tool))
        for finding in ann.findings:
            _logger.warning("[resource demand] %s: %s", shortname(ann.tool_id), finding.message)
        if ann.annotated:
            self.tools[ann.tool_id] = ann

    def before_job(self, ctx: JobContext) -> Verdict:
        ann = self.tools.get(ctx.tool.tool["id"])
        if ann is None:
            return Verdict.ok()
        variables = {symbol: self.variable(ann, var, ctx) for symbol, var in ann.variables.items()}
        ctx.record(
            "demand",
            tool=ann.tool_id,
            source=ann.demand_source,
            variables=variables,
            demands={res: [[asdict(f) for f in term] for term in terms] for res, terms in ann.demands.items()},
        )
        return Verdict.ok()

    def variable(self, ann: ToolAnnotation, var: Variable, ctx: JobContext) -> dict[str, Any]:
        """The variable's entry in the `demand` record: its port, measure and value (and how the probe went)."""
        port = shortname(var.port)
        value = ctx.inputs.get(port)
        instrument = self.instrument(var)
        taken = instrument.take(var, ann.ports[var.port], value) if instrument else Measurement(None)
        entry: dict[str, Any] = {"port": port, "measure": var.measure, "value": taken.value}
        if taken.duration_ms is not None:
            entry["probe_ms"] = taken.duration_ms
        if taken.error:
            _logger.warning("[resource demand] %s: %s", ctx.step, taken.error)
            entry["error"] = taken.error
        return entry

    def instrument(self, var: Variable) -> Instrument | None:
        """Its probe (with --resource-demand-probes), or its direct measure; None if it cannot be taken yet."""
        if var.probe and self.prober:
            return self.prober
        return DirectMeasure(var.measure) if var.measure in DirectMeasure else None

    def close(self) -> None:
        if self.prober:
            self.prober.close()

    # ---- design time
    def add_lint_arguments(self, group: argparse._ArgumentGroup) -> None:
        group.add_argument(
            "--resource-demand-vocabulary",
            metavar="VERSION|URL",
            default=RD_VERSION,
            help=f"Release of the resource demand vocabulary (default %(default)s, from {release_url('VERSION')}, "
            "downloaded once and cached), or the URL or path of an unreleased one. Domain vocabularies (formats, "
            "measures such as eo:PixelCount) come from the document's $schemas.",
        )

    def lint(self, document: str, args: argparse.Namespace) -> LintResult:
        return lint_document(document, args.resource_demand_vocabulary)
