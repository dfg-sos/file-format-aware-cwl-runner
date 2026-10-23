"""Acceptance tests against a running SOS File Format Service.

    docker run -d -p 8000:8000 -v "$PWD/tests/fixtures/mappings:/app/mappings:ro" \
        ghcr.io/dfg-sos/file-format-service:latest
    uv run pytest -m service

The service ships no format mappings; tests/fixtures/mappings/eo-formats.json provides the one for
the EO formats ontology.

The CWL fixtures load the EO formats ontology from
https://dfg-sos.github.io/ontologies/eo-formats.owl (`$schemas`), which both cwltool and the
service fetch. SOS_FFS_ONTOLOGY_URL overrides the URL the linter sends to
the service (e.g. file:///ontology/eo-formats.owl for a mounted copy).

By-path validation (/validate/local) is tested only if SOS_FFS_TEST_SHARED_DIR names a host
directory that the service shares (SOS_FFS_SHARED_DIRS); otherwise `auto` falls back to upload.
"""

import json
import os
from pathlib import Path

import httpx
import pytest
from cwltool.main import main as vanilla_main

from format_aware_cwl import cli, lint

pytestmark = pytest.mark.service

FIXTURES = Path(__file__).parent / "fixtures"
SERVICE = os.environ.get("SOS_FFS_URL", "http://localhost:8000")
ONTOLOGY_OVERRIDE = os.environ.get("SOS_FFS_ONTOLOGY_URL")
SHARED_DIR = os.environ.get("SOS_FFS_TEST_SHARED_DIR")


@pytest.fixture(scope="module", autouse=True)
def service_up():
    try:
        httpx.get(f"{SERVICE}/health", timeout=3).raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(f"format service not reachable at {SERVICE}: {exc}")


def args(*names):
    return [str(FIXTURES / n) for n in names]


# (workflow, job, vanilla exit, basic exit, full exit)
MATRIX = [
    ("a_relabel.cwl", "jobs/a1.yml", 0, 1, 1),  # A1: wrong extension
    ("a_relabel.cwl", "jobs/a2.yml", 0, 0, 1),  # A2: right extension, wrong content
    ("b_crs.cwl", "jobs/b.yml", 0, 0, 1),  # B: wrong CRS
    ("c_geometry.cwl", "jobs/c_points.yml", 0, 0, 1),  # C: wrong geometry type
    ("c_geometry.cwl", "jobs/c_roads.yml", 0, 0, 0),  # C control
    ("d_shapefile_to_vector.cwl", "jobs/d.yml", 0, 0, 0),  # multi-file Shapefile, subclass accepted
    ("e_unannotated.cwl", None, 0, 0, 0),  # E
]


@pytest.mark.parametrize("wf,job,vanilla,basic,full", MATRIX, ids=[f"{w}:{j}" for w, j, *_ in MATRIX])
def test_fixture_matrix(tmp_path, wf, job, vanilla, basic, full):
    files = args(wf, *([job] if job else []))
    common = ["--quiet", "--outdir", str(tmp_path / "out")]
    assert vanilla_main(argsl=[*common, *files]) == vanilla
    for mode, expected in (("basic", basic), ("full", full)):
        rc = cli.main([*common, "--format-service-url", SERVICE, "--format-validation-mode", mode, *files])
        assert rc == expected, f"{mode} mode"


def test_warn_mode_never_aborts(tmp_path):
    rc = cli.main(
        [
            "--quiet",
            "--outdir",
            str(tmp_path),
            "--format-service-url",
            SERVICE,
            "--format-validation",
            "warn",
            "--format-validation-mode",
            "full",
            *args("a_relabel.cwl", "jobs/a2.yml"),
        ]
    )
    assert rc == 0


