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

SOS_CWL = "https://dfg-sos.github.io/ontologies/cwl#"


def sos_field(mapping: Mapping[str, Any], name: str) -> Any:
    """Value of the extension field `sos:<name>`.

    schema-salad expands namespaced keys to the full IRI; the prefixed form is accepted too.
    """
    return mapping.get(SOS_CWL + name, mapping.get("sos:" + name))


def _get(port: Mapping[str, Any], name: str) -> str | None:
    value = sos_field(port, name)
    return str(value) if value not in (None, "") else None


def expected_crs(port: Mapping[str, Any]) -> str | None:
    return _get(port, "expectedCRS")


def expected_geometry_type(port: Mapping[str, Any]) -> str | None:
    return _get(port, "expectedGeometryType")


def expected_metadata(port: Mapping[str, Any]) -> dict[str, str]:
    """The port's extension fields as the service's `expected_metadata` keys (only those set)."""
    values = {"crs": expected_crs(port), "geometry_type": expected_geometry_type(port)}
    return {key: value for key, value in values.items() if value}
