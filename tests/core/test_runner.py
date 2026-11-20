"""The core's cwltool hooks, with a recording extension (no real extension involved)."""

from __future__ import annotations

import json
from importlib.metadata import distribution, entry_points, version
from pathlib import Path

import pytest
from packaging.requirements import Requirement

from sos_cwl.core import runner
from sos_cwl.core.extension import Extension, UsageError, Verdict

CWL = Path(__file__).parent / "cwl"
WF = [str(CWL / "wf.cwl"), str(CWL / "job.yml")]


class Recorder(Extension):
    """Records every hook call; fails configure, a step's before/after hook, or close on request."""

    def __init__(
        self,
        name="recorder",
        *,
        active=True,
        wants_outputs=True,
        fail_configure=False,
        fail_before=(),
        fail_after=(),
        fail_close=False,
    ):
        self.name = name
        self._active = active
        self._wants_outputs = wants_outputs
        self.fail_configure = fail_configure
        self.fail_before = set(fail_before)
        self.fail_after = set(fail_after)
        self.fail_close = fail_close
        self.calls: list[tuple] = []
        self.resolved: list[str] = []  # content of File inputs, read through ctx.resolve

    def add_arguments(self, group):
        group.add_argument(f"--{self.name}-level", dest=f"{self.name}_level", default="low")

    def configure(self, args):
        self.calls.append(("configure", getattr(args, f"{self.name}_level")))
        if self.fail_configure:
            raise UsageError("level does not fit")

    @property
    def active(self):
        return self._active

    @property
    def wants_outputs(self):
        return self._wants_outputs

    def on_tool(self, tool):
        self.calls.append(("tool", Path(tool.tool["id"]).name))

    def before_job(self, ctx):
        ctx.record("seen", inputs=sorted(ctx.inputs))
        self.calls.append(("before", ctx.step, sorted(ctx.inputs)))
        if "file" in ctx.inputs:
            self.resolved.append(Path(ctx.resolve(ctx.inputs["file"]["location"])).read_text())
        return Verdict.fail(f"before {ctx.step} failed") if ctx.step in self.fail_before else Verdict.ok()

    def after_job(self, ctx, outputs):
        self.calls.append(("after", ctx.step, sorted(outputs)))
        return Verdict.fail(f"after {ctx.step} failed") if ctx.step in self.fail_after else Verdict.ok()

    def close(self):
        self.calls.append(("close",))
        if self.fail_close:
            raise RuntimeError("close failed")

    def hooks(self, kind):
        return [c[1:] for c in self.calls if c[0] == kind]


def run(tmp_path, *extensions, argv=(), trace=True):
    trace_path = tmp_path / "t.jsonl"
    args = ["--quiet", "--no-container", "--outdir", str(tmp_path / "out")]
    if trace:
        args += ["--trace", str(trace_path)]
    rc = runner.main([*args, *argv, *WF], extensions=list(extensions))
    return rc, read_trace(trace_path) if trace else []


