"""cwltool-sos end to end with a mocked format service (no network, no containers)."""

import json
from pathlib import Path

import httpx
import pytest
import respx

from format_aware_cwl import cli

CWL = Path(__file__).parent / "cwl"
SERVICE = "http://ffs.test"


def run(tmp_path, *argv, status="FAILURE"):
    log = tmp_path / "t.jsonl"
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(f"{SERVICE}/api/v1/validate").mock(
            return_value=httpx.Response(200, json={"status": status, "errors": [{"message": "not a GeoTIFF"}]})
        )
        rc = cli.main(
            [
                "--quiet",
                "--no-container",
                "--outdir",
                str(tmp_path / "out"),
                "--format-service-url",
                SERVICE,
                "--format-timing-log",
                str(log),
                *argv,
            ]
        )
    records = [json.loads(line) for line in log.read_text().splitlines()]
    return rc, route, records


def by_type(records, kind):
    return [r for r in records if r["record"] == kind]


def test_post_check_failure_fails_workflow(tmp_path):
    rc, route, records = run(tmp_path, str(CWL / "wf.cwl"))
    assert rc == 1
    checks = by_type(records, "check")
    assert [(c["step"], c["direction"], c["result"]) for c in checks] == [("produce", "post", "FAILURE")]
    assert route.call_count == 1  # consume never ran


def test_warn_mode_completes_and_checks_both_directions(tmp_path):
    rc, _, records = run(tmp_path, "--format-validation", "warn", str(CWL / "wf.cwl"))
    assert rc == 0
    assert [(c["step"], c["direction"]) for c in by_type(records, "check")] == [("produce", "post"), ("consume", "pre")]
    assert {m["step"] for m in by_type(records, "main")} == {"produce", "consume"}
    assert by_type(records, "skip")[0]["port"] == "size"


def test_success_passes(tmp_path):
    rc, _, _ = run(tmp_path, str(CWL / "wf.cwl"), status="SUCCESS")
    assert rc == 0


@pytest.mark.parametrize("check,expected", [("pre", [("consume", "pre")]), ("post", [("produce", "post")])])
def test_direction_selection(tmp_path, check, expected):
    _, _, records = run(tmp_path, "--format-validation", "warn", "--format-check", check, str(CWL / "wf.cwl"))
    assert [(c["step"], c["direction"]) for c in by_type(records, "check")] == expected


def test_pre_check_failure_skips_command(tmp_path):
    bad = tmp_path / "bad.tif"
    bad.write_text("{}")
    job = tmp_path / "job.json"
    job.write_text(
        json.dumps({"raster": {"class": "File", "path": str(bad), "format": "http://edamontology.org/format_4109"}})
    )
    rc, _, records = run(tmp_path, str(CWL / "wf_in.cwl"), str(job))
    assert rc == 1
    assert by_type(records, "main") == []


def test_full_mode_sends_extension_fields(tmp_path):
    _, route, _ = run(tmp_path, "--format-validation-mode", "full", str(CWL / "produce.cwl"))
    assert b'name="expected_crs"\r\n\r\nEPSG:4326' in route.calls.last.request.content


def test_unannotated_ports_are_skipped(tmp_path):
    rc, route, records = run(tmp_path, str(CWL / "unannotated.cwl"))
    assert rc == 0 and route.call_count == 0
    assert by_type(records, "skip")[0]["port"] == "plain"


def test_off_is_plain_cwltool(tmp_path):
    rc, route, records = run(tmp_path, "--format-validation", "off", str(CWL / "wf.cwl"))
    assert rc == 0 and route.call_count == 0
    assert by_type(records, "check") == [] and len(by_type(records, "main")) == 2
