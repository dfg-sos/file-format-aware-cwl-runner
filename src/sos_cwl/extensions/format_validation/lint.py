"""Design-time check (`sos-cwl-lint`) that connected File ports have compatible formats.

For every connection (workflow input or step output -> step input, and -> workflow output) the
source port's format is checked against the sink port's format with the service's
`/compatibility` endpoint (subclass / equivalence in the ontologies listed in `$schemas`).
A connection is compatible if every source format is compatible with at least one sink format
in at least one of the ontologies. Formats that no ontology defines (service answers 422) are
reported as `unknown-format` instead of `incompatible`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from cwl_utils.parser import load_document_by_uri

from sos_cwl.core.extension import Finding, LintResult, Severity

from .client import FormatServiceClient


class Status(StrEnum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNKNOWN_FORMAT = "unknown-format"  # no ontology defines the format (typo, wrong ontology)
    ERROR = "error"  # the service could not decide
    UNANNOTATED = "unannotated"
    EXPRESSION = "expression"


SEVERITY = {
    Status.INCOMPATIBLE: Severity.ERROR,
    Status.UNKNOWN_FORMAT: Severity.ERROR,
    Status.ERROR: Severity.ERROR,
    Status.UNANNOTATED: Severity.WARNING,
    Status.EXPRESSION: Severity.INFO,
}


@dataclass
class Connection:
    """One checked connection between two ports."""

    workflow: str
    source: str
    sink: str
    source_formats: list[str]
    sink_formats: list[str]
    status: Status = Status.COMPATIBLE
    message: str = ""


def short_id(uri: str) -> str:
    return uri.split("#", 1)[-1] if "#" in uri else uri


def last_segment(uri: str) -> str:
    return short_id(uri).rsplit("/", 1)[-1]


def formats_of(port: Any) -> list[str]:
    return _as_list(getattr(port, "format", None))


def is_expression(formats: Sequence[str]) -> bool:
    return any(f.startswith(("$(", "${")) for f in formats)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def _is_file_port(port: Any) -> bool:
    """Whether the port's type mentions File (also File[], File?, unions, records)."""
    saved = json.dumps(getattr(port, "type_", None), default=lambda t: t.save() if hasattr(t, "save") else str(t))
    return "File" in saved


def _is_workflow(process: Any) -> bool:
    return getattr(process, "class_", None) == "Workflow"


def connections(wf: Any) -> Iterator[tuple[str, str, Any, str, Any]]:
    """(workflow id, source id, source port, sink id, sink port) of every connection in `wf` and its nested
    workflows; the source port is None when it cannot be found."""
    # Every port that can feed a connection inside this workflow.
    sources: dict[str, Any] = {inp.id: inp for inp in wf.inputs}
    runs: dict[str, Any] = {}
    for step in wf.steps:
        run = runs[step.id] = load_document_by_uri(step.run) if isinstance(step.run, str) else step.run
        outs_by_name = {last_segment(o.id): o for o in run.outputs}
        for out in step.out:
            out_id = out if isinstance(out, str) else out.id
            if (port := outs_by_name.get(last_segment(out_id))) is not None:
                sources[out_id] = port

    for step in wf.steps:
        run = runs[step.id]
        sinks = {last_segment(i.id): i for i in run.inputs}
        for step_in in step.in_:
            sink = sinks.get(last_segment(step_in.id))
            if sink is None or step_in.source is None or getattr(step_in, "valueFrom", None):
                continue  # valueFrom: transformed by an expression, nothing static to compare
            for src in _as_list(step_in.source):
                yield wf.id, src, sources.get(src), step_in.id, sink
        if _is_workflow(run):
            yield from connections(run)

    for out in wf.outputs:
        for src in _as_list(getattr(out, "outputSource", None)):
            yield wf.id, src, sources.get(src), out.id, out


