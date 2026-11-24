"""Read parametric dependency annotations from a loaded CWL CommandLineTool.

Annotation (see the resource-demand vocabulary):

    inputs:
      raster:
        type: File
        format: eo:GeoTIFF
        rd:complexityVariables: [{symbol: n, measure: eo:PixelCount}]
    hints:
      ResourceRequirement:
        rd:ramDemand:  [{n: rd:Linear}]         # a sum of terms, each {symbol: complexity class, ...}
        rd:timeDemand: [{n: rd:Linearithmic}]  # whose entries are multiplied

Extraction only reads the structure; whether the values are allowed is checked by the SHACL
shapes (`shapes.ttl`). Values are kept as found, with namespace prefixes expanded, so invalid
values still reach validation and are reported there.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urljoin

from sos_cwl.core.extension import Finding, Severity
from sos_cwl.core.loading import expand

from .vocabulary import RD

COMPLEXITY_VARIABLES = str(RD.complexityVariables)
RESOURCE_REQUIREMENT = "ResourceRequirement"


class Resource(StrEnum):
    RAM = "ram"
    TIME = "time"

    @property
    def term(self) -> str:
        """`ramDemand`, the rd: property of the demand."""
        return f"{self}Demand"

    @property
    def iri(self) -> str:
        return str(RD[self.term])


class DemandSource(StrEnum):
    """Where the demands are read from, in order of precedence (as in CWL)."""

    REQUIREMENTS = "requirements"
    HINTS = "hints"


@dataclass(frozen=True)
class Port:
    """What validation needs to know about an input parameter."""

    id: str
    kind: str  # File | Directory | int | long | float | double | string | boolean | array | enum | record | union
    items: str | None = None  # item kind of an array
    formats: tuple[str, ...] = ()  # format IRIs, or an expression string

    @classmethod
    def from_param(cls, param: Mapping[str, Any]) -> Port:
        """An input or output parameter of a loaded CWL document."""
        kind, items = _kind(param.get("type"))
        fmt = param.get("format")
        formats = tuple(fmt) if isinstance(fmt, list) else (fmt,) if isinstance(fmt, str) else ()
        return cls(id=str(param["id"]), kind=kind, items=items, formats=formats)

    @property
    def type(self) -> str:
        """The type as written in CWL: `File`, `File[]`, ..."""
        return f"{self.items}[]" if self.kind == "array" else self.kind


@dataclass(frozen=True)
class Variable:
    port: str  # input id
    symbol: str  # unique within the tool
    measure: str  # IRI of a rd:Measure subclass (checked by the SHACL shapes)
    fields: Mapping[str, Any]  # the other keys as written: probe (+ anything unexpected)

    @property
    def probe(self) -> str | None:
        value = self.fields.get("probe")
        return value if isinstance(value, str) else None


@dataclass(frozen=True)
class Factor:
    variable: str  # symbol of a complexity variable (declared? checked by the SHACL shapes)
    complexity: str  # IRI of a rd:ComplexityClass subclass (checked by the SHACL shapes)


Term = tuple[Factor, ...]  # multiplied; no factors: a constant


@dataclass
class ToolAnnotation:
    tool_id: str
    ports: dict[str, Port]
    variables: dict[str, Variable]  # by symbol
    demands: dict[Resource, list[Term]]  # terms (summed)
    demand_source: DemandSource | None  # None: no demands
    findings: list[Finding]  # structural problems found while reading

    @property
    def annotated(self) -> bool:
        return bool(self.variables or self.demands)

    @classmethod
    def from_tool(cls, tool: Mapping[str, Any], namespaces: Mapping[str, str]) -> ToolAnnotation:
        """Read the annotation of one CommandLineTool, given as cwltool's loaded document (`process.tool`)."""
        tool_id = str(tool.get("id", ""))
        findings: list[Finding] = []
        ports: dict[str, Port] = {}
        variables: dict[str, Variable] = {}

        for param in tool.get("inputs", []):
            port = Port.from_param(param)
            ports[port.id] = port
            if (declared := param.get(COMPLEXITY_VARIABLES)) is None:
                continue
            for var in _variables(port.id, declared, tool_id, namespaces, findings):
                if var.symbol in variables:
                    msg = f"symbol {var.symbol} is declared more than once in this tool"
                    findings.append(Finding(Severity.ERROR, port.id, msg))
                else:
                    variables[var.symbol] = var

        demands, source = _demands(tool, tool_id, namespaces, findings)
        return cls(tool_id, ports, variables, demands, source, findings)


