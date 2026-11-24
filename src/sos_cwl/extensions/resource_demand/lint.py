"""Design time (`sos-cwl-lint`): validate the annotations of a document and show each demand in Big O notation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from rdflib import Graph
from schema_salad.exceptions import ValidationException

from sos_cwl.core import loading
from sos_cwl.core.extension import Finding, LintResult, Severity

from .annotations import ToolAnnotation
from .validate import validate
from .vocabulary import RD_VERSION, Vocabulary, VocabularyError, rd_graph


@dataclass
class Document:
    """A tool or workflow document: the annotations of its CommandLineTools and what it declares to check them."""

    annotations: list[ToolAnnotation]
    schemas: list[Graph]  # the domain vocabularies of its $schemas, as cwltool loaded them
    namespaces: dict[str, str]  # its $namespaces, for display

    @classmethod
    def load(cls, path: str | Path) -> Document:
        tools = list(loading.command_line_tools(loading.load(path)))
        schemas = {id(t.formatgraph): t.formatgraph for t in tools if t.formatgraph is not None}
        return cls(
            annotations=[ToolAnnotation.from_tool(t.tool, loading.namespaces(t)) for t in tools],
            schemas=list(schemas.values()),
            namespaces={prefix: ns for t in tools for prefix, ns in loading.namespaces(t).items()},
        )

    def vocabulary(self, rd: str = RD_VERSION) -> Vocabulary:
        return Vocabulary(rd_graph(rd), self.schemas, self.namespaces)


def lint_document(document: str, rd: str = RD_VERSION) -> LintResult:
    """Every annotated tool described, every problem as a finding; locations relative to the working directory."""
    try:
        doc = Document.load(document)
    except ValidationException as exc:
        return LintResult(findings=[Finding(Severity.ERROR, document, f"not valid CWL: {exc}")])
    if not any(a.annotated or a.findings for a in doc.annotations):
        return LintResult()  # no vocabulary needed
    try:
        vocabulary = doc.vocabulary(rd)
    except VocabularyError as exc:
        return LintResult(findings=[Finding(Severity.ERROR, document, str(exc))])
    base = Path.cwd()
    return LintResult(
        lines=[line for ann in doc.annotations for line in describe(ann, vocabulary, base)],
        findings=[replace(f, location=relative(f.location, base)) for f in validate(doc.annotations, vocabulary)],
    )


def describe(ann: ToolAnnotation, vocabulary: Vocabulary, base: Path) -> list[str]:
    """`tool.cwl`, then one line per variable (`n = eo:PixelCount(mask)`) and per demand (`ram: O(n)`)."""
    lines = [relative(ann.tool_id, base)]
    for var in ann.variables.values():
        port = var.port.rsplit("#", 1)[-1]
        measure_name = vocabulary.qname(var.measure)
        probe = f" via {relative(var.probe, base)}" if var.probe else ""
        lines.append(f"  {var.symbol} = {measure_name}({port}){probe}")
    for resource, terms in ann.demands.items():
        lines.append(f"  {resource + ':':6}{vocabulary.big_o(terms)}")
    if not ann.annotated:
        lines.append("  (no annotation)")
    return lines


def relative(iri: str, base: Path) -> str:
    return iri.removeprefix(base.resolve().as_uri() + "/")
