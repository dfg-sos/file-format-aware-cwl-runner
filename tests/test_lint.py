import json
from pathlib import Path

import httpx
import pytest
import respx

from format_aware_cwl import lint
from format_aware_cwl.client import FormatServiceClient

CWL = Path(__file__).parent / "cwl"
SERVICE = "http://ffs.test"
EDAM = "http://edamontology.org/"
# actual -> set of expected formats it is compatible with (beyond itself)
SUBCLASS = {"format_4100": {"format_4109"}, "format_4119": {"format_4126"}}
KNOWN = {"format_4100", "format_4109", "format_4119", "format_4126"}


def fake_compat(request):
    body = json.loads(request.content)
    actual, expected = body["actual_format"].rsplit("/", 1)[-1], body["expected_format"].rsplit("/", 1)[-1]
    ok = actual == expected or expected in SUBCLASS.get(actual, set())
    return httpx.Response(200, json={"compatible": ok, "message": ""})


def fake_info(request):
    fmt = json.loads(request.content)["format_identifier"].rsplit("/", 1)[-1]
    return httpx.Response(200, json={"label": fmt if fmt in KNOWN else None, "parents": []})


def mock_service(compat=fake_compat):
    respx.post(f"{SERVICE}/api/v1/compatibility").mock(side_effect=compat)
    respx.post(f"{SERVICE}/api/v1/format-info").mock(side_effect=fake_info)


def run_lint(capsys, *argv, compat=fake_compat):
    with respx.mock:
        mock_service(compat)
        rc = lint.main(["--format-service-url", SERVICE, "--json", *argv, str(CWL / "wf_lint.cwl")])
    out = json.loads(capsys.readouterr().out)
    return rc, {(f["source"], f["sink"]): f for f in out["findings"]}, out


def test_lint_findings(capsys):
    rc, findings, out = run_lint(capsys)
    assert rc == 1
    assert out["ontologies"] == ["http://ontology.test/edam.owl"]
    assert findings[("roads", "consume/raster")]["status"] == "incompatible"
    assert findings[("roads", "inner/r")]["status"] == "incompatible"
    assert findings[("inner/run/r", "inner/run/c2/raster")]["status"] == "compatible"  # COG ⊂ GeoTIFF, any-of
    assert findings[("inner/size", "out")]["status"] == "unannotated"


def test_ontology_override_and_service_error(capsys):
    def down(request):
        assert json.loads(request.content)["ontology_schema_url"] == "http://ontology/edam.owl"
        return httpx.Response(502, json={"detail": "cannot fetch"})

    rc, findings, _ = run_lint(capsys, "--format-ontology-url", "http://ontology/edam.owl", compat=down)
    assert rc == 1
    assert findings[("roads", "consume/raster")]["status"] == "error"


@pytest.mark.parametrize(
    "source,sink,status",
    [
        ([EDAM + "format_4119"], [EDAM + "format_4126"], "compatible"),  # Shapefile -> vector
        ([EDAM + "format_4119"], [EDAM + "format_4109"], "incompatible"),
        ([EDAM + "format_4109", EDAM + "format_4119"], [EDAM + "format_4109"], "incompatible"),  # every source must fit
        (["$(inputs.f.format)"], [EDAM + "format_4109"], "expression"),
        ([], [EDAM + "format_4109"], "unannotated"),
        ([EDAM + "format_9999"], [EDAM + "format_4109"], "unknown-format"),
    ],
)
def test_pair_rules(source, sink, status):
    class Port:
        def __init__(self, fmts):
            self.format = fmts or None
            self.type_ = "File"

    with respx.mock:
        mock_service()
        linter = lint.Linter(FormatServiceClient(SERVICE), ["http://o"])
        assert linter._check("wf", "#src", Port(source), "#sink", Port(sink)).status == status


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
        linter = lint.Linter(FormatServiceClient(SERVICE), ["http://first", "http://second"])
        finding = linter._check("wf", "#a", Port(EDAM + "format_4119"), "#b", Port(EDAM + "format_4126"))
    assert finding.status == "compatible"
    assert [d["ontology"] for d in finding.details] == ["http://first", "http://second"]
