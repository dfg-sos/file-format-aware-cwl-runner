"""`cwl-format-lint`: design-time check that connected File ports have compatible formats.

For every connection (workflow input or step output -> step input, and -> workflow output) the
source port's format is checked against the sink port's format with the service's
`/compatibility` endpoint (subclass / equivalence in the ontologies listed in `$schemas`).
A connection is compatible if every source format is compatible with at least one sink format
in at least one of the ontologies. Formats that no ontology defines (service answers 422) are
reported as `unknown-format` instead of `incompatible`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from cwl_utils.parser import load_document_by_uri

from .client import FormatServiceClient

COMPATIBLE = "compatible"
INCOMPATIBLE = "incompatible"
UNANNOTATED = "unannotated"
EXPRESSION = "expression"
ERROR = "error"
UNKNOWN_FORMAT = "unknown-format"


@dataclass
class Finding:
    workflow: str
    source: str
    sink: str
    source_formats: list[str]
    sink_formats: list[str]
    status: str
    message: str = ""
    details: list[dict[str, Any]] = field(default_factory=list)


def short_id(uri: str) -> str:
    return uri.split("#", 1)[-1] if "#" in uri else uri


def last_segment(uri: str) -> str:
    return short_id(uri).rsplit("/", 1)[-1]


def formats_of(port: Any) -> list[str]:
    fmt = getattr(port, "format", None)
    if fmt is None:
        return []
    return [str(f) for f in (fmt if isinstance(fmt, list) else [fmt])]


def is_expression(formats: Sequence[str]) -> bool:
    return any(f.startswith(("$(", "${")) for f in formats)


def _load_run(run: Any) -> Any:
    return load_document_by_uri(run) if isinstance(run, str) else run


def _step_outputs(step: Any) -> Iterator[str]:
    for out in step.out:
        yield out if isinstance(out, str) else out.id


def _is_workflow(process: Any) -> bool:
    return getattr(process, "class_", None) == "Workflow"


class Linter:
    def __init__(self, client: FormatServiceClient, ontology_urls: Sequence[str]):
        self.client = client
        self.ontology_urls = list(ontology_urls)

    def lint(self, workflow: Any) -> list[Finding]:
        findings: list[Finding] = []
        self._lint_workflow(workflow, findings)
        return findings

    def _lint_workflow(self, wf: Any, findings: list[Finding]) -> None:
        # Every port that can feed a connection inside this workflow.
        sources: dict[str, Any] = {inp.id: inp for inp in wf.inputs}
        runs: dict[str, Any] = {}
        for step in wf.steps:
            run = runs[step.id] = _load_run(step.run)
            outs_by_name = {last_segment(o.id): o for o in run.outputs}
            for out_id in _step_outputs(step):
                port = outs_by_name.get(last_segment(out_id))
                if port is not None:
                    sources[out_id] = port

        for step in wf.steps:
            run = runs[step.id]
            sinks = {last_segment(i.id): i for i in run.inputs}
            for step_in in step.in_:
                sink = sinks.get(last_segment(step_in.id))
                if sink is None or step_in.source is None:
                    continue
                if getattr(step_in, "valueFrom", None):
                    continue  # value is transformed by an expression; nothing static to compare
                for src in _as_list(step_in.source):
                    self._add(findings, self._check(wf.id, src, sources.get(src), step_in.id, sink))
            if _is_workflow(run):
                self._lint_workflow(run, findings)

        for out in wf.outputs:
            for src in _as_list(getattr(out, "outputSource", None)):
                self._add(findings, self._check(wf.id, src, sources.get(src), out.id, out))

    @staticmethod
    def _add(findings: list[Finding], finding: Finding | None) -> None:
        if finding is not None:
            findings.append(finding)

    def _check(self, wf_id: str, source_id: str, source: Any, sink_id: str, sink: Any) -> Finding | None:
        """Check one connection; None for connections that do not carry Files."""
        src_fmts = formats_of(source) if source is not None else []
        sink_fmts = formats_of(sink)
        if not src_fmts and not _is_file_port(sink):
            return None
        finding = Finding(short_id(wf_id), short_id(source_id), short_id(sink_id), src_fmts, sink_fmts, COMPATIBLE)
        if is_expression(src_fmts) or is_expression(sink_fmts):
            finding.status, finding.message = EXPRESSION, "format is an expression; skipped"
            return finding
        if not sink_fmts:
            finding.status, finding.message = UNANNOTATED, "sink declares no format (accepts anything)"
            return finding
        if not src_fmts:
            finding.status, finding.message = UNANNOTATED, "source declares no format"
            return finding
        for actual in src_fmts:
            pairs = [self._pair(expected, actual, finding) for expected in sink_fmts]
            if any(status == COMPATIBLE for status, _ in pairs):
                continue
            # Report the most informative reason: an unknown format (typo, wrong ontology) explains the
            # rest; a service error means compatibility could not be decided.
            for status in (UNKNOWN_FORMAT, ERROR, INCOMPATIBLE):
                messages = [message for s, message in pairs if s == status]
                if messages:
                    finding.status, finding.message = status, "; ".join(dict.fromkeys(messages))
                    break
            return finding
        return finding

    def _pair(self, expected: str, actual: str, finding: Finding) -> tuple[str, str]:
        """Status of one (sink format, source format) pair over all ontologies.

        Compatible if any ontology says so; incompatible if an ontology defines both formats but
        does not relate them; unknown-format only if every ontology lacks one of them.
        """
        results = []
        for url in self.ontology_urls:
            r = self.client.compatibility(expected, actual, url)
            finding.details.append(
                {"actual": actual, "expected": expected, "ontology": url, "compatible": r.compatible}
                | ({"unknown_formats": r.unknown_formats} if r.unknown_formats else {"message": r.message})
            )
            if r.compatible:
                return COMPATIBLE, ""
            results.append(r)
        if any(r.compatible is False for r in results):
            return INCOMPATIBLE, f"{last_segment(actual)} is not {last_segment(expected)} or a subclass of it"
        if results and all(r.unknown_formats for r in results):
            unknown = dict.fromkeys(last_segment(f) for r in results for f in r.unknown_formats)
            return UNKNOWN_FORMAT, f"not defined in {self.ontology_urls}: {list(unknown)}"
        return ERROR, next((r.message for r in results if not r.unknown_formats), "no ontology given")


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def _is_file_port(port: Any) -> bool:
    return "File" in json.dumps(_type_repr(getattr(port, "type_", None)))


def _type_repr(t: Any) -> Any:
    if t is None or isinstance(t, str):
        return t
    if isinstance(t, list):
        return [_type_repr(x) for x in t]
    if hasattr(t, "save"):
        return t.save()
    return str(t)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cwl-format-lint", description=__doc__.splitlines()[0])
    p.add_argument("workflow", help="CWL workflow file")
    p.add_argument("--format-service-url", default=os.environ.get("SOS_FFS_URL", "http://localhost:8000"))
    p.add_argument(
        "--format-ontology-url",
        action="append",
        default=None,
        help="Ontology URL as reachable by the service; repeatable (default: all $schemas entries).",
    )
    p.add_argument("--strict", action="store_true", help="Fail on unannotated File connections.")
    p.add_argument("--json", action="store_true", help="Print findings as JSON.")
    args = p.parse_args(argv)

    doc = load_document_by_uri(args.workflow)
    schemas = list(getattr(doc.loadingOptions, "schemas", None) or [])
    ontology_urls = args.format_ontology_url or schemas
    if not ontology_urls:
        p.error("no ontology: the document has no $schemas; pass --format-ontology-url")

    client = FormatServiceClient(args.format_service_url)
    try:
        findings = Linter(client, ontology_urls).lint(doc) if _is_workflow(doc) else []
    finally:
        client.close()

    failing = {INCOMPATIBLE, UNKNOWN_FORMAT, ERROR} | ({UNANNOTATED} if args.strict else set())
    if args.json:
        print(json.dumps({"ontologies": ontology_urls, "findings": [asdict(f) for f in findings]}, indent=2))
    else:
        for f in findings:
            print(f"{f.status.upper():14} {f.source} -> {f.sink}  {f.message}".rstrip())
        counts = {
            s: sum(f.status == s for f in findings)
            for s in (COMPATIBLE, INCOMPATIBLE, UNKNOWN_FORMAT, UNANNOTATED, EXPRESSION, ERROR)
        }
        print(", ".join(f"{n} {s}" for s, n in counts.items()))
    return 1 if any(f.status in failing for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