def read_trace(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def of(records, kind):
    return [r for r in records if r["record"] == kind]


def test_hooks_are_called_per_tool_and_job(tmp_path):
    ext = Recorder()
    rc, _ = run(tmp_path, ext, argv=["--recorder-level", "high"])
    assert rc == 0
    assert ext.calls[0] == ("configure", "high")
    assert sorted(ext.hooks("tool")) == [("consume.cwl",), ("produce.cwl",)]
    assert ext.hooks("before") == [("produce", ["text"]), ("consume", ["file"])]
    assert ext.hooks("after") == [("produce", ["out"]), ("consume", ["count"])]
    assert ext.resolved == ["hello\n"]  # consume's input: the file produce wrote
    assert ext.calls[-1] == ("close",)


def test_usage_error_in_configure_is_an_argument_error(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        run(tmp_path, Recorder(fail_configure=True), trace=False)
    assert exc.value.code == 2
    assert "recorder: level does not fit" in capsys.readouterr().err


def test_before_job_failure_skips_the_job(tmp_path):
    ext = Recorder(fail_before={"produce"})
    rc, records = run(tmp_path, ext)
    assert rc == 1
    assert ext.hooks("before") == [("produce", ["text"])]  # consume never got its input
    assert ext.hooks("after") == []
    assert of(records, "job") == []  # no job ran


def test_after_job_failure_fails_the_step(tmp_path):
    ext = Recorder(fail_after={"produce"})
    rc, records = run(tmp_path, ext)
    assert rc == 1
    assert [r["step"] for r in of(records, "job")] == ["produce"]
    assert ext.hooks("before") == [("produce", ["text"])]


def test_inactive_extension_gets_no_job_hooks(tmp_path):
    ext = Recorder(active=False, fail_before={"produce"})
    rc, _ = run(tmp_path, ext)
    assert rc == 0
    assert len(ext.hooks("tool")) == 2  # load-time hook still runs
    assert ext.hooks("before") == ext.hooks("after") == []


def test_after_job_only_when_wanted(tmp_path):
    ext = Recorder(wants_outputs=False)
    assert run(tmp_path, ext)[0] == 0
    assert len(ext.hooks("before")) == 2
    assert ext.hooks("after") == []


def test_every_extension_is_asked(tmp_path):
    first, second = Recorder(), Recorder("second", fail_before={"consume"})
    rc, _ = run(tmp_path, first, second)
    assert rc == 1
    assert first.hooks("before") == second.hooks("before") == [("produce", ["text"]), ("consume", ["file"])]


def test_every_close_runs_and_the_trace_is_complete(tmp_path):
    failing, other = Recorder(fail_close=True), Recorder("other")
    with pytest.raises(RuntimeError, match="close failed"):
        run(tmp_path, failing, other)
    assert failing.calls[-1] == other.calls[-1] == ("close",)
    assert len(of(read_trace(tmp_path / "t.jsonl"), "job")) == 2


def test_trace_records_the_run(tmp_path):
    rc, records = run(tmp_path, Recorder(), argv=["--run-id", "r1"])
    assert rc == 0
    run_record = records[0]
    assert run_record["record"] == "run"
    assert all(r["run_id"] == "r1" for r in records)
    assert run_record["extensions"] == ["recorder"]
    # the core records the arguments of its own and of every extension's group, nothing of cwltool's
    assert run_record["arguments"] == {"trace": str(tmp_path / "t.jsonl"), "run_id": "r1", "recorder_level": "low"}
    assert run_record["versions"]["cwltool"] == version("cwltool")
    jobs = of(records, "job")
    assert [r["step"] for r in jobs] == ["produce", "consume"]
    assert all(r["job"].startswith(r["step"]) and r["duration_ms"] > 0 for r in jobs)
    hooks = [(r["extension"], r["hook"], r["step"], r["failed"]) for r in of(records, "hook")]
    assert hooks == [
        ("recorder", "before_job", "produce", False),
        ("recorder", "after_job", "produce", False),
        ("recorder", "before_job", "consume", False),
        ("recorder", "after_job", "consume", False),
    ]
    # an extension's own observations get the step and job added
    seen = [(r["step"], r["inputs"]) for r in of(records, "seen")]
    assert seen == [("produce", ["text"]), ("consume", ["file"])]
    assert all(r["job"] for r in of(records, "seen"))


def test_cached_jobs_are_traced_and_skip_hooks(tmp_path):
    cache = ["--cachedir", str(tmp_path / "cache")]
    run(tmp_path, Recorder(), argv=cache)
    ext = Recorder()
    rc, records = run(tmp_path, ext, argv=cache)
    assert rc == 0
    assert sorted(r["step"] for r in of(records, "cached")) == ["consume", "produce"]
    assert ext.hooks("before") == []


def test_without_extensions_it_is_plain_cwltool_and_jobs_are_still_timed(tmp_path):
    rc, records = run(tmp_path)
    assert rc == 0
    assert [r["step"] for r in of(records, "job")] == ["produce", "consume"]
    assert of(records, "hook") == []


def test_versions_of_the_core_and_of_installed_extensions():
    assert set(runner.package_versions([Recorder()])) == set(runner.CORE_PACKAGES)  # not installed: core only
    versions = runner.package_versions(runner.load_extensions())
    assert versions["cwltool"] == version("cwltool")
    dist = distribution("sos-cwl-runner")  # ships the installed extensions
    requirements = {r.name for r in map(Requirement, dist.requires or []) if r.marker is None}
    assert {dist.name, *requirements} <= set(versions)


def test_installed_extensions_are_found_in_entry_point_name_order():
    found = runner.load_extensions()
    assert all(isinstance(e, Extension) for e in found)
    eps = sorted(entry_points(group=runner.ENTRY_POINT_GROUP), key=lambda ep: ep.name)
    assert eps and [type(e) for e in found] == [ep.load() for ep in eps]
