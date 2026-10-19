"""cwltool integration: a CommandLineTool that validates real files before and after each job."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass, field
from typing import Any

import cwltool.job
from cwltool.command_line_tool import CommandLineTool
from cwltool.context import LoadingContext, RuntimeContext
from cwltool.errors import WorkflowException
from cwltool.job import JobBase
from cwltool.process import shortname
from cwltool.workflow import default_make_tool

from . import extensions
from .client import SUCCESS, FormatServiceClient
from .files import default_resolve, iter_files, secondary_refs, to_ref
from .policy import Policy, describe
from .timing import TimingLog, duration_ms, now_ns

_logger = logging.getLogger("cwltool")

PRE, POST = "pre", "post"


@dataclass
class Validator:
    """Shared state for one cwltool run."""

    client: FormatServiceClient
    policy: Policy
    log: TimingLog
    directions: frozenset[str] = frozenset({PRE, POST})
    job_steps: dict[str, str] = field(default_factory=dict)  # job name -> workflow step name

    @property
    def enabled(self) -> bool:
        return self.policy.enabled

    def check_port(
        self,
        job: str,
        port: Mapping[str, Any],
        value: Any,
        direction: str,
        resolve: Callable[[str], str] = default_resolve,
    ) -> list[str]:
        """Validate every File in one port value. Returns messages of fatal failures."""
        fatal: list[str] = []
        port_name = shortname(port["id"])
        step = self.job_steps.get(job, job)
        for f in iter_files(value):
            fmt = f.get("format")
            if not fmt:
                self.log.write(
                    "skip",
                    step=step,
                    job=job,
                    port=port_name,
                    direction=direction,
                    file=f.get("basename"),
                    reason="no format",
                )
                continue
            ref = to_ref(f, resolve)
            crs = geom = None
            if self.policy.mode == "full":
                crs, geom = extensions.expected_crs(port), extensions.expected_geometry_type(port)
            t_start = now_ns()
            result = self.client.validate(
                ref,
                str(fmt),
                mode=self.policy.mode,
                secondaries=secondary_refs(f, resolve),
                expected_crs=crs,
                expected_geometry_type=geom,
            )
            t_end = now_ns()
            self.log.write(
                "check",
                step=step,
                job=job,
                port=port_name,
                direction=direction,
                file=ref.basename,
                size_bytes=ref.size(),
                format=fmt,
                mode=self.policy.mode,
                result=result.status,
                message=result.message,
                t_start=t_start,
                t_end=t_end,
                duration_ms=duration_ms(t_start, t_end),
            )
            if result.status == SUCCESS:
                continue
            msg = describe(step, port_name, direction, ref.basename, str(fmt), result)
            if self.policy.is_fatal(result):
                _logger.error(msg)
                fatal.append(msg)
            else:
                _logger.warning(msg)
        return fatal


class FormatAwareCommandLineTool(CommandLineTool):
    validator: Validator  # set by make_tool

    def job(
        self,
        job_order: Any,
        output_callbacks: Any,
        runtimeContext: RuntimeContext,
    ) -> Generator[Any, None, None]:
        v = self.validator
        step = runtimeContext.name or shortname(self.tool["id"])
        for j in super().job(job_order, output_callbacks, runtimeContext):
            if not isinstance(j, JobBase):
                if j is not None:  # CallbackJob: cache hit, nothing is executed or checked
                    v.log.write("cached", step=step)
                yield j
                continue
            v.job_steps[j.name] = step
            if not v.enabled:
                yield j
                continue
            if PRE in v.directions and not self._pre_check(j):
                continue  # step already reported permanentFail; do not run it
            if POST in v.directions:
                j.collect_outputs = functools.partial(_checked_collect, self, j, j.collect_outputs)
            yield j

    def _pre_check(self, j: JobBase) -> bool:
        def resolve(location: str) -> str:
            try:
                return j.pathmapper.mapper(location).resolved
            except KeyError:
                return default_resolve(location)

        fatal: list[str] = []
        for port in self.tool["inputs"]:
            name = shortname(port["id"])
            if name in j.builder.job:
                fatal += self.validator.check_port(j.name, port, j.builder.job[name], PRE, resolve)
        if fatal:
            # Same outcome as a failed command: the step ends permanentFail and the
            # workflow continues with whatever does not depend on it.
            j.output_callback({}, "permanentFail")
            return False
        return True


def _checked_collect(
    tool: FormatAwareCommandLineTool, j: JobBase, collect: Callable[..., Any], outdir: str, rcode: int
) -> Any:
    outputs = collect(outdir, rcode)
    fatal: list[str] = []
    for port in tool.tool["outputs"]:
        name = shortname(port["id"])
        if name in outputs:
            fatal += tool.validator.check_port(j.name, port, outputs[name], POST)
    if fatal:
        # Raised inside JobBase._execute -> job ends permanentFail with this message.
        raise WorkflowException("\n".join(fatal))
    return outputs


def make_tool_factory(validator: Validator) -> Callable[[Any, LoadingContext], Any]:
    def make_tool(toolpath_object: Any, loadingContext: LoadingContext) -> Any:
        if toolpath_object.get("class") == "CommandLineTool":
            tool = FormatAwareCommandLineTool(toolpath_object, loadingContext)
            tool.validator = validator
            return tool
        return default_make_tool(toolpath_object, loadingContext)

    return make_tool


_active: Validator | None = None


def install_main_timer(validator: Validator) -> None:
    """Time the tool's main command (cwltool.job._job_popen, called with name=job name).

    Includes container start-up for containerised jobs. Records go to the most recently
    installed validator's log.
    """
    global _active
    _active = validator
    original = cwltool.job._job_popen
    if getattr(original, "_format_aware", False):
        return

    @functools.wraps(original)
    def timed(*args: Any, **kwargs: Any) -> int:
        t_start = now_ns()
        try:
            return original(*args, **kwargs)
        finally:
            t_end = now_ns()
            if _active is not None:
                job = kwargs.get("name")
                _active.log.write(
                    "main",
                    step=_active.job_steps.get(job, job),
                    job=job,
                    t_start=t_start,
                    t_end=t_end,
                    main_duration_ms=duration_ms(t_start, t_end),
                )

    timed._format_aware = True  # type: ignore[attr-defined]
    cwltool.job._job_popen = timed