def _variables(
    port: str, declared: Any, tool_id: str, namespaces: Mapping[str, str], findings: list[Finding]
) -> list[Variable]:
    """The rd:complexityVariables of one input; malformed variables are reported and skipped."""
    if not isinstance(declared, list):
        findings.append(Finding(Severity.ERROR, port, "rd:complexityVariables must be a list of {symbol, measure}"))
        return []
    variables = []
    for index, item in enumerate(declared):
        if not isinstance(item, Mapping):
            findings.append(Finding(Severity.ERROR, port, f"rd:complexityVariables[{index}] must be a mapping"))
            continue
        fields = {key: expand(value, namespaces) for key, value in item.items()}
        symbol, measure = fields.pop("symbol", None), fields.pop("measure", None)
        if not isinstance(symbol, str) or not isinstance(measure, str):
            msg = f"rd:complexityVariables[{index}] needs a symbol and a measure"
            findings.append(Finding(Severity.ERROR, port, msg))
            continue
        if isinstance(fields.get("probe"), str):
            fields["probe"] = urljoin(tool_id, fields["probe"])
        variables.append(Variable(port, symbol, measure, fields))
    return variables


def _kind(cwl_type: Any) -> tuple[str, str | None]:
    """Types as cwltool loads them: `File[]` is already {type: array, items: File}, `File?` [null, File]."""
    if isinstance(cwl_type, str):
        return cwl_type, None
    if isinstance(cwl_type, list):
        options = [t for t in cwl_type if t != "null"]
        return _kind(options[0]) if len(options) == 1 else ("union", None)
    if isinstance(cwl_type, Mapping):
        if cwl_type.get("type") == "array":
            return "array", _kind(cwl_type.get("items"))[0]
        return str(cwl_type.get("type")), None
    return "unknown", None


def _demands(
    tool: Mapping[str, Any], tool_id: str, namespaces: Mapping[str, str], findings: list[Finding]
) -> tuple[dict[Resource, list[Term]], DemandSource | None]:
    """Demands from the ResourceRequirement cwltool would use: `requirements` before `hints`, the last one first."""
    found = [(source, req) for source in DemandSource for req in reversed(tool.get(source, [])) if _has_demands(req)]
    if not found:
        return {}, None
    source, req = found[0]
    if found[-1][0] != source:
        findings.append(
            Finding(Severity.WARNING, tool_id, "demands in both requirements and hints; the hints are ignored")
        )
    demands = {r: _terms(req[r.iri], f"rd:{r.term}", tool_id, namespaces, findings) for r in Resource if r.iri in req}
    return demands, source


def _has_demands(req: Any) -> bool:
    return isinstance(req, Mapping) and req.get("class") == RESOURCE_REQUIREMENT and any(r.iri in req for r in Resource)


def _terms(raw: Any, where: str, tool_id: str, namespaces: Mapping[str, str], findings: list[Finding]) -> list[Term]:
    """`[{n: rd:Linear}, {d: rd:Quadratic}]` -> the terms n and d^2; malformed terms are reported and skipped."""
    if not isinstance(raw, list):
        findings.append(Finding(Severity.ERROR, tool_id, f"{where} must be a list of terms {{symbol: complexity}}"))
        return []
    terms = []
    for index, term in enumerate(raw):
        if not isinstance(term, Mapping) or not all(isinstance(v, str) for v in term.values()):
            findings.append(
                Finding(Severity.ERROR, tool_id, f"{where}[{index}] must be a mapping {{symbol: complexity}}")
            )
            continue
        terms.append(tuple(Factor(str(symbol), expand(cls, namespaces)) for symbol, cls in term.items()))
    return terms
