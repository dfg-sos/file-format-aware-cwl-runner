"""Runtime format validation: send the real files of each job to the SOS File Format Service.

Before a job (pre) its input Files, after it (post) its output Files are validated against their
`format` label. A fatal result ends the step `permanentFail`, see `policy.py`.
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from collections.abc import Callable, Mapping
from typing import Any

from cwltool.process import shortname

from sos_cwl.core.extension import Extension, JobContext, LintResult, Verdict
from sos_cwl.core.files import default_resolve, iter_files

from . import fields
from .client import FormatServiceClient, Mode, Transfer, ValidationStatus
from .files import secondary_refs, to_ref
from .policy import Check, Phase, Policy, Reaction, describe

_logger = logging.getLogger("cwltool")

DEFAULT_SERVICE_URL = "http://localhost:8000"


class FormatValidationExtension(Extension):
    name = "format-validation"
    title = "format validation (SOS File Format Service)"

    client: FormatServiceClient | None = None
    policy: Policy = Policy(validation=Reaction.OFF)
    phases: frozenset[Phase] = Check.BOTH.phases

    def _add_service_url(self, group: argparse._ArgumentGroup) -> None:
        """For both the runner and the lint, which build separate parsers."""
        group.add_argument(
            "--format-service-url",
            default=os.environ.get("SOS_FFS_URL", DEFAULT_SERVICE_URL),
            help="Base URL of the format service (env SOS_FFS_URL; default %(default)s).",
        )

    # ---- runtime
    def add_arguments(self, group: argparse._ArgumentGroup) -> None:
        self._add_service_url(group)
        group.add_argument(
            "--format-validation",
            choices=list(Reaction),
            default=Reaction.OFF,
            help="off: plain cwltool (default); warn: log only; fail: abort the step.",
        )
        group.add_argument(
            "--format-validation-mode",
            choices=list(Mode),
            default=Mode.BASIC,
            help="Service validation depth (default %(default)s).",
        )
        group.add_argument(
            "--format-check",
            choices=list(Check),
            default=Check.BOTH,
            help="Validate step inputs (pre), outputs (post) or both (default).",
        )
        group.add_argument(
            "--format-uncertain",
            choices=[Reaction.WARN, Reaction.FAIL],
            default=Reaction.WARN,
            help="Treat an UNCERTAIN result as a warning (default) or a failure.",
        )
        group.add_argument(
            "--format-service-error",
            choices=[Reaction.WARN, Reaction.FAIL],
            default=Reaction.FAIL,
            help="When the service is unreachable or rejects a request (default: fail).",
        )
        group.add_argument(
            "--format-file-transfer",
            choices=list(Transfer),
            default=Transfer.AUTO,
            help="How files reach the service: local = by path (/validate/local, needs SOS_FFS_SHARED_DIRS on the "
            "service), upload = multipart upload, auto = by path, falling back to upload when the service cannot "
            "read the path (default).",
        )
        group.add_argument("--format-service-timeout", type=float, default=300.0, help="Seconds per request.")

    def configure(self, args: argparse.Namespace) -> None:
        self.policy = Policy(
            validation=Reaction(args.format_validation),
            mode=Mode(args.format_validation_mode),
            uncertain=Reaction(args.format_uncertain),
            service_error=Reaction(args.format_service_error),
        )
        self.phases = Check(args.format_check).phases
        self.client = FormatServiceClient(
            args.format_service_url,
            timeout=args.format_service_timeout,
            transfer=Transfer(args.format_file_transfer),
        )

    @property
    def active(self) -> bool:
        # With --format-validation off no job is touched, so timings stay comparable with plain cwltool.
        return self.policy.enabled

    @property
    def wants_outputs(self) -> bool:
        return Phase.POST in self.phases

    def before_job(self, ctx: JobContext) -> Verdict:
        if Phase.PRE not in self.phases:
            return Verdict.ok()
        fatal: list[str] = []
        for port in ctx.tool.tool["inputs"]:
            name = shortname(port["id"])
            if name in ctx.inputs:
                fatal += self.check_port(ctx, port, ctx.inputs[name], Phase.PRE, ctx.resolve)
        return Verdict.fail(*fatal) if fatal else Verdict.ok()

    def after_job(self, ctx: JobContext, outputs: Mapping[str, Any]) -> Verdict:
        fatal: list[str] = []
        for port in ctx.tool.tool["outputs"]:
            name = shortname(port["id"])
            if name in outputs:
                fatal += self.check_port(ctx, port, outputs[name], Phase.POST)
        return Verdict.fail(*fatal) if fatal else Verdict.ok()

    def close(self) -> None:
        if self.client is not None:
            self.client.close()

    def check_port(
        self,
        ctx: JobContext,
        port: Mapping[str, Any],
        value: Any,
        phase: Phase,
        resolve: Callable[[str], str] = default_resolve,
    ) -> list[str]:
        """Validate every File in one port value. Returns messages of fatal failures."""
        assert self.client is not None, "configure() first"
        fatal: list[str] = []
        port_name = shortname(port["id"])
        for f in iter_files(value):
            fmt = f.get("format")
            if not fmt:
                ctx.record(
                    "skip",
                    port=port_name,
                    phase=phase,
                    file=f.get("basename"),
                    reason="no format",
                )
                continue
            ref = to_ref(f, resolve)
            secondaries = secondary_refs(f, resolve)
            metadata = fields.expected_metadata(port) if self.policy.mode != Mode.BASIC else None
            t_start = time.perf_counter_ns()
            result = self.client.validate(
                ref,
                str(fmt),
                mode=self.policy.mode,
                secondaries=secondaries,
                expected_metadata=metadata,
            )
            t_end = time.perf_counter_ns()
            ctx.record(
                "check",
                port=port_name,
                phase=phase,
                file=ref.basename,
                size_bytes=ref.size(),
                secondary_size_bytes=sum(s.size() or 0 for s in secondaries),
                format=fmt,
                mode=self.policy.mode,
                result=result.status,
                message=result.message,
                transfer=result.transfer,
                server_timing=result.server_timing,
                t_start=t_start,
                t_end=t_end,
                duration_ms=(t_end - t_start) / 1e6,
            )
            if result.status == ValidationStatus.SUCCESS:
                continue
            msg = describe(ctx.step, port_name, phase, ref.basename, str(fmt), result)
            if self.policy.is_fatal(result):
                _logger.error(msg)
                fatal.append(msg)
            else:
                _logger.warning(msg)
        return fatal

    # ---- design time
    def add_lint_arguments(self, group: argparse._ArgumentGroup) -> None:
        self._add_service_url(group)
        group.add_argument(
            "--format-ontology-url",
            action="append",
            default=None,
            help="Ontology URL as reachable by the service; repeatable (default: all $schemas entries).",
        )

    def lint(self, document: str, args: argparse.Namespace) -> LintResult:
        from .lint import Linter

        client = FormatServiceClient(args.format_service_url)
        try:
            return Linter(client, args.format_ontology_url).lint(document)
        finally:
            client.close()