def test_timing_log_records(tmp_path):
    log = tmp_path / "t.jsonl"
    cli.main(
        [
            "--quiet",
            "--outdir",
            str(tmp_path / "out"),
            "--format-service-url",
            SERVICE,
            "--format-validation",
            "warn",
            "--format-timing-log",
            str(log),
            *args("a_relabel.cwl", "jobs/a2.yml"),
        ]
    )
    records = [json.loads(line) for line in log.read_text().splitlines()]
    checks = [(r["step"], r["direction"], r["result"]) for r in records if r["record"] == "check"]
    assert checks == [("relabel", "post", "SUCCESS"), ("consume", "pre", "SUCCESS")]
    assert {r["step"] for r in records if r["record"] == "main"} == {"relabel", "consume"}
    assert all(r["duration_ms"] > 0 and r["size_bytes"] > 0 for r in records if r["record"] == "check")


@pytest.mark.parametrize(
    "wf,expected,rc",
    [
        ("d_shapefile_to_geotiff.cwl", "incompatible", 1),
        ("d_shapefile_to_vector.cwl", "compatible", 0),
    ],
)
def test_linter_fixture_d(capsys, wf, expected, rc):
    argv = [
        "--format-service-url",
        SERVICE,
        *(["--format-ontology-url", ONTOLOGY_OVERRIDE] if ONTOLOGY_OVERRIDE else []),
    ]
    assert lint.main([*argv, "--json", *args(wf)]) == rc
    findings = json.loads(capsys.readouterr().out)["findings"]
    assert {(f["source"], f["sink"]): f["status"] for f in findings}[("roads", "consume/data")] == expected
    assert lint.main([*argv, *args(wf)]) == rc  # text output
    assert expected.upper() in capsys.readouterr().out


def test_linter_official_online_edam(capsys):
    """The service fetches the official EDAM itself; EO formats are not part of it (422 -> unknown-format)."""
    rc = lint.main(["--format-service-url", SERVICE, "--json", *args("f_edam_online.cwl")])
    findings = {f["sink"]: f["status"] for f in json.loads(capsys.readouterr().out)["findings"]}
    assert findings == {"align/s": "compatible", "climate/c": "incompatible", "gis/g": "unknown-format"}
    assert rc == 1


def _docker_available() -> bool:
    import subprocess

    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(not _docker_available(), reason="docker daemon not available")
def test_container_jobs_are_checked(tmp_path):
    files = args("a_relabel_docker.cwl", "jobs/a2.yml")
    common = ["--quiet", "--outdir", str(tmp_path / "out"), "--format-service-url", SERVICE]
    log = tmp_path / "t.jsonl"
    assert cli.main([*common, "--format-validation", "warn", "--format-timing-log", str(log), *files]) == 0
    records = [json.loads(line) for line in log.read_text().splitlines()]
    checks = [(r["step"], r["direction"], r["result"]) for r in records if r["record"] == "check"]
    assert checks == [("relabel", "post", "SUCCESS"), ("consume", "pre", "SUCCESS")]
    assert {r["step"] for r in records if r["record"] == "main"} == {"relabel", "consume"}
    # A2 content error is caught in the containerised producer
    assert cli.main([*common, "--format-validation-mode", "full", *files]) == 1


@pytest.mark.skipif(not SHARED_DIR, reason="SOS_FFS_TEST_SHARED_DIR not set")
def test_local_transfer_on_shared_storage(tmp_path):
    import shutil
    import tempfile

    shared = Path(tempfile.mkdtemp(dir=SHARED_DIR))
    try:
        for name in ("roads.shp", "roads.shx", "roads.dbf", "roads.prj"):
            shutil.copy(FIXTURES / "data" / name, shared / name)
        job = shared / "job.yml"
        job.write_text(
            f'roads: {{class: File, location: {shared / "roads.shp"}, format: "https://dfg-sos.github.io/ontologies/eo-formats#Shapefile"}}\n'
        )
        log = tmp_path / "t.jsonl"
        rc = cli.main(
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
                "full",  # basic transfers no files; structural/full read them in place
                "--format-timing-log",
                str(log),
                *args("d_shapefile_to_vector.cwl"),
                str(job),
            ]
        )
        assert rc == 0
        checks = [json.loads(line) for line in log.read_text().splitlines() if '"check"' in line]
        assert [(c["transfer"], c["result"]) for c in checks] == [("local", "SUCCESS")]
        assert "validate" in checks[0]["server_timing"]
    finally:
        shutil.rmtree(shared, ignore_errors=True)
