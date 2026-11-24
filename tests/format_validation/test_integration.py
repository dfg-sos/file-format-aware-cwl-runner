"""Acceptance tests against a running SOS File Format Service.

    docker run -d -p 8000:8000 -v "$PWD/tests/format_validation/fixtures/mappings:/app/mappings:ro" \
        ghcr.io/dfg-sos/file-format-service-eo:latest
    uv run pytest -m integration

These tests carry the `integration` marker and are deselected in a plain `uv run pytest`
(see `addopts` in pyproject.toml). The service ships no format mappings;
tests/format_validation/fixtures/mappings/eo-formats.json provides the one for the EO formats ontology.

The CWL fixtures load the EO formats ontology from
https://dfg-sos.github.io/ontologies/eo-formats.owl (`$schemas`), which both cwltool and the
service fetch. SOS_FFS_ONTOLOGY_URL overrides the URL the linter sends to
the service (e.g. file:///ontology/eo-formats.owl for a mounted copy).

Validation modes use separate endpoints: basic sends only file paths (/validate/basic),
metadata and content upload the files (/validate/<mode>) or let the service read them in place
(/validate/<mode>/local). By-path validation is tested only if SOS_FFS_TEST_SHARED_DIR names a host
directory that the service shares (SOS_FFS_SHARED_DIRS); otherwise `auto` falls back to upload.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx
import pytest
from cwl_utils.parser import load_document_by_uri
from cwltool.main import main as vanilla_main

from sos_cwl.core import lint as core_lint
from sos_cwl.core import runner as core_runner
from sos_cwl.extensions.format_validation import FormatValidationExtension, lint
from sos_cwl.extensions.format_validation.client import FormatServiceClient

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parent / "fixtures"


def runner_main(argv):
    """The runner with this extension only, validating (`--format-validation fail`) unless `argv` says otherwise."""
    return core_runner.main(["--format-validation", "fail", *argv], extensions=[FormatValidationExtension()])


SERVICE = os.environ.get("SOS_FFS_URL", "http://localhost:8000")
ONTOLOGY_OVERRIDE = os.environ.get("SOS_FFS_ONTOLOGY_URL")
SHARED_DIR = os.environ.get("SOS_FFS_TEST_SHARED_DIR")
EO = "https://dfg-sos.github.io/ontologies/eo-formats#"


@pytest.fixture(scope="module", autouse=True)
def service_up():
    try:
        httpx.get(f"{SERVICE}/health", timeout=3).raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(f"format service not reachable at {SERVICE}: {exc}")


def args(*names):
    return [str(FIXTURES / n) for n in names]


def run(tmp_path, *argv):
    """Run the format-aware runner; returns (exit code, check records of the run trace)."""
    log = tmp_path / "t.jsonl"
    rc = runner_main(
        ["--quiet", "--outdir", str(tmp_path / "out"), "--format-service-url", SERVICE] + ["--trace", str(log), *argv]
    )
    checks = [r for r in map(json.loads, log.read_text().splitlines()) if r["record"] == "check"]
    return rc, checks


def test_mapping_fixture_matches_ontology_and_is_accepted():
    """Every mapped key is a class of the hosted ontology, and the service loads the mapping
    (a single unknown validator ID makes it answer 500 to every validation request)."""
    from rdflib import OWL, RDF, Graph

    graph = Graph().parse("https://dfg-sos.github.io/ontologies/eo-formats.owl")
    classes = {str(c).removeprefix(EO) for c in graph.subjects(RDF.type, OWL.Class)}
    mapping = json.loads((FIXTURES / "mappings" / "eo-formats.json").read_text())
    assert mapping["ontology_uri"] == EO
    assert set(mapping["mappings"]) <= classes
    resp = httpx.post(
        f"{SERVICE}/api/v1/validate/basic",
        json={"file_path": "/x/a.tif", "ontology_namespace": EO, "format_identifier": "GeoTIFF"},
    )
    assert resp.status_code == 200, resp.text


# (workflow, job, vanilla exit, basic exit, metadata exit, content exit), default policy (fail)
MATRIX = [
    ("a_relabel.cwl", "jobs/a1.yml", 0, 1, 1, 1),  # A1: wrong extension
    ("a_relabel.cwl", "jobs/a2.yml", 0, 0, 1, 1),  # A2: right extension, wrong content
    ("b_crs.cwl", "jobs/b.yml", 0, 0, 1, 1),  # B: wrong CRS
    ("c_geometry.cwl", "jobs/c_points.yml", 0, 0, 1, 1),  # C: wrong geometry type
    ("c_geometry.cwl", "jobs/c_roads.yml", 0, 0, 0, 0),  # C control
    ("c_geometry.cwl", "jobs/c_mixed.yml", 0, 0, 0, 1),  # C mixed: one stray Point among the LineStrings
    ("d_shapefile_to_vector.cwl", "jobs/d.yml", 0, 0, 0, 0),  # multi-file Shapefile, subclass accepted
    ("e_unannotated.cwl", None, 0, 0, 0, 0),  # E
    ("g_unsupported_format.cwl", None, 0, 0, 0, 0),  # G: UNCERTAIN, only a warning by default
    ("h_invalid_metadata.cwl", "jobs/b.yml", 0, 0, 1, 1),  # H: sos: fields are only sent (and rejected) beyond basic
    ("i_input.cwl", "jobs/i1.yml", 0, 1, 1, 1),  # I1: workflow input with the wrong extension
    ("i_input.cwl", "jobs/i2.yml", 0, 0, 1, 1),  # I2: workflow input, right extension, wrong content
    ("i_input.cwl", "jobs/j.yml", 0, 0, 1, 1),  # J: GeoTIFF truncated in its header
    ("i_input.cwl", "jobs/k.yml", 0, 0, 0, 1),  # K: GeoTIFF truncated in its pixel data
    ("i_input.cwl", "jobs/i_ok.yml", 0, 0, 0, 0),  # I control
]


@pytest.mark.parametrize("wf,job,vanilla,basic,metadata,content", MATRIX, ids=[f"{w}:{j}" for w, j, *_ in MATRIX])
def test_fixture_matrix(tmp_path, wf, job, vanilla, basic, metadata, content):
    files = args(wf, *([job] if job else []))
    common = ["--quiet", "--outdir", str(tmp_path / "out")]
    assert vanilla_main(argsl=[*common, *files]) == vanilla
    for mode, expected in (("basic", basic), ("metadata", metadata), ("content", content)):
        rc = runner_main([*common, "--format-service-url", SERVICE, "--format-validation-mode", mode, *files])
        assert rc == expected, f"{mode} mode"


def test_unsupported_format_is_uncertain(tmp_path):
    rc, checks = run(tmp_path, *args("g_unsupported_format.cwl"))
    assert rc == 0
    assert [(c["result"], "not supported" in c["message"]) for c in checks] == [("UNCERTAIN", True)]
    rc, _ = run(tmp_path, "--format-uncertain", "fail", *args("g_unsupported_format.cwl"))
    assert rc == 1


def test_invalid_metadata_is_an_error(tmp_path):
    metadata = ["--format-validation-mode", "metadata"]
    rc, checks = run(tmp_path, *metadata, *args("h_invalid_metadata.cwl", "jobs/b.yml"))
    assert rc == 1
    assert [(c["result"], "geometry_type" in c["message"]) for c in checks] == [("ERROR", True)]
    rc, _ = run(tmp_path, *metadata, "--format-service-error", "warn", *args("h_invalid_metadata.cwl", "jobs/b.yml"))
    assert rc == 0


@pytest.mark.parametrize(
    "wf,job,message",
    [
        ("i_input.cwl", "jobs/k.yml", "pixel data"),  # header intact, pixel strip cut off
        ("c_geometry.cwl", "jobs/c_mixed.yml", "incompatible with expected type"),  # 1 of 3 features is a Point
    ],
)
def test_content_mode_reads_beyond_metadata(tmp_path, wf, job, message):
    """Faults past the header: metadata mode only opens the file (and samples geometry types), so it passes;
    content mode reads every pixel or feature and fails."""
    (tmp_path / "metadata").mkdir()
    rc, checks = run(tmp_path / "metadata", "--format-validation-mode", "metadata", *args(wf, job))
    assert rc == 0
    assert {(c["mode"], c["result"]) for c in checks} == {("metadata", "SUCCESS")}
    (tmp_path / "content").mkdir()
    rc, checks = run(tmp_path / "content", "--format-validation-mode", "content", *args(wf, job))
    assert rc == 1
    assert [(c["mode"], c["result"], message in c["message"]) for c in checks] == [("content", "FAILURE", True)]


@pytest.mark.parametrize("mode", ["metadata", "content"])
def test_upload_multi_file_format(tmp_path, mode):
    argv = ["--format-validation-mode", mode, "--format-file-transfer", "upload"]
    rc, checks = run(tmp_path, *argv, *args("d_shapefile_to_vector.cwl", "jobs/d.yml"))
    assert rc == 0
    assert [(c["transfer"], c["result"]) for c in checks] == [("upload", "SUCCESS")]
    assert {"receive", "validate"} <= set(checks[0]["server_timing"])


def test_warn_mode_never_aborts(tmp_path):
    rc = runner_main(
        [
            "--quiet",
            "--outdir",
            str(tmp_path),
            "--format-service-url",
            SERVICE,
            "--format-validation",
            "warn",
            "--format-validation-mode",
            "metadata",
            *args("a_relabel.cwl", "jobs/a2.yml"),
        ]
    )
    assert rc == 0


def test_trace_records(tmp_path):
    log = tmp_path / "t.jsonl"
    runner_main(
        [
            "--quiet",
            "--outdir",
            str(tmp_path / "out"),
            "--format-service-url",
            SERVICE,
            "--format-validation",
            "warn",
            "--trace",
            str(log),
            *args("a_relabel.cwl", "jobs/a2.yml"),
        ]
    )
    records = [json.loads(line) for line in log.read_text().splitlines()]
    checks = [r for r in records if r["record"] == "check"]
    assert [(c["step"], c["phase"], c["result"]) for c in checks] == [
        ("relabel", "post", "SUCCESS"),
        ("consume", "pre", "SUCCESS"),
    ]
    assert {r["step"] for r in records if r["record"] == "job"} == {"relabel", "consume"}
    assert all(c["duration_ms"] > 0 and c["size_bytes"] > 0 for c in checks)
    # basic mode (default): only paths are sent, no file transfer
    assert all(c["mode"] == "basic" and c["transfer"] is None and "validate" in c["server_timing"] for c in checks)


def lint_statuses(wf):
    """(source, sink) -> status of every connection, checked by the running service."""
    doc = load_document_by_uri(args(wf)[0])
    ontologies = [ONTOLOGY_OVERRIDE] if ONTOLOGY_OVERRIDE else doc.loadingOptions.schemas
    client = FormatServiceClient(SERVICE)
    try:
        return {(c.source, c.sink): c.status for c in lint.Linter(client).check(doc, ontologies)}
    finally:
        client.close()


@pytest.mark.parametrize(
    "wf,expected,rc",
    [
        ("d_shapefile_to_geotiff.cwl", "incompatible", 1),
        ("d_shapefile_to_vector.cwl", "compatible", 0),
    ],
)
def test_linter_fixture_d(capsys, wf, expected, rc):
    assert lint_statuses(wf)[("roads", "consume/data")] == expected
    argv = [
        "--format-service-url",
        SERVICE,
        *(["--format-ontology-url", ONTOLOGY_OVERRIDE] if ONTOLOGY_OVERRIDE else []),
    ]
    assert core_lint.main([*argv, *args(wf)], extensions=[FormatValidationExtension()]) == rc
    assert "roads -> consume/data" in capsys.readouterr().out


def test_linter_official_online_edam():
    """The service fetches the official EDAM itself; EO formats are not part of it (422 -> unknown-format)."""
    found = {sink: status for (_, sink), status in lint_statuses("f_edam_online.cwl").items()}
    assert found == {"align/s": "compatible", "climate/c": "incompatible", "gis/g": "unknown-format"}


def _docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(not _docker_available(), reason="docker daemon not available")
def test_container_jobs_are_checked(tmp_path):
    files = args("a_relabel_docker.cwl", "jobs/a2.yml")
    common = ["--quiet", "--outdir", str(tmp_path / "out"), "--format-service-url", SERVICE]
    log = tmp_path / "t.jsonl"
    assert runner_main([*common, "--format-validation", "warn", "--trace", str(log), *files]) == 0
    records = [json.loads(line) for line in log.read_text().splitlines()]
    checks = [(r["step"], r["phase"], r["result"]) for r in records if r["record"] == "check"]
    assert checks == [("relabel", "post", "SUCCESS"), ("consume", "pre", "SUCCESS")]
    assert {r["step"] for r in records if r["record"] == "job"} == {"relabel", "consume"}
    # A2 content error is caught in the containerised producer
    assert runner_main([*common, "--format-validation-mode", "metadata", *files]) == 1


@pytest.mark.skipif(not SHARED_DIR, reason="SOS_FFS_TEST_SHARED_DIR not set")
@pytest.mark.parametrize("mode", ["metadata", "content"])
def test_local_transfer_on_shared_storage(tmp_path, mode):
    shared = Path(tempfile.mkdtemp(dir=SHARED_DIR))
    try:
        for name in ("roads.shp", "roads.shx", "roads.dbf", "roads.prj"):
            shutil.copy(FIXTURES / "data" / name, shared / name)
        job = shared / "job.yml"
        job.write_text(
            f'roads: {{class: File, location: {shared / "roads.shp"}, format: "https://dfg-sos.github.io/ontologies/eo-formats#Shapefile"}}\n'
        )
        log = tmp_path / "t.jsonl"
        rc = runner_main(
            [
                "--quiet",
                "--outdir",
                str(shared / "out"),
                "--tmpdir-prefix",
                f"{shared}/",
                "--tmp-outdir-prefix",
                f"{shared}/",
                "--format-service-url",
                SERVICE,
                "--format-file-transfer",
                "local",
                "--format-validation-mode",
                mode,  # basic transfers no files; metadata/content read them in place
                "--trace",
                str(log),
                *args("d_shapefile_to_vector.cwl"),
                str(job),
            ]
        )
        assert rc == 0
        checks = [json.loads(line) for line in log.read_text().splitlines() if '"check"' in line]
        assert [(c["transfer"], c["result"]) for c in checks] == [("local", "SUCCESS")]
        assert {"resolve", "validate"} <= set(checks[0]["server_timing"])
    finally:
        shutil.rmtree(shared, ignore_errors=True)
