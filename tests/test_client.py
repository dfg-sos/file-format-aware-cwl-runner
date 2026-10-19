import json

import httpx
import pytest
import respx

from format_aware_cwl.client import (
    ERROR,
    FAILURE,
    SUCCESS,
    UNCERTAIN,
    FileRef,
    FormatServiceClient,
    ValidationResult,
    split_format_iri,
)
from format_aware_cwl.policy import Policy
from format_aware_cwl.timing import TimingLog

BASE = "http://ffs.test"
GEOTIFF = "http://edamontology.org/format_4109"


@pytest.fixture
def client():
    c = FormatServiceClient(BASE)
    yield c
    c.close()


@pytest.fixture
def tif(tmp_path):
    p = tmp_path / "out.tif"
    p.write_bytes(b"II*\x00")
    return FileRef(str(p), "out.tif")


@pytest.mark.parametrize(
    "iri,expected",
    [
        (GEOTIFF, ("http://edamontology.org", "format_4109")),
        ("https://example.org/onto#fmt_1", ("https://example.org/onto", "fmt_1")),
    ],
)
def test_split_format_iri(iri, expected):
    assert split_format_iri(iri) == expected


@pytest.mark.parametrize("bad", ["format_4109", "http://edamontology.org/"])
def test_split_format_iri_rejects(bad):
    with pytest.raises(ValueError):
        split_format_iri(bad)


@pytest.mark.parametrize("status", ["SUCCESS", "FAILURE", "UNCERTAIN", "success"])
@respx.mock
def test_validate_statuses(client, tif, status):
    route = respx.post(f"{BASE}/api/v1/validate").mock(
        return_value=httpx.Response(
            200, json={"status": status, "errors": [{"message": "boom"}], "warnings": [], "infos": []}
        )
    )
    result = client.validate(tif, GEOTIFF, mode="full", expected_crs="EPSG:4326")
    assert result.status == status.upper()
    body = route.calls.last.request.content
    assert b'name="format_identifier"\r\n\r\nformat_4109' in body
    assert b'name="ontology_namespace"\r\n\r\nhttp://edamontology.org' in body
    assert b'name="mode"\r\n\r\nfull' in body
    assert b'name="expected_crs"\r\n\r\nEPSG:4326' in body
    assert b'filename="out.tif"' in body
    assert b"expected_geometry_type" not in body


@respx.mock
def test_validate_shapefile_sends_secondaries(client, tmp_path):
    refs = []
    for ext in ("shp", "shx", "dbf", "prj"):
        (tmp_path / f"roads.{ext}").write_bytes(b"x")
        refs.append(FileRef(str(tmp_path / f"roads.{ext}"), f"roads.{ext}"))
    route = respx.post(f"{BASE}/api/v1/validate").mock(return_value=httpx.Response(200, json={"status": "SUCCESS"}))
    client.validate(refs[0], "http://edamontology.org/format_4119", secondaries=refs[1:])
    body = route.calls.last.request.content
    assert body.count(b'name="secondary_files"') == 3
    assert b'name="file"; filename="roads.shp"' in body


@respx.mock
def test_validate_http_400_is_error(client, tif):
    respx.post(f"{BASE}/api/v1/validate").mock(return_value=httpx.Response(400, json={"detail": "unmapped format"}))
    result = client.validate(tif, GEOTIFF)
    assert result.status == ERROR
    assert "unmapped format" in result.message


@respx.mock
def test_validate_service_down(client, tif):
    respx.post(f"{BASE}/api/v1/validate").mock(side_effect=httpx.ConnectError("refused"))
    assert client.validate(tif, GEOTIFF).status == ERROR


@respx.mock
def test_validate_remote_file_is_fetched_and_uploaded(client):
    respx.get("https://data.test/a/out.tif").mock(return_value=httpx.Response(200, content=b"REMOTE"))
    route = respx.post(f"{BASE}/api/v1/validate").mock(return_value=httpx.Response(200, json={"status": "SUCCESS"}))
    client.validate(FileRef("https://data.test/a/out.tif", "out.tif"), GEOTIFF)
    assert b"REMOTE" in route.calls.last.request.content


@respx.mock
def test_compatibility_cached(client):
    route = respx.post(f"{BASE}/api/v1/compatibility").mock(
        return_value=httpx.Response(200, json={"compatible": False, "message": "no"})
    )
    for _ in range(2):
        r = client.compatibility(GEOTIFF, "http://edamontology.org/format_4119", "http://onto.test/edam.owl")
        assert r.compatible is False
    assert route.call_count == 1
    assert json.loads(route.calls.last.request.content) == {
        "expected_format": GEOTIFF,
        "actual_format": "http://edamontology.org/format_4119",
        "ontology_schema_url": "http://onto.test/edam.owl",
    }


@respx.mock
def test_compatibility_service_error_not_cached(client):
    route = respx.post(f"{BASE}/api/v1/compatibility").mock(return_value=httpx.Response(502, json={"detail": "x"}))
    assert client.compatibility("a/b", "a/c", "u").compatible is None
    client.compatibility("a/b", "a/c", "u")
    assert route.call_count == 2


@pytest.mark.parametrize(
    "policy,status,fatal",
    [
        (Policy(validation="fail"), FAILURE, True),
        (Policy(validation="fail"), SUCCESS, False),
        (Policy(validation="fail"), UNCERTAIN, False),
        (Policy(validation="fail", uncertain="fail"), UNCERTAIN, True),
        (Policy(validation="fail"), ERROR, True),
        (Policy(validation="fail", service_error="warn"), ERROR, False),
        (Policy(validation="warn"), FAILURE, False),
        (Policy(validation="off"), FAILURE, False),
    ],
)
def test_policy(policy, status, fatal):
    assert policy.is_fatal(ValidationResult(status)) is fatal


def test_timing_log(tmp_path):
    path = tmp_path / "t.jsonl"
    log = TimingLog(str(path), run_id="r1")
    log.run_record({"mode": "basic"}, "http://x")
    log.write("check", step="s", duration_ms=1.5)
    log.close()
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["record"] for r in lines] == ["run", "check"]
    assert all(r["run_id"] == "r1" for r in lines)
    assert lines[0]["versions"]["cwltool"] == "3.3.20260925135507"
