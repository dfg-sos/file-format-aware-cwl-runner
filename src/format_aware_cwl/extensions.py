"""CWL extension fields for `metadata` and `content` mode: expected CRS and geometry type on a File port.

Declare in a CWL document:
    $namespaces: {sos: "https://dfg-sos.github.io/ontologies/cwl#"}
    ...
    outputs:
      roads: {type: File, format: edam:format_4119, sos:expectedCRS: "EPSG:4326", sos:expectedGeometryType: LineString}
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SOS_NAMESPACE = "https://dfg-sos.github.io/ontologies/cwl#"
EXPECTED_CRS = SOS_NAMESPACE + "expectedCRS"
EXPECTED_GEOMETRY_TYPE = SOS_NAMESPACE + "expectedGeometryType"


def _get(port: Mapping[str, Any], iri: str) -> str | None:
    # schema-salad expands namespaced keys to the full IRI; accept the prefixed form too.
    value = port.get(iri, port.get("sos:" + iri[len(SOS_NAMESPACE) :]))
    return str(value) if value not in (None, "") else None


def expected_crs(port: Mapping[str, Any]) -> str | None:
    return _get(port, EXPECTED_CRS)


def expected_geometry_type(port: Mapping[str, Any]) -> str | None:
    return _get(port, EXPECTED_GEOMETRY_TYPE)


def expected_metadata(port: Mapping[str, Any]) -> dict[str, str]:
    """The port's extension fields as the service's `expected_metadata` keys (only those set)."""
    values = {"crs": expected_crs(port), "geometry_type": expected_geometry_type(port)}
    return {key: value for key, value in values.items() if value}
