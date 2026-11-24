"""SHACL validation: one test per rule, each with the smallest tool that breaks it."""

from __future__ import annotations

import pytest

from .conftest import factor, make_tool, messages, raster, term

PIXELS = {"symbol": "n", "measure": "eo:PixelCount"}


def test_valid_tool_has_no_issues(check):
    tool = make_tool({"mask": raster(PIXELS)}, ram=[term(factor("n"))], time=[term(factor("n", "rd:Linearithmic"))])
    assert check(tool) == []


def test_unannotated_tool_is_skipped(check):
    assert check(make_tool({"x": "int"})) == []


# ---- complexity variables


def test_symbol_required(check):
    tool = make_tool({"mask": raster({"measure": "eo:PixelCount"})})
    assert "rd:complexityVariables[0] needs a symbol and a measure" in messages(check(tool))


def test_symbol_must_be_a_name(check):
    tool = make_tool({"mask": raster({"symbol": "2n", "measure": "eo:PixelCount"})}, ram=[term(factor("2n"))])
    assert any("symbol 2n must be a name" in m for m in messages(check(tool)))


def test_measure_required(check):
    tool = make_tool({"mask": raster({"symbol": "n"})}, ram=[term(factor("n"))])
    assert "rd:complexityVariables[0] needs a symbol and a measure" in messages(check(tool))


def test_measure_with_undeclared_prefix_is_not_an_iri(check):
    tool = make_tool({"mask": raster({"symbol": "n", "measure": "PixelCount"})}, ram=[term(factor("n"))])
    assert any(m.startswith("measure PixelCount is not an IRI") for m in messages(check(tool)))


@pytest.mark.parametrize("measure", ["rd:Measure", "rd:Linear", "eo:GeoTIFF", "rd:Nonsense"])
def test_measure_must_be_a_measure(check, measure):
    tool = make_tool({"mask": raster({"symbol": "n", "measure": measure})}, ram=[term(factor("n"))])
    assert f"measure {measure} is not a rd:Measure" in " ".join(messages(check(tool), "error"))


def test_unexpected_key_in_variable(check):
    tool = make_tool({"mask": raster({**PIXELS, "unit": "px"})}, ram=[term(factor("n"))])
    assert "unexpected key 'unit'" in messages(check(tool))


def test_derived_measure_needs_probe(check):
    tool = make_tool({"mask": raster({"symbol": "c", "measure": "rd:DerivedMeasure"})}, ram=[term(factor("c"))])
    assert any("needs a probe" in m for m in messages(check(tool)))


def test_probe_only_for_derived_measure(check):
    tool = make_tool({"mask": raster({**PIXELS, "probe": "probe.cwl"})}, ram=[term(factor("n"))])
    assert any("a probe is only allowed for a rd:DerivedMeasure" in m for m in messages(check(tool)))


def test_value_needs_numeric_input(check):
    tool = make_tool(
        {"name": {"type": "string", "rd:complexityVariables": [{"symbol": "s", "measure": "rd:Value"}]}},
        time=[term(factor("s"))],
    )
    assert "measure rd:Value needs a numeric input (int, long, float, double), not string" in messages(check(tool))


@pytest.mark.parametrize("type_", ["int", "float?", "long"])
def test_value_on_numbers(check, type_):
    tool = make_tool(
        {"k": {"type": type_, "rd:complexityVariables": [{"symbol": "k", "measure": "rd:Value"}]}},
        time=[term(factor("k"))],
    )
    assert check(tool) == []


def test_array_length_needs_array(check):
    tool = make_tool(
        {"k": {"type": "int", "rd:complexityVariables": [{"symbol": "k", "measure": "rd:ArrayLength"}]}},
        time=[term(factor("k"))],
    )
    assert "measure rd:ArrayLength needs an array input, not int" in messages(check(tool))


def test_file_size_on_array_of_files(check):
    tool = make_tool(
        {"fs": {"type": "File[]", "rd:complexityVariables": [{"symbol": "b", "measure": "rd:FileSize"}]}},
        time=[term(factor("b"))],
    )
    assert check(tool) == []


def test_file_measure_on_number(check):
    tool = make_tool(
        {"k": {"type": "int", "rd:complexityVariables": [{"symbol": "b", "measure": "rd:FileSize"}]}},
        time=[term(factor("b"))],
    )
    assert "measure rd:FileSize needs a File input (or an array of Files), not int" in messages(check(tool))