class Linter:
    """Checks the connections of CWL documents with the service; `ontology_urls` replace each document's `$schemas`."""

    def __init__(self, client: FormatServiceClient, ontology_urls: Sequence[str] | None = None):
        self.client = client
        self.ontology_urls = list(ontology_urls or [])

    def lint(self, document: str) -> LintResult:
        """`sos-cwl-lint`: every problem as a finding, every compatible connection as a line."""
        doc = load_document_by_uri(document)
        ontologies = self.ontology_urls or list(getattr(doc.loadingOptions, "schemas", None) or [])
        if not ontologies:
            skipped = Finding(Severity.INFO, document, "no $schemas and no --format-ontology-url; skipped")
            return LintResult(findings=[skipped])
        if not _is_workflow(doc):
            return LintResult()  # a CommandLineTool has no connections
        checked = self.check(doc, ontologies)
        return LintResult(
            lines=[f"{c.status.upper():14} {c.source} -> {c.sink}" for c in checked if c.status == Status.COMPATIBLE],
            findings=[
                Finding(SEVERITY[c.status], f"{c.source} -> {c.sink}", c.message)
                for c in checked
                if c.status != Status.COMPATIBLE
            ],
        )

    def check(self, workflow: Any, ontologies: Sequence[str]) -> list[Connection]:
        """Every File connection of `workflow`, checked against the given ontologies."""
        return [c for ports in connections(workflow) if (c := self._check(*ports, ontologies)) is not None]

    def _check(
        self, wf_id: str, source_id: str, source: Any, sink_id: str, sink: Any, ontologies: Sequence[str]
    ) -> Connection | None:
        """Check one connection; None for connections that do not carry Files."""
        src_fmts = formats_of(source)
        sink_fmts = formats_of(sink)
        if not src_fmts and not _is_file_port(sink):
            return None
        c = Connection(short_id(wf_id), short_id(source_id), short_id(sink_id), src_fmts, sink_fmts)
        if is_expression(src_fmts) or is_expression(sink_fmts):
            c.status, c.message = Status.EXPRESSION, "format is an expression; skipped"
        elif not sink_fmts:
            c.status, c.message = Status.UNANNOTATED, "sink declares no format (accepts anything)"
        elif not src_fmts:
            c.status, c.message = Status.UNANNOTATED, "source declares no format"
        else:
            for actual in src_fmts:
                pairs = [self._pair(expected, actual, ontologies) for expected in sink_fmts]
                if all(status != Status.COMPATIBLE for status, _ in pairs):
                    # Report the most informative reason: an unknown format (typo, wrong ontology) explains
                    # the rest; a service error means compatibility could not be decided.
                    found = {status for status, _ in pairs}
                    c.status = next(s for s in (Status.UNKNOWN_FORMAT, Status.ERROR, Status.INCOMPATIBLE) if s in found)
                    c.message = "; ".join(dict.fromkeys(m for s, m in pairs if s == c.status))
                    break
        return c

    def _pair(self, expected: str, actual: str, ontologies: Sequence[str]) -> tuple[Status, str]:
        """Status of one (sink format, source format) pair over all ontologies.

        Compatible if any ontology says so; incompatible if an ontology defines both formats but
        does not relate them; unknown-format only if every ontology lacks one of them.
        """
        results = []
        for url in ontologies:
            r = self.client.compatibility(expected, actual, url)
            if r.compatible:
                return Status.COMPATIBLE, ""
            results.append(r)
        if any(r.compatible is False for r in results):
            return Status.INCOMPATIBLE, f"{last_segment(actual)} is not {last_segment(expected)} or a subclass of it"
        if results and all(r.unknown_formats for r in results):
            unknown = dict.fromkeys(last_segment(f) for r in results for f in r.unknown_formats)
            return Status.UNKNOWN_FORMAT, f"not defined in {list(ontologies)}: {list(unknown)}"
        return Status.ERROR, next((r.message for r in results if not r.unknown_formats), "no ontology given")
