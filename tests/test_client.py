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
    parse_server_timing,
    split_format_iri,
)
from format_aware_cwl.policy import Policy
from format_aware_cwl.timing import TimingLog

BASE = "http://ffs.test"
EO = "https://dfg-sos.github.io/ontologies/eo-formats#"
GEOTIFF = EO + "GeoTIFF"
OK = {"status": "SUCCESS", "errors": [], "warnings": [], "infos": []}


def upload(mode):
    return f"{BASE}/api/v1/validate/{mode}"


def local(mode):
    return f"{BASE}/api/v1/validate/{mode}/local"


@pytest.fixture
def client():
    c = FormatServiceClient(BASE)  # transfer=auto
    yield c
    c.close()


@pytest.fixture
def uploader():
    c = FormatServiceClient(BASE, transfer="upload")
    yield c
    c.close()


@pytest.fixture
def tif(tmp_path):
    p = tmp_path / "out.tif"
    p.write_bytes(b"II*\x00")
    return FileRef(str(p), "out.tif")


def shapefile(tmp_path):
    refs = []
    for ext in ("shp", "shx", "dbf", "prj"):
        (tmp_path / f"roads.{ext}").write_bytes(b"x")
        refs.append(FileRef(str(tmp_path / f"roads.{ext}"), f"roads.{ext}"))
    return refs


@pytest.mark.parametrize(
    "iri,expected",
    [
        (GEOTIFF, (EO, "GeoTIFF")),
        ("http://edamontology.org/format_1929", ("http://edamontology.org/", "format_1929")),
    ],
)
def test_split_format_iri_keeps_separator(iri, expected):
    assert split_format_iri(iri) == expected


@pytest.mark.parametrize("bad", ["GeoTIFF", EO])
def test_split_format_iri_rejects(bad):
    with pytest.raises(ValueError):
        split_format_iri(bad)


def test_parse_server_timing():
    assert parse_server_timing("receive;dur=1.8, validate;dur=812.3") == {"receive": 1.8, "validate": 812.3}
    assert parse_server_timing(None) == {}
    assert parse_server_timing("cache;desc=x, bad;dur=n/a") == {}


def test_unknown_mode_is_error(client, tif):
    assert client.validate(tif, GEOTIFF, mode="deep").status == ERROR


# --- basic: paths only, no file transfer --------------------------------------------------------------------------


@respx.mock
def test_basic_sends_only_paths(uploader, tmp_path):
    refs = [FileRef(str(tmp_path / f"roads.{e}"), f"roads.{e}") for e in ("shp", "shx")]  # files need not exist
    route = respx.post(upload("basic")).mock(
        return_value=httpx.Response(200, json=OK, headers={"Server-Timing": "validate;dur=0.2"})
    )
    result = uploader.validate(refs[0], EO + "Shapefile", secondaries=refs[1:], expected_metadata={"crs": "x"})
    assert (result.status, result.transfer, result.server_timing) == (SUCCESS, None, {"validate": 0.2})
    assert json.loads(route.calls.last.request.content) == {  # no metadata outside full mode
        "ontology_namespace": EO,
        "format_identifier": "Shapefile",
        "file_path": str(tmp_path / "roads.shp"),
        "secondary_file_paths": [str(tmp_path / "roads.shx")],
    }


@respx.mock
def test_basic_remote_file_sends_url_path(client):
    route = respx.post(upload("basic")).mock(return_value=httpx.Response(200, json=OK))
    client.validate(FileRef("https://data.test/a/out.tif", "out.tif"), GEOTIFF)
    assert json.loads(route.calls.last.request.content)["file_path"] == "/a/out.tif"


# --- structural / full by path --------------------------------------------------------------------


@respx.mock
def test_full_local_sends_paths_and_metadata(client, tmp_path):
    refs = shapefile(tmp_path)
    route = respx.post(local("full")).mock(
        return_value=httpx.Response(200, json=OK, headers={"Server-Timing": "resolve;dur=0.1, validate;dur=5.5"})
    )
    result = client.validate(
        refs[0], EO + "Shapefile", mode="full", secondaries=refs[1:], expected_metadata={"crs": "EPSG:4326", "x": ""}
    )
    assert (result.status, result.transfer, result.server_timing) == (
        SUCCESS,
        "local",
        {"resolve": 0.1, "validate": 5.5},
    )
    assert json.loads(route.calls.last.request.content) == {
        "ontology_namespace": EO,
        "format_identifier": "Shapefile",
        "expected_metadata": {"crs": "EPSG:4326"},
        "file_path": str(tmp_path / "roads.shp"),
        "secondary_file_paths": [str(tmp_path / f"roads.{e}") for e in ("shx", "dbf", "prj")],
    }


@respx.mock
def test_auto_falls_back_to_upload_outside_shared_dirs(client, tif):
    by_path = respx.post(local("structural")).mock(return_value=httpx.Response(403, json={"detail": "outside"}))
    uploaded = respx.post(upload("structural")).mock(return_value=httpx.Response(200, json=OK))
    for _ in range(2):
        assert client.validate(tif, GEOTIFF, mode="structural").transfer == "upload"
    assert (by_path.call_count, uploaded.call_count) == (2, 2)  # other paths may still be shared


@respx.mock
def test_auto_remembers_disabled_local_validation(client, tif):
    detail = {"detail": "Local validation is disabled: no shared directories configured"}
    by_path = respx.post(local("structural")).mock(return_value=httpx.Response(403, json=detail))
    respx.post(upload("structural")).mock(return_value=httpx.Response(200, json=OK))
    for _ in range(3):
        assert client.validate(tif, GEOTIFF, mode="structural").status == SUCCESS
    assert by_path.call_count == 1


