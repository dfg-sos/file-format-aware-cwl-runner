"""Loading the resource demand vocabulary, and Big O rendering."""

from __future__ import annotations

import httpx
import pytest
import respx
from rdflib import OWL, URIRef

from sos_cwl.extensions.resource_demand import Factor
from sos_cwl.extensions.resource_demand.vocabulary import (
    BASE,
    RD,
    RD_VERSION,
    VocabularyError,
    _cached_release,
    rd_graph,
    release_url,
)

from .conftest import RD_OWL


def test_default_is_the_cached_release():
    graph = rd_graph()
    assert str(graph.value(URIRef(BASE + "resource-demand"), OWL.versionIRI)) == release_url(RD_VERSION)
    assert (RD.Linear, RD.bigO, None) in graph


def test_a_release_is_downloaded_once(tmp_path, monkeypatch):
    monkeypatch.setenv("SOS_CWL_CACHE", str(tmp_path))
    owl = RD_OWL.read_bytes()
    with respx.mock:
        route = respx.get(release_url("9.9.9")).mock(return_value=httpx.Response(200, content=owl))
        assert _cached_release("9.9.9") == owl
        assert _cached_release("9.9.9") == owl
    assert route.call_count == 1
    assert (tmp_path / "releases/resource-demand/9.9.9/resource-demand.owl").read_bytes() == owl


def test_an_unreleased_vocabulary_by_path():
    assert (RD.Linear, RD.bigO, None) in rd_graph(str(RD_OWL))


def test_a_missing_vocabulary_is_a_vocabulary_error(tmp_path):
    with pytest.raises(VocabularyError, match="cannot load the resource demand vocabulary"):
        rd_graph(str(tmp_path / "missing.owl"))


def F(variable: str, complexity: str) -> Factor:  # noqa: N802
    return Factor(variable, str(RD[complexity]))


@pytest.mark.parametrize(
    ("terms", "expected"),
    [
        ([], "O(1)"),
        ([(())], "O(1)"),
        ([((F("n", "Linear"),))], "O(n)"),
        ([((F("n", "Linear"),)), (())], "O(n)"),
        ([((F("n", "Linear"), F("d", "Quadratic")))], "O(n · d^2)"),
        ([((F("n", "Linear"),)), ((F("d", "Linearithmic"),))], "O(n + d log d)"),
        ([((F("area", "Logarithmic"),))], "O(log area)"),
        ([((F("n", "Constant"), F("d", "Linear")))], "O(d)"),
        ([((F("n", "Linear"),)), ((F("n", "Linear"),))], "O(n)"),
    ],
)
def test_big_o(vocabulary, terms, expected):
    assert vocabulary.big_o(terms) == expected
