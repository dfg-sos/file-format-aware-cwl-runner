"""Probes: the contract checked at design time, and running them at run time."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from sos_cwl.core import lint, runner
from sos_cwl.extensions.resource_demand import ResourceDemandExtension, probes
from sos_cwl.extensions.resource_demand.annotations import Port, Variable

from .conftest import EO_FORMATS, EXAMPLES

PROBE = EXAMPLES / "probes" / "cloud-fraction.cwl"
SCENE = Port(id="scene", kind="File")


def probe(
    tmp_path: Path,
    inputs: str = "scene: File",
    outputs: str = "value: {type: float, outputBinding: {outputEval: $(0.5)}}",
    cls: str = "CommandLineTool",
) -> str:
    path = tmp_path / "probe.cwl"
    path.write_text(
        f'cwlVersion: v1.2\nclass: {cls}\nbaseCommand: ["true"]\n'
        f"requirements: {{InlineJavascriptRequirement: {{}}}}\n"
        f"inputs: {{{inputs}}}\noutputs: {{{outputs}}}\n"
    )
    return path.as_uri()


# ---- design time: the contract


def test_the_example_probe_keeps_the_contract():
    loaded = probes.Probe.load(PROBE.as_uri(), SCENE)
    assert (loaded.input, loaded.output) == ("scene", "value")


@pytest.mark.parametrize(
    ("inputs", "outputs", "message"),
    [
        ("scene: File, extra: int", None, "needs exactly one input, has 2"),
        ("n: int", None, "input is int, the annotated input is File"),
        (None, "a: float, b: float", "needs exactly one output, has 2"),
        (None, "value: string", "output must be a number (int, long, float, double), is string"),
    ],
)
def test_contract(tmp_path, inputs, outputs, message):
    args = {k: v for k, v in {"inputs": inputs, "outputs": outputs}.items() if v}
    with pytest.raises(probes.ProbeError, match=re.escape(message)):
        probes.Probe.load(probe(tmp_path, **args), SCENE)


def test_array_inputs_must_match():
    files = Port(id="files", kind="array", items="File")
    with pytest.raises(probes.ProbeError, match=r"input is File, the annotated input is File\[\]"):
        probes.Probe.load(PROBE.as_uri(), files)


def test_a_missing_probe(tmp_path):
    with pytest.raises(probes.ProbeError, match="probe missing.cwl cannot be loaded"):
        probes.Probe.load((tmp_path / "missing.cwl").as_uri(), SCENE)


def test_lint_reports_a_broken_probe(tmp_path, capsys):
    tool = tmp_path / "cloud-mask.cwl"
    broken = probe(tmp_path, outputs="value: string")
    text = (EXAMPLES / "cloud-mask.cwl").read_text().replace("probes/cloud-fraction.cwl", broken)
    tool.write_text(text.replace("../vocabularies/eo-formats.owl", EO_FORMATS.as_uri()))
    assert lint.main([str(tool)], extensions=[ResourceDemandExtension()]) == 1
    assert "probe probe.cwl: output must be a number" in capsys.readouterr().out


# ---- run time


def run(tmp_path, *argv):
    trace = tmp_path / "t.jsonl"
    rc = runner.main(
        [
            "--quiet",
            "--no-container",
            "--outdir",
            str(tmp_path / "out"),
            "--trace",
            str(trace),
            "--resource-demand",
            "log",
            *argv,
            str(EXAMPLES / "cloud-mask.cwl"),
            str(EXAMPLES / "jobs" / "cloud-mask.yml"),
        ],
        extensions=[ResourceDemandExtension()],
    )
    [demand] = [r for r in map(json.loads, trace.read_text().splitlines()) if r["record"] == "demand"]
    return rc, demand["variables"]


def test_probes_are_run_on_request(tmp_path):
    rc, variables = run(tmp_path, "--resource-demand-probes")
    assert rc == 0
    c = variables["c"]
    assert (c["port"], c["value"]) == ("scene", 0.25)
    assert c["probe_ms"] > 0 and "error" not in c
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["masked.tif"]  # nothing of the probe


def test_without_the_flag_derived_measures_have_no_value(tmp_path):
    rc, variables = run(tmp_path)
    assert rc == 0
    assert variables["c"]["value"] is None and "probe_ms" not in variables["c"]


def test_a_failing_probe_does_not_fail_the_job(tmp_path, monkeypatch):
    def fail(self, iri, port, value):
        raise probes.ProbeError("probe cloud-fraction.cwl failed: boom")

    monkeypatch.setattr(probes.Prober, "_call", fail)
    rc, variables = run(tmp_path, "--resource-demand-probes")
    assert rc == 0
    assert variables["c"] == {
        "port": "scene",
        "measure": variables["c"]["measure"],
        "value": None,
        "probe_ms": variables["c"]["probe_ms"],
        "error": "probe cloud-fraction.cwl failed: boom",
    }


def test_each_value_is_probed_once(tmp_path, monkeypatch):
    calls = []

    def count(self, iri, port, value):
        calls.append(iri)
        return 1

    monkeypatch.setattr(probes.Prober, "_call", count)
    prober = probes.Prober(probes.RuntimeContext())
    scene = {"class": "File", "location": "file:///data/a.tif", "path": "/var/lib/cwl/stg1/a.tif"}
    var = Variable("scene", "c", "rd:DerivedMeasure", {"probe": "p.cwl"})
    prober.take(var, SCENE, scene)
    prober.take(var, SCENE, {**scene, "path": "/var/lib/cwl/stg2/a.tif"})  # staged elsewhere, same file
    prober.take(var, SCENE, {**scene, "location": "file:///data/b.tif"})
    prober.close()
    assert len(calls) == 2


def test_probes_need_log(capsys):
    with pytest.raises(SystemExit) as exc:
        runner.main(
            ["--resource-demand-probes", str(EXAMPLES / "cloud-mask.cwl"), str(EXAMPLES / "jobs" / "cloud-mask.yml")],
            extensions=[ResourceDemandExtension()],
        )
    assert exc.value.code == 2
    assert "--resource-demand-probes needs --resource-demand log" in capsys.readouterr().err
