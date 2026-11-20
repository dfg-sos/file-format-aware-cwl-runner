"""`sos-cwl-lint`: collects the findings of the extensions' design-time checks."""

from __future__ import annotations

import pytest

from sos_cwl.core import lint
from sos_cwl.core.extension import Extension, Finding, LintResult, Severity


class Fixed(Extension):
    def __init__(self, name, *findings, lines=()):
        self.name = name
        self.result = LintResult(list(lines), [Finding(*f) for f in findings])
        self.seen = []

    def add_lint_arguments(self, group):
        group.add_argument(f"--{self.name}-opt", default="x")

    def lint(self, document, args):
        self.seen.append((document, getattr(args, f"{self.name}_opt")))
        return self.result


def test_findings_and_exit_code(capsys):
    a = Fixed("a", (Severity.ERROR, "t.cwl#x", "broken"), lines=["summary"])
    b = Fixed("b", (Severity.WARNING, "t.cwl#y", "odd"))
    assert lint.main(["t.cwl", "--a-opt", "y"], extensions=[a, b]) == 1
    out = capsys.readouterr().out
    assert "[a] t.cwl\n  summary\n  error   t.cwl#x: broken" in out
    assert "warning t.cwl#y: odd" in out
    assert out.strip().endswith("1 error(s), 1 warning(s), 0 info(s)")
    assert a.seen == [("t.cwl", "y")]


@pytest.mark.parametrize(("strict", "rc"), [([], 0), (["--strict"], 1)])
def test_warnings_fail_only_when_strict(strict, rc):
    assert lint.main(["t.cwl", *strict], extensions=[Fixed("a", (Severity.WARNING, "l", "m"))]) == rc


def test_select_extensions():
    a, b = Fixed("a", (Severity.ERROR, "l", "m")), Fixed("b")
    assert lint.main(["t.cwl", "u.cwl", "--extension", "b"], extensions=[a, b]) == 0
    assert a.seen == []
    assert [d for d, _ in b.seen] == ["t.cwl", "u.cwl"]


def test_empty_results_print_nothing(capsys):
    assert lint.main(["t.cwl"], extensions=[Fixed("a")]) == 0
    assert "[a]" not in capsys.readouterr().out
