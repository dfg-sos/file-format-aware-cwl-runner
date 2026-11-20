"""cwltool integration: a CommandLineTool that calls the extensions' hooks around each job.

    Runtime                         one run: extensions, trace
      .make_tool                    cwltool's tool factory -> ExtensibleCommandLineTool, `on_tool`
    ExtensibleCommandLineTool.job   per job: `before_job`; wraps the job's `run` (`job` record)
                                    and `collect_outputs` (`after_job`)

See docs/cwltool-hook-points.md for why these hook points (and no fork of cwltool) suffice.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass
from typing import Any

from cwltool.command_line_tool import CommandLineTool
from cwltool.context import LoadingContext, RuntimeContext
from cwltool.errors import WorkflowException
from cwltool.job import JobBase
from cwltool.process import shortname
from cwltool.workflow import default_make_tool

from .extension import Extension, JobContext, Verdict
from .trace import Trace, duration_ms, now_ns


@dataclass
class Runtime:
    """Shared state for one cwltool run."""

    extensions: Sequence[Extension]
    trace: Trace

    # ---- set up by the runner
    def make_tool(self, toolpath_object: Any, loadingContext: LoadingContext) -> Any:
        """For `LoadingContext.construct_tool_object`: our CommandLineTool, everything else as cwltool does."""
        if toolpath_object.get("class") == "CommandLineTool":
            tool = ExtensibleCommandLineTool(toolpath_object, loadingContext)
            tool.runtime = self
            for ext in self.extensions:
                ext.on_tool(tool)
            return tool
        return default_make_tool(toolpath_object, loadingContext)

    # ---- per job, called by ExtensibleCommandLineTool
    @property
    def active(self) -> list[Extension]:
        return [e for e in self.extensions if e.active]

    def before_job(self, ctx: JobContext, extensions: Sequence[Extension]) -> list[Verdict]:
        verdicts = []
        for ext in extensions:
            t_start = now_ns()
            verdict = ext.before_job(ctx)
            self._trace_hook(ext, "before_job", ctx, verdict, t_start)
            verdicts.append(verdict)
        return verdicts

    def collect_and_check(
        self,
        ctx: JobContext,
        extensions: Sequence[Extension],
        collect: Callable[[str, int], Any],
        outdir: str,
        rcode: int,
    ) -> Any:
        """Replaces the job's `collect_outputs`: collect as cwltool does, then call each `after_job`."""
        outputs = collect(outdir, rcode)
        verdicts = []
        for ext in extensions:
            t_start = now_ns()
            verdict = ext.after_job(ctx, outputs)
            self._trace_hook(ext, "after_job", ctx, verdict, t_start)
            verdicts.append(verdict)
        if any(v.failed for v in verdicts):
            # Raised inside JobBase._execute -> job ends permanentFail with this message.
            raise WorkflowException("\n".join(reason for v in verdicts if v.failed for reason in v.reasons))
        return outputs

    def traced_run(self, step: str, job: str, run: Callable[..., None], *args: Any, **kwargs: Any) -> None:
        """Replaces the job's `run` (with --trace): run it as cwltool does and add a `job` record.

        Covers the whole job: staging, container start-up (and image pull), the command, collecting
        outputs including the `after_job` hooks. The `before_job` hooks ran before.
        """
        t_start = now_ns()
        try:
            run(*args, **kwargs)
        finally:
            t_end = now_ns()
            self.trace.write(
                "job", step=step, job=job, t_start=t_start, t_end=t_end, duration_ms=duration_ms(t_start, t_end)
            )

    def _trace_hook(self, ext: Extension, hook: str, ctx: JobContext, verdict: Verdict, t_start: int) -> None:
        """Add a `hook` record: how long `ext.<hook>` took on this job (called right after the hook returned)."""
        t_end = now_ns()
        self.trace.write(
            "hook",
            extension=ext.name,
            hook=hook,
            step=ctx.step,
            job=ctx.name,
            failed=verdict.failed,
            t_start=t_start,
            t_end=t_end,
            duration_ms=duration_ms(t_start, t_end),
        )


class ExtensibleCommandLineTool(CommandLineTool):
    runtime: Runtime  # set by Runtime.make_tool

    def job(
        self,
        job_order: Any,
        output_callbacks: Any,
        runtimeContext: RuntimeContext,
    ) -> Generator[Any, None, None]:
        rt = self.runtime
        step = runtimeContext.name or shortname(self.tool["id"])
        for j in super().job(job_order, output_callbacks, runtimeContext):
            if not isinstance(j, JobBase):
                if j is not None:  # CallbackJob: cache hit, nothing is executed or checked
                    rt.trace.write("cached", step=step)
                yield j
                continue
            if rt.trace.enabled:  # also for the plain-cwltool baseline
                j.run = functools.partial(rt.traced_run, step, j.name, j.run)
            active = rt.active
            if not active:  # no hooks at all, e.g. the plain-cwltool baseline
                yield j
                continue
            ctx = JobContext(self, j, step, rt.trace)
            verdicts = rt.before_job(ctx, active)
            if any(v.failed for v in verdicts):
                # Same outcome as a failed command: the step ends permanentFail and the
                # workflow continues with whatever does not depend on it.
                j.output_callback({}, "permanentFail")
                continue
            after = [e for e in active if e.wants_outputs]
            if after:
                j.collect_outputs = functools.partial(rt.collect_and_check, ctx, after, j.collect_outputs)
            yield j
