"""`cwl-format-aware-runner`: cwltool with runtime file-format validation via the SOS File Format Service."""

from __future__ import annotations

import argparse
import os
import sys

import cwltool.main
from cwltool.argparser import arg_parser
from cwltool.context import LoadingContext

from .client import FormatServiceClient
from .policy import Policy
from .timing import TimingLog
from .tool import POST, PRE, Validator, install_main_timer, make_tool_factory

DEFAULT_SERVICE_URL = "http://localhost:8000"


def add_format_arguments(parser: argparse.ArgumentParser) -> None:
    g = parser.add_argument_group("format validation (SOS File Format Service)")
    g.add_argument(
        "--format-service-url",
        default=os.environ.get("SOS_FFS_URL", DEFAULT_SERVICE_URL),
        help="Base URL of the format service (env SOS_FFS_URL; default %(default)s).",
    )
    g.add_argument(
        "--format-validation",
        choices=["off", "warn", "fail"],
        default="fail",
        help="off: plain cwltool (baseline); warn: log only; fail: abort the step (default).",
    )
    g.add_argument(
        "--format-validation-mode",
        choices=["basic", "structural", "full"],
        default="basic",
        help="Service validation depth (default %(default)s).",
    )
    g.add_argument(
        "--format-check",
        choices=["both", "pre", "post"],
        default="both",
        help="Validate step inputs (pre), outputs (post) or both (default).",
    )
    g.add_argument(
        "--format-uncertain",
        choices=["warn", "fail"],
        default="warn",
        help="Treat an UNCERTAIN result as a warning (default) or a failure.",
    )
    g.add_argument(
        "--format-service-error",
        choices=["warn", "fail"],
        default="fail",
        help="When the service is unreachable or rejects a request (default: fail).",
    )
    g.add_argument(
        "--format-file-transfer",
        choices=["auto", "local", "upload"],
        default="auto",
        help="How files reach the service: local = by path (/validate/local, needs SOS_FFS_SHARED_DIRS on the "
        "service), upload = multipart upload, auto = by path, falling back to upload when the service cannot "
        "read the path (default).",
    )
    g.add_argument("--format-service-timeout", type=float, default=300.0, help="Seconds per request.")
    g.add_argument(
        "--format-timing-log",
        metavar="FILE.jsonl",
        default=None,
        help="Append one JSON record per check, per main command and per run.",
    )
    g.add_argument("--format-run-id", default=None, help="Run id written to the timing log (default: random).")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = arg_parser()
    parser.prog = "cwl-format-aware-runner"
    add_format_arguments(parser)
    addl = [x for x in os.environ.get("CWLTOOL_OPTIONS", "").split(" ") if x]
    args = parser.parse_args(addl + argv)
    if args.record_container_id:  # mirrors cwltool.main.main
        if not args.cidfile_dir:
            args.cidfile_dir = os.getcwd()
        del args.record_container_id
    return args


def format_flags(args: argparse.Namespace) -> dict[str, object]:
    return {k: v for k, v in vars(args).items() if k.startswith("format_")}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    policy = Policy(
        validation=args.format_validation,
        mode=args.format_validation_mode,
        uncertain=args.format_uncertain,
        service_error=args.format_service_error,
    )
    directions = {"both": {PRE, POST}, "pre": {PRE}, "post": {POST}}[args.format_check]
    client = FormatServiceClient(
        args.format_service_url, timeout=args.format_service_timeout, transfer=args.format_file_transfer
    )
    log = TimingLog(args.format_timing_log, args.format_run_id)
    log.run_record(format_flags(args), args.format_service_url if policy.enabled else None)
    # With --format-validation off the tool subclass only records job->step names (no wrapping,
    # no service calls), so timings stay comparable with the validated runs.
    validator = Validator(client, policy, log, frozenset(directions))
    if log.enabled:
        install_main_timer(validator)

    loading_context = LoadingContext(vars(args))
    loading_context.construct_tool_object = make_tool_factory(validator)
    try:
        return cwltool.main.main(args=args, loadingContext=loading_context)
    finally:
        client.close()
        log.close()


if __name__ == "__main__":
    sys.exit(main())