def test_format_measure_needs_format(check):
    tool = make_tool({"mask": raster(PIXELS, fmt=None)}, ram=[term(factor("n"))])
    assert any("declare a format on the input" in m for m in messages(check(tool)))


def test_raster_measure_on_vector_format(check):
    tool = make_tool({"roads": raster(PIXELS, fmt="eo:Shapefile")}, ram=[term(factor("n"))])
    assert "measure eo:PixelCount cannot be taken from format eo:Shapefile" in messages(check(tool))


@pytest.mark.parametrize("fmt", ["eo:GeoTIFF", "eo:COG", "eo:Raster"])
def test_raster_measure_on_raster_formats(check, fmt):
    """Subclasses of eo:Raster are accepted (COG is a GeoTIFF is a Raster)."""
    assert check(make_tool({"mask": raster(PIXELS, fmt=fmt)}, ram=[term(factor("n"))])) == []


def test_measure_must_fit_every_declared_format(check):
    tool = make_tool({"x": raster(PIXELS, fmt=["eo:GeoTIFF", "eo:GeoJSON"])}, ram=[term(factor("n"))])
    assert messages(check(tool)) == ["measure eo:PixelCount cannot be taken from format eo:GeoJSON"]


def test_format_expression_is_a_warning(check):
    tool = make_tool({"mask": raster(PIXELS, fmt="$(inputs.fmt)"), "fmt": "string"}, ram=[term(factor("n"))])
    findings = check(tool)
    assert messages(findings, "error") == []
    assert any("format of the input is an expression" in m for m in messages(findings, "warning"))


def test_duplicate_symbol(check):
    tool = make_tool({"a": raster(PIXELS), "b": raster(PIXELS)}, ram=[term(factor("n"))])
    assert "symbol n is declared more than once in this tool" in messages(check(tool))


# ---- demands


def test_undeclared_variable(check):
    tool = make_tool({"mask": raster(PIXELS)}, ram=[term(factor("n")), term(factor("m"))])
    assert any("variable m is not declared" in m for m in messages(check(tool), "error"))


def test_unused_variable_is_a_warning(check):
    tool = make_tool(
        {"mask": raster(PIXELS, {"symbol": "d", "measure": "eo:ValidPixelCount"})}, ram=[term(factor("n"))]
    )
    findings = check(tool)
    assert messages(findings, "error") == []
    assert messages(findings, "warning") == ["variable d is declared but not used by any demand"]


@pytest.mark.parametrize("complexity", ["rd:Measure", "rd:ComplexityClass", "rd:Linaer", "eo:PixelCount"])
def test_complexity_must_be_a_complexity_class(check, complexity):
    tool = make_tool({"mask": raster(PIXELS)}, ram=[term(factor("n", complexity))])
    assert any(f"complexity {complexity} is not a rd:ComplexityClass" in m for m in messages(check(tool)))


def test_complexity_without_prefix(check):
    tool = make_tool({"mask": raster(PIXELS)}, ram=[term(factor("n", "linear"))])
    assert any(m.startswith("complexity linear is not an IRI") for m in messages(check(tool)))


def test_term_must_map_symbols_to_complexities(check):
    tool = make_tool({"mask": raster(PIXELS)}, ram=[["n"], {"n": ["rd:Linear"]}, term(factor("n"))])
    found = messages(check(tool))
    assert "rd:ramDemand[0] must be a mapping {symbol: complexity}" in found
    assert "rd:ramDemand[1] must be a mapping {symbol: complexity}" in found


def test_constant_term(check):
    assert check(make_tool({"mask": raster(PIXELS)}, ram=[term()], time=[term(factor("n"))])) == []


def test_requirements_win_over_hints(check):
    tool = make_tool(
        {"mask": raster(PIXELS)},
        ram=[term(factor("n"))],
        section="requirements",
        hints=[{"class": "ResourceRequirement", "rd:ramDemand": [term(factor("zzz"))]}],
    )
    found = check(tool)
    assert messages(found) == ["demands in both requirements and hints; the hints are ignored"]


# ---- structure (before SHACL)


def test_demand_must_be_a_list(check):
    tool = make_tool({"mask": raster(PIXELS)}, ram={"n": "rd:Linear"})
    assert "rd:ramDemand must be a list of terms {symbol: complexity}" in messages(check(tool))
