"""Validate annotations with the SHACL shapes (`shapes.ttl`) against the vocabularies, and their probes.

The shapes check the annotation as RDF. Only what they need is mapped, not the whole CWL document:

    <tool>  a cwl:CommandLineTool ; cwl:inputs <port> ; cwl:requirements|cwl:hints <tool#ResourceRequirement> .
    <port>  cwl:type "File" ; cwl:items "File" ; cwl:format eo:GeoTIFF ;
            rd:complexityVariables <port/complexityVariables/n> .
    <port/complexityVariables/n>  rd:symbol "n" ; rd:measure eo:PixelCount ; rd:probe <probe.cwl> .
    <tool#ResourceRequirement>  a cwl:ResourceRequirement ; rd:ramDemand <…/ramDemand/0> .
    <…/ramDemand/0>  rd:factors <…/ramDemand/0/n> .
    <…/ramDemand/0/n>  rd:variable "n" ; rd:complexity rd:Linear .

Keys of a variable become rd: properties (`probe` -> rd:probe); unexpected keys too, so closed
shapes report them. A demand term `{n: rd:Linear}` becomes one factor node per entry. Nodes get IRIs
derived from the tool id, so a validation result points at the exact place in the document.

Probes are checked by loading them (`Probe.load`), not by the shapes.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import cache
from importlib.resources import files
from typing import Any
from urllib.parse import quote

from pyshacl import validate as shacl_validate
from rdflib import RDF, Graph, Literal, Namespace, URIRef
from rdflib.term import Node

from sos_cwl.core.extension import Finding, Severity

from .annotations import ToolAnnotation
from .probes import Probe, ProbeError
from .vocabulary import CWL, RD, Vocabulary

SH = Namespace("http://www.w3.org/ns/shacl#")
SEVERITY = {SH.Violation: Severity.ERROR, SH.Warning: Severity.WARNING, SH.Info: Severity.INFO}


@cache
def shapes() -> Graph:
    graph = Graph()
    graph.parse(data=files(__package__).joinpath("shapes.ttl").read_text(), format="turtle")
    return graph


def validate(annotations: Iterable[ToolAnnotation], vocabulary: Vocabulary) -> list[Finding]:
    """Structural findings found while reading, the SHACL results, then probes that cannot be loaded or break the
    contract. Unannotated tools are skipped."""
    annotations = [a for a in annotations if a.annotated or a.findings]
    findings = [finding for a in annotations for finding in a.findings]
    if not annotations:
        return findings
    # The vocabulary is merged in here rather than passed as pyshacl's ont_graph: pyshacl copies only
    # RDFS/OWL axioms from ont_graph and would drop annotations such as rd:appliesToFormat.
    data = Graph()
    for ann in annotations:
        _add_tool(data, ann)
    data += vocabulary.graph
    _conforms, results, _text = shacl_validate(
        data,
        shacl_graph=shapes(),
        inference="none",
        allow_warnings=True,
        advanced=True,
    )
    found = []
    for result in results.subjects(RDF.type, SH.ValidationResult):
        severity = SEVERITY.get(results.value(result, SH.resultSeverity), Severity.ERROR)
        focus = str(results.value(result, SH.focusNode))
        message = _closed_message(results, result) or str(results.value(result, SH.resultMessage) or "")
        value = results.value(result, SH.value)
        if value is not None:  # pyshacl fills {?value} only in SPARQL-based messages
            message = message.replace("{?value}", vocabulary.qname(str(value)))
        found.append(Finding(severity, focus, _shorten(message, vocabulary)))
    found.sort(key=lambda i: (i.location, i.severity, i.message))
    return findings + found + _broken_probes(annotations)


def _broken_probes(annotations: Iterable[ToolAnnotation]) -> list[Finding]:
    """Every probe that cannot be loaded or breaks the contract."""
    findings = []
    for ann in annotations:
        for var in ann.variables.values():
            if var.probe:
                try:
                    Probe.load(var.probe, ann.ports[var.port])
                except ProbeError as exc:
                    findings.append(Finding(Severity.ERROR, var.port, str(exc)))
    return findings


def _closed_message(results: Graph, result) -> str | None:
    if results.value(result, SH.sourceConstraintComponent) != SH.ClosedConstraintComponent:
        return None
    path = str(results.value(result, SH.resultPath))
    return f"unexpected key {path.rsplit('#', 1)[-1]!r}"


def _shorten(message: str, vocabulary: Vocabulary) -> str:
    """Replace full vocabulary IRIs in pyshacl's substituted messages with prefixed names."""
    for word in set(message.replace(",", " ").split()):
        iri = word.strip("<>()")
        short = vocabulary.qname(iri)
        if short != iri:
            message = message.replace(word, short)
    return message


# ---------------------------------------------------------------- the annotation as RDF


def _add_tool(graph: Graph, ann: ToolAnnotation) -> None:
    tool = URIRef(ann.tool_id)
    graph.add((tool, RDF.type, CWL.CommandLineTool))
    _add_ports(graph, tool, ann)
    _add_variables(graph, ann)
    _add_demands(graph, tool, ann)


def _add_ports(graph: Graph, tool: URIRef, ann: ToolAnnotation) -> None:
    for port in ann.ports.values():
        p = URIRef(port.id)
        graph.add((tool, CWL.inputs, p))
        graph.add((p, CWL.type, Literal(port.kind)))
        if port.items:
            graph.add((p, CWL.items, Literal(port.items)))
        for fmt in port.formats:
            graph.add((p, CWL["format"], _node(fmt)))


def _add_variables(graph: Graph, ann: ToolAnnotation) -> None:
    for var in ann.variables.values():
        v = _child(var.port, "complexityVariables", var.symbol)
        graph.add((URIRef(var.port), RD.complexityVariables, v))
        graph.add((v, RD.symbol, Literal(var.symbol)))
        graph.add((v, RD.measure, _node(var.measure)))
        for key, value in var.fields.items():
            graph.add((v, RD[key], _node(value)))


def _add_demands(graph: Graph, tool: URIRef, ann: ToolAnnotation) -> None:
    if not ann.demand_source:
        return
    rr = _child(ann.tool_id, "ResourceRequirement")
    graph.add((tool, CWL[ann.demand_source], rr))
    graph.add((rr, RDF.type, CWL.ResourceRequirement))
    for resource, terms in ann.demands.items():
        for index, term in enumerate(terms):
            t = _child(rr, resource.term, index)
            graph.add((rr, URIRef(resource.iri), t))
            for factor in term:
                f = _child(t, factor.variable)
                graph.add((t, RD.factors, f))
                graph.add((f, RD.variable, Literal(factor.variable)))
                graph.add((f, RD.complexity, _node(factor.complexity)))


def _child(base: str, *parts: object) -> URIRef:
    """`file:///t.cwl#raster` + ("complexityVariables", "n") -> `file:///t.cwl#raster/complexityVariables/n`."""
    sep = "/" if "#" in base else "#"
    return URIRef(base + sep + "/".join(quote(str(p), safe="") for p in parts))


def _node(value: Any) -> Node:
    """An absolute IRI as a node, anything else as a literal (nested structures as text, which the shapes reject)."""
    if isinstance(value, str) and _is_absolute_iri(value):
        return URIRef(value)
    return Literal(value if isinstance(value, str | int | float | bool) else str(value))


def _is_absolute_iri(value: str) -> bool:
    scheme, sep, rest = value.partition(":")
    return bool(sep and rest and scheme.isascii() and scheme[:1].isalpha() and " " not in value)