@respx.mock
def test_forced_local_does_not_fall_back(tif):
    respx.post(local("full")).mock(return_value=httpx.Response(403, json={"detail": "disabled"}))
    uploaded = respx.post(upload("full"))
    result = FormatServiceClient(BASE, transfer="local").validate(tif, GEOTIFF, mode="full")
    assert (result.status, result.transfer) == (ERROR, "local")
    assert uploaded.call_count == 0


@respx.mock
def test_auto_uploads_remote_files_directly(client):
    respx.get("https://data.test/a/out.tif").mock(return_value=httpx.Response(200, content=b"REMOTE"))
    route = respx.post(upload("full")).mock(return_value=httpx.Response(200, json=OK))
    by_path = respx.post(local("full"))
    client.validate(FileRef("https://data.test/a/out.tif", "out.tif"), GEOTIFF, mode="full")
    assert b"REMOTE" in route.calls.last.request.content
    assert by_path.call_count == 0


# --- structural / full upload --------------------------------------------------------------------


@pytest.mark.parametrize("status", ["SUCCESS", "FAILURE", "UNCERTAIN", "success"])
@respx.mock
def test_upload_statuses_and_fields(uploader, tif, status):
    route = respx.post(upload("full")).mock(
        return_value=httpx.Response(
            200,
            json={**OK, "status": status, "errors": [{"message": "boom"}]},
            headers={"Server-Timing": "receive;dur=2"},
        )
    )
    result = uploader.validate(tif, GEOTIFF, mode="full", expected_metadata={"crs": "EPSG:4326"})
    assert (result.status, result.transfer, result.server_timing) == (status.upper(), "upload", {"receive": 2.0})
    body = route.calls.last.request.content
    assert b'name="format_identifier"\r\n\r\nGeoTIFF' in body
    assert b'name="ontology_namespace"\r\n\r\nhttps://dfg-sos.github.io/ontologies/eo-formats#' in body
    assert b'name="expected_metadata"\r\n\r\n{"crs": "EPSG:4326"}' in body
    assert b'filename="out.tif"' in body
    assert b'name="mode"' not in body


@respx.mock
def test_upload_shapefile_sends_secondaries(uploader, tmp_path):
    refs = shapefile(tmp_path)
    route = respx.post(upload("structural")).mock(return_value=httpx.Response(200, json=OK))
    uploader.validate(refs[0], EO + "Shapefile", mode="structural", secondaries=refs[1:])
    body = route.calls.last.request.content
    assert body.count(b'name="secondary_files"') == 3
    assert b'name="file"; filename="roads.shp"' in body
    assert b"expected_metadata" not in body


@pytest.mark.parametrize(
    "detail,status",
    [
        ("Format identifier 'GeoZarr' not supported for ontology namespace 'x'", UNCERTAIN),  # no validator
        ("Unsupported metadata keys ['geometry_type'], supported keys are ['crs'].", ERROR),  # workflow annotation
        ("Invalid projection: EPSG:99999999", ERROR),
    ],
)
@respx.mock
def test_http_400(uploader, tif, detail, status):
    respx.post(upload("full")).mock(return_value=httpx.Response(400, json={"detail": detail}))
    result = uploader.validate(tif, GEOTIFF, mode="full")
    assert result.status == status
    assert detail[:20] in result.message


@pytest.mark.parametrize("transfer", ["upload", "local"])
@respx.mock
def test_service_down(tif, transfer):
    respx.post(upload("full")).mock(side_effect=httpx.ConnectError("refused"))
    respx.post(local("full")).mock(side_effect=httpx.ConnectError("refused"))
    assert FormatServiceClient(BASE, transfer=transfer).validate(tif, GEOTIFF, mode="full").status == ERROR


# --- compatibility -----------------------------------------------------------------------------


@respx.mock
def test_compatibility_cached(client):
    route = respx.post(f"{BASE}/api/v1/compatibility").mock(
        return_value=httpx.Response(200, json={"compatible": False, "message": "no"})
    )
    for _ in range(2):
        r = client.compatibility(GEOTIFF, EO + "Shapefile", "http://onto.test/eo.owl")
        assert r.compatible is False
    assert route.call_count == 1
    assert json.loads(route.calls.last.request.content) == {
        "expected_format": GEOTIFF,
        "actual_format": EO + "Shapefile",
        "ontology_schema_url": "http://onto.test/eo.owl",
    }


@respx.mock
def test_compatibility_unknown_format(client):
    detail = {"message": "Format(s) not defined", "unknown_formats": [EO + "GeoTIF"]}
    respx.post(f"{BASE}/api/v1/compatibility").mock(return_value=httpx.Response(422, json={"detail": detail}))
    r = client.compatibility(EO + "GeoTIF", EO + "COG", "http://onto.test/eo.owl")
    assert (r.compatible, r.unknown_formats) == (None, [EO + "GeoTIF"])


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(502, json={"detail": "cannot fetch"}),
        httpx.Response(422, json={"detail": [{"loc": ["body"], "msg": "field required"}]}),  # invalid body
    ],
)
@respx.mock
def test_compatibility_service_error_not_cached(client, response):
    route = respx.post(f"{BASE}/api/v1/compatibility").mock(return_value=response)
    r = client.compatibility("a/b", "a/c", "u")
    assert (r.compatible, r.unknown_formats) == (None, [])
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
