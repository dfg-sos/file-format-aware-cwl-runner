import json
from pathlib import Path

import httpx
import pytest
import respx
from cwl_utils.parser import load_document_by_uri

from sos_cwl.core.extension import Severity
from sos_cwl.extensions.format_validation import lint
from sos_cwl.extensions.format_validation.client import FormatServiceClient

CWL = Path(__file__).parent / "cwl"
SERVICE = "http://ffs.test"
EO = "https://dfg-sos.github.io/ontologies/eo-formats#"
# actual -> set of expected formats it is compatible with (beyond itself)
SUBCLASS = {"COG": {"GeoTIFF"}, "Shapefile": {"Vector"}}
KNOWN = {"COG", "GeoTIFF", "Shapefile", "Vector"}


def fake_compat(request):
    body = json.loads(request.content)
    actual, expected = body["actual_format"].rsplit("#", 1)[-1], body["expected_format"].rsplit("#", 1)[-1]
    unknown = [body[k] for k in ("expected_format", "actual_format") if body[k].rsplit("#", 1)[-1] not in KNOWN]
    if unknown:
        return httpx.Response(422, json={"detail": {"message": "not defined", "unknown_formats": unknown}})
    ok = actual == expected or expected in SUBCLASS.get(actual, set())
    return httpx.Response(200, json={"compatible": ok, "message": ""})


def mock_service(compat=fake_compat):
    respx.post(f"{SERVICE}/api/v1/compatibility").mock(side_effect=compat)


def statuses(path, ontologies, compat=fake_compat):
    """(source, sink) -> status of every checked connection."""
    with respx.mock:
        mock_service(compat)
        checked = lint.Linter(FormatServiceClient(SERVICE)).check(load_document_by_uri(str(path)), ontologies)
    return {(c.source, c.sink): c.status for c in checked}


def run_lint(path, ontology=None, compat=fake_compat):
    with respx.mock:
        mock_service(compat)
        return lint.Linter(FormatServiceClient(SERVICE), ontology).lint(str(path))


def test_connection_statuses():
    found = statuses(CWL / "wf_lint.cwl", ["http://o"])
    assert found[("roads", "consume/raster")] == "incompatible"
    assert found[("roads", "inner/r")] == "incompatible"
    assert found[("inner/run/r", "inner/run/c2/raster")] == "compatible"  # COG ⊂ GeoTIFF, any-of
    assert found[("inner/size", "out")] == "unannotated"


def test_lint_uses_the_schemas_and_reports_problems_as_findings():
    ontologies = set()

    def recording(request):
        ontologies.add(json.loads(request.content)["ontology_schema_url"])
        return fake_compat(request)

    result = run_lint(CWL / "wf_lint.cwl", compat=recording)
    assert ontologies == {"http://ontology.test/eo-formats.owl"}
    findings = {f.location: f.severity for f in result.findings}
    assert findings["roads -> consume/raster"] == Severity.ERROR
    assert findings["inner/size -> out"] == Severity.WARNING
    assert any("inner/run/r -> inner/run/c2/raster" in line for line in result.lines)  # compatible


def test_ontology_override_and_service_error():
    def down(request):
        assert json.loads(request.content)["ontology_schema_url"] == "http://ontology/eo-formats.owl"
        return httpx.Response(502, json={"detail": "cannot fetch"})

    result = run_lint(CWL / "wf_lint.cwl", ontology=["http://ontology/eo-formats.owl"], compat=down)
    finding = next(f for f in result.findings if f.location == "roads -> consume/raster")
    assert finding.severity == Severity.ERROR and "cannot fetch" in finding.message


@pytest.mark.parametrize(
    "source,sink,status",
    [
        ([EO + "Shapefile"], [EO + "Vector"], "compatible"),  # Shapefile -> Vector
        ([EO + "Shapefile"], [EO + "GeoTIFF"], "incompatible"),
        ([EO + "GeoTIFF", EO + "Shapefile"], [EO + "GeoTIFF"], "incompatible"),  # every source must fit
        (["$(inputs.f.format)"], [EO + "GeoTIFF"], "expression"),
        ([], [EO + "GeoTIFF"], "unannotated"),
        ([EO + "GeoTIF"], [EO + "GeoTIFF"], "unknown-format"),
    ],
)
def test_pair_rules(source, sink, status):
    class Port:
        def __init__(self, fmts):
            self.format = fmts or None
            self.type_ = "File"

    with respx.mock:
        mock_service()
        linter = lint.Linter(FormatServiceClient(SERVICE))
        assert linter._check("wf", "#src", Port(source), "#sink", Port(sink), ["http://o"]).status == status


def test_any_ontology_may_confirm_compatibility():
    def per_ontology(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={"compatible": body["ontology_schema_url"] == "http://second", "message": ""})

    class Port:
        type_ = "File"

        def __init__(self, fmt):
            self.format = fmt

    with respx.mock:
        mock_service(per_ontology)
        linter = lint.Linter(FormatServiceClient(SERVICE))
        check = linter._check(
            "wf", "#a", Port(EO + "Shapefile"), "#b", Port(EO + "Vector"), ["http://first", "http://second"]
        )
        assert check.status == "compatible"
        asked = [json.loads(call.request.content)["ontology_schema_url"] for call in respx.calls]
    assert asked == ["http://first", "http://second"]
