"""The vocabularies an annotation is checked against: resource demand (rd:) and the document's domain vocabularies.

rd: is a fixed release (`--resource-demand-vocabulary`, default RD_VERSION), downloaded once into the user's cache:
releases never change. Domain vocabularies (file formats, domain measures such as eo:PixelCount) are the document's
own `$schemas`, which cwltool loads for its format checks anyway.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from rdflib import Graph, Namespace, URIRef

if TYPE_CHECKING:  # annotations imports RD from here
    from .annotations import Factor, Term

BASE = "https://dfg-sos.github.io/ontologies/"
RD = Namespace(BASE + "resource-demand#")
CWL = Namespace("https://w3id.org/cwl/cwl#")

RD_VERSION = "1.2.0"  # demand terms as {symbol: complexity} mappings


class VocabularyError(Exception):
    """The rd vocabulary cannot be loaded."""


def release_url(version: str) -> str:
    return f"{BASE}releases/resource-demand/{version}/resource-demand.owl"


def cache_dir() -> Path:
    """`$SOS_CWL_CACHE`, else `$XDG_CACHE_HOME/sos-cwl` (default `~/.cache/sos-cwl`)."""
    if path := os.environ.get("SOS_CWL_CACHE"):
        return Path(path)
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "sos-cwl"


@cache
def rd_graph(source: str = RD_VERSION) -> Graph:
    """The rd vocabulary: a release version (downloaded once, then read from the cache), or the URL or path of an
    unreleased file (read every time)."""
    graph = Graph()
    try:
        if re.fullmatch(r"\d+\.\d+\.\d+", source):
            graph.parse(data=_cached_release(source), format="xml")
        else:
            graph.parse(source)
    except (OSError, httpx.HTTPError, ValueError) as exc:
        raise VocabularyError(f"cannot load the resource demand vocabulary {source}: {exc}") from exc
    return graph


def _cached_release(version: str) -> bytes:
    url = release_url(version)
    path = cache_dir() / url.removeprefix(BASE)
    if not path.exists():
        response = httpx.get(url, follow_redirects=True, timeout=30)
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".partial")
        partial.write_bytes(response.content)
        partial.replace(path)  # atomic: a concurrent run never reads half a file
    return path.read_bytes()


class Vocabulary:
    """rd merged with the domain vocabularies, with the lookups the annotation needs."""

    def __init__(self, rd: Graph, domain: Iterable[Graph] = (), prefixes: Mapping[str, str] | None = None) -> None:
        self.graph = Graph()
        self.graph += rd
        for graph in domain:
            self.graph += graph
        self.prefixes = {"rd": str(RD), **(prefixes or {})}  # for display: `eo:PixelCount`
        for prefix, ns in self.prefixes.items():
            self.graph.bind(prefix, ns)

    def big_o(self, terms: Iterable[Term]) -> str:
        """A demand in Big O notation, e.g. `O(n + d^2)`, from the rd:bigO of its complexity classes.

        Terms are summed; a demand without terms is constant, and so is a constant next to growing terms."""
        texts = list(dict.fromkeys(self._term_text(t) for t in terms))
        if len(texts) > 1:
            texts = [t for t in texts if t != "1"]
        return "O(" + " + ".join(texts or ["1"]) + ")"

    def _term_text(self, term: Term) -> str:
        """Factors are multiplied; constant factors are dropped."""
        parts = [p for p in map(self._factor_text, term) if p != "1"] or ["1"]
        if len(parts) == 1:
            return parts[0]
        return " · ".join(f"({p})" if " " in p and "log" not in p else p for p in parts)

    def _factor_text(self, factor: Factor) -> str:
        """`rd:Linearithmic` on `area` -> `area log area` (the vocabulary's `O(n log n)` with n replaced)."""
        value = self.graph.value(URIRef(factor.complexity), RD.bigO)
        inner = str(value or "O(?)").removeprefix("O(").removesuffix(")")
        return re.sub(r"\bn\b", factor.variable, inner)

    def qname(self, iri: str) -> str:
        """`eo:PixelCount` for a namespace of the document, else the IRI itself."""
        for prefix, ns in self.prefixes.items():
            if iri.startswith(ns):
                return f"{prefix}:{iri[len(ns) :]}"
        return iri
