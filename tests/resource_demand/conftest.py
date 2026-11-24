from __future__ import annotations

import atexit
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from sos_cwl.core.extension import Finding
from sos_cwl.extensions.resource_demand import Document, Vocabulary, validate
from sos_cwl.extensions.resource_demand.vocabulary import BASE, RD_VERSION, rd_graph, release_url

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = Path(__file__).resolve().parent / "cwl"
VOCABULARIES = Path(__file__).resolve().parent / "vocabularies"
EO_FORMATS = VOCABULARIES / "eo-formats.owl"  # eo-formats 1.2.0, the domain vocabulary of the examples
RD_OWL = VOCABULARIES / f"resource-demand-{RD_VERSION}.owl"  # the rd release the extension loads by default

# A temporary cache that already holds RD_OWL, so the tests need no network and never write into the repository.
_cache = Path(tempfile.mkdtemp(prefix="sos-cwl-cache-"))
atexit.register(shutil.rmtree, _cache, ignore_errors=True)
_release = _cache / release_url(RD_VERSION).removeprefix(BASE)
_release.parent.mkdir(parents=True)
shutil.copy(RD_OWL, _release)
os.environ["SOS_CWL_CACHE"] = str(_cache)

NAMESPACES = {
    "eo": "https://dfg-sos.github.io/ontologies/eo-formats#",
    "rd": "https://dfg-sos.github.io/ontologies/resource-demand#",
}


@pytest.fixture(scope="session")
def vocabulary() -> Vocabulary:
    """rd alone: enough for Big O."""
    return Vocabulary(rd_graph())


def make_tool(inputs: dict, ram: list | None = None, time: list | None = None, section: str = "hints", **extra) -> dict:
    requirement: dict = {"class": "ResourceRequirement"}
    if ram is not None:
        requirement["rd:ramDemand"] = ram
    if time is not None:
        requirement["rd:timeDemand"] = time
    tool = {
        "cwlVersion": "v1.2",
        "class": "CommandLineTool",
        "$namespaces": NAMESPACES,
        "$schemas": [EO_FORMATS.as_uri()],
        "baseCommand": ["true"],
        "inputs": inputs,
        "outputs": [],
    }
    if len(requirement) > 1:
        tool[section] = [requirement]
    tool.update(extra)
    return tool


def factor(variable: str, complexity: str = "rd:Linear") -> tuple[str, str]:
    return variable, complexity


def term(*factors: tuple[str, str]) -> dict:
    return dict(factors)


def raster(*variables: dict, fmt: str | None = "eo:GeoTIFF", type_: object = "File") -> dict:
    port: dict = {"type": type_, "rd:complexityVariables": list(variables)}
    if fmt is not None:
        port["format"] = fmt
    return port


@pytest.fixture
def check(tmp_path: Path):
    """Write a tool document, load it with cwltool and return the validation findings."""

    def run(tool: dict) -> list[Finding]:
        path = tmp_path / "tool.cwl"
        path.write_text(json.dumps(tool, indent=1))  # JSON is valid YAML
        doc = Document.load(path)
        return validate(doc.annotations, doc.vocabulary())

    return run


def messages(findings: list[Finding], severity: str | None = None) -> list[str]:
    return [i.message for i in findings if severity is None or i.severity == severity]
