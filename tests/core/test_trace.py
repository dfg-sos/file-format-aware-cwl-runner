import json

import pytest

from sos_cwl.core.trace import RunInfo, Trace


@pytest.fixture
def run_info() -> RunInfo:
    return RunInfo(versions={"cwltool": "1"}, extensions=["format-validation"], arguments={"mode": "basic"})


def test_trace_starts_with_the_run_record(tmp_path, run_info):
    path = tmp_path / "t.jsonl"
    trace = Trace(str(path), run_info, run_id="r1")
    trace.write("check", step="s", duration_ms=1.5)
    trace.close()
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["record"] for r in lines] == ["run", "check"]
    assert all(r["run_id"] == "r1" for r in lines)
    assert lines[0]["versions"] == {"cwltool": "1"}
    assert lines[0]["extensions"] == ["format-validation"]
    assert lines[0]["arguments"] == {"mode": "basic"}


def test_disabled_trace_writes_nothing(run_info):
    trace = Trace(None, run_info)
    trace.write("check", step="s")
    assert not trace.enabled
    trace.close()
