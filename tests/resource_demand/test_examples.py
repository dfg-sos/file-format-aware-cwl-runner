"""The examples: valid, rendered as intended, and still plain CWL that cwltool runs."""

from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

from sos_cwl.core import lint
from sos_cwl.extensions.resource_demand import Document, ResourceDemandExtension, validate

from .conftest import EO_FORMATS, EXAMPLES

EXPECTED = {
    "resample.cwl": {"ram": "O(n · s^2)", "time": "O(n · s^2)"},
    "polygonize.cwl": {"ram": "O(n + d)", "time": "O(n + d log d)"},
    "count-features.cwl": {"ram": "O(1)", "time": "O(f)"},
    "cloud-mask.cwl": {"ram": "O(n)", "time": "O(n · c)"},
    "concat.cwl": {"ram": "O(m)", "time": "O(k · b)"},
    "zonal-stats.cwl": {"ram": "O(n + v)", "time": "O(b · n + v)"},
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_example_valid_and_rendered(name):
    doc = Document.load(EXAMPLES / name)
    vocabulary = doc.vocabulary()
    assert validate(doc.annotations, vocabulary) == []
    [ann] = doc.annotations
    assert {r: vocabulary.big_o(terms) for r, terms in ann.demands.items()} == EXPECTED[name]


def test_workflow_reads_every_step():
    doc = Document.load(EXAMPLES / "workflow.cwl")
    assert sorted(a.tool_id.rsplit("/", 1)[-1] for a in doc.annotations) == ["polygonize.cwl", "resample.cwl"]
    assert validate(doc.annotations, doc.vocabulary()) == []


def test_probe_resolved_relative_to_document():
    [ann] = Document.load(EXAMPLES / "cloud-mask.cwl").annotations
    probe = ann.variables["c"].probe
    assert probe == (EXAMPLES / "probes" / "cloud-fraction.cwl").as_uri()


@pytest.mark.parametrize("name", [*sorted(EXPECTED), "workflow.cwl", "probes/cloud-fraction.cwl"])
def test_cwltool_strict_validate(name):
    """Annotated documents stay valid CWL for an unmodified cwltool."""
    result = subprocess.run(
        [sys.executable, "-m", "cwltool", "--strict", "--validate", str(EXAMPLES / name)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "is valid CWL" in result.stdout


@pytest.mark.skipif(shutil.which("cp") is None, reason="needs cp")
def test_cwltool_runs_annotated_workflow(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "cwltool",
            "--strict",
            "--no-container",
            "--outdir",
            str(tmp_path),
            str(EXAMPLES / "workflow.cwl"),
            str(EXAMPLES / "jobs" / "mask.yml"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Final process status is success" in result.stderr


def test_lint(capsys):
    argv = [str(EXAMPLES / "polygonize.cwl")]
    assert lint.main(argv, extensions=[ResourceDemandExtension()]) == 0
    out = capsys.readouterr().out
    assert "n = eo:PixelCount(mask)" in out
    assert "time: O(n + d log d)" in out
    assert "0 error(s), 0 warning(s)" in out


def test_lint_reports_findings(capsys, tmp_path):
    broken = tmp_path / "broken.cwl"
    text = (EXAMPLES / "polygonize.cwl").read_text().replace("rd:Linearithmic", "rd:Linaer")
    broken.write_text(text.replace("../vocabularies/eo-formats.owl", EO_FORMATS.as_uri()))
    assert lint.main([str(broken)], extensions=[ResourceDemandExtension()]) == 1
    assert "complexity rd:Linaer is not a rd:ComplexityClass" in capsys.readouterr().out


def test_lint_skips_unannotated_documents(capsys):
    """No vocabulary is loaded (nor needed) for a document without annotations."""
    unannotated = EXAMPLES / "probes" / "cloud-fraction.cwl"
    assert (
        lint.main(
            ["--resource-demand-vocabulary", "http://ontology.invalid/rd.owl", str(unannotated)],
            extensions=[ResourceDemandExtension()],
        )
        == 0
    )
