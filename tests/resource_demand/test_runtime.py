"""At run time: a `demand` record per job of an annotated tool, with the measured variables."""

from __future__ import annotations

import json

import pytest
from rdflib import Namespace

from sos_cwl.core import runner
from sos_cwl.extensions.resource_demand import ResourceDemandExtension
from sos_cwl.extensions.resource_demand.annotations import Port, Variable
from sos_cwl.extensions.resource_demand.measures import DirectMeasure
from sos_cwl.extensions.resource_demand.vocabulary import RD

from .conftest import EXAMPLES

EO = Namespace("https://dfg-sos.github.io/ontologies/eo-formats#")


def run(tmp_path, document, job, *argv, log=True):
    log_path = tmp_path / "t.jsonl"
    args = ["--quiet", "--no-container", "--outdir", str(tmp_path / "out")]
    if log:
        args += ["--trace", str(log_path), "--resource-demand", "log"]
    rc = runner.main(
        [*args, *argv, str(EXAMPLES / document), str(EXAMPLES / "jobs" / job)], extensions=[ResourceDemandExtension()]
    )
    records = [json.loads(line) for line in log_path.read_text().splitlines()] if log else []
    return rc, records


def demands(records):
    return [r for r in records if r["record"] == "demand"]


def test_generic_measures_are_taken(tmp_path):
    rc, records = run(tmp_path, "concat.cwl", "concat.yml")
    assert rc == 0
    [record] = demands(records)
    assert record["variables"] == {
        "k": {"port": "times", "measure": str(RD.Value), "value": 3},
        "b": {"port": "files", "measure": str(RD.FileSize), "value": 4 + 6},
        "m": {"port": "files", "measure": str(RD.ArrayLength), "value": 2},
    }
    assert record["source"] == "hints"
    assert record["demands"]["time"] == [
        [{"variable": "k", "complexity": str(RD.Linear)}, {"variable": "b", "complexity": str(RD.Linear)}]
    ]
    # The sample an estimator fits to: measured variables and the main command's duration, by job.
    [main] = [r for r in records if r["record"] == "job"]
    assert main["job"] == record["job"]


def test_workflow_steps_and_unmeasured_variables(tmp_path):
    rc, records = run(tmp_path, "workflow.cwl", "mask.yml")
    assert rc == 0
    by_step = {r["step"]: r for r in demands(records)}
    assert set(by_step) == {"resample", "polygonize"}
    resample = by_step["resample"]["variables"]
    assert resample["s"]["value"] == 2.0  # default value of the input
    assert resample["n"] == {"port": "raster", "measure": str(EO.PixelCount), "value": None}  # not measured yet


def test_off(tmp_path):
    rc, records = run(tmp_path, "concat.cwl", "concat.yml", "--resource-demand", "off")
    assert rc == 0
    assert demands(records) == []
    assert records[0]["arguments"]["resource_demand"] == "off"


def test_off_by_default_like_plain_cwltool(tmp_path):
    ext = ResourceDemandExtension()
    argv = ["--quiet", "--no-container", "--outdir", str(tmp_path / "out")]
    assert (
        runner.main([*argv, str(EXAMPLES / "concat.cwl"), str(EXAMPLES / "jobs" / "concat.yml")], extensions=[ext]) == 0
    )
    assert not ext.tools  # annotations are not even read
    assert not ext.active


def test_log_needs_a_trace(tmp_path, capsys):
    argv = ["--resource-demand", "log", str(EXAMPLES / "concat.cwl"), str(EXAMPLES / "jobs" / "concat.yml")]
    with pytest.raises(SystemExit) as exc:
        runner.main(argv, extensions=[ResourceDemandExtension()])
    assert exc.value.code == 2
    assert "--resource-demand log needs --trace" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("measure", "value", "expected"),
    [
        (DirectMeasure.VALUE, 3, 3),
        (DirectMeasure.VALUE, 2.5, 2.5),
        (DirectMeasure.VALUE, True, None),
        (DirectMeasure.VALUE, None, None),
        (DirectMeasure.ARRAY_LENGTH, [1, 2, 3], 3),
        (DirectMeasure.ARRAY_LENGTH, "abc", None),
        (DirectMeasure.FILE_SIZE, {"class": "File", "size": 7}, 7),
        (DirectMeasure.FILE_SIZE, [{"class": "File", "size": 7}, {"class": "File", "size": 1}], 8),
        (DirectMeasure.FILE_SIZE, [], None),
        (DirectMeasure.FILE_SIZE, {"class": "File", "location": "https://example.org/x.tif"}, None),
    ],
)
def test_direct_measures(measure, value, expected):
    var = Variable("p", "x", measure, {})
    assert measure.take(var, Port("p", "File"), value).value == expected


@pytest.mark.parametrize(
    ("measure_iri", "instrument"),
    [
        (RD.FileSize, DirectMeasure.FILE_SIZE),
        (EO.PixelCount, None),  # domain measures are not taken yet
        (RD.DerivedMeasure, None),  # without --resource-demand-probes
    ],
)
def test_the_instrument_of_a_variable(measure_iri, instrument):
    var = Variable("p", "x", str(measure_iri), {})
    assert ResourceDemandExtension().instrument(var) is instrument
