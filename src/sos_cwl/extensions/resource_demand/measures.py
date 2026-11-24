"""The values of a job's complexity variables, taken at run time.

Direct measures (`rd:Value`, `rd:ArrayLength`, `rd:FileSize`) are taken from the CWL value itself; derived
measures (`rd:DerivedMeasure`), with probes enabled, by running their probe (`probes.py`). Domain measures
(`eo:PixelCount`, ...) need to open the file and are not taken yet: their value is None.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sos_cwl.core.files import iter_files

from .annotations import Port, Variable
from .vocabulary import RD

Number = int | float


def as_number(value: Any) -> Number | None:
    """The value if it is a number (booleans are not)."""
    return value if isinstance(value, int | float) and not isinstance(value, bool) else None


@dataclass(frozen=True)
class Measurement:
    value: Number | None
    duration_ms: float | None = None  # only when a probe ran
    error: str | None = None


class Instrument:
    """Takes the value of a complexity variable for a job."""

    def take(self, var: Variable, port: Port, value: Any) -> Measurement:
        raise NotImplementedError


class DirectMeasure(Instrument, StrEnum):
    """Measures that need nothing but the CWL value."""

    VALUE = str(RD.Value)
    ARRAY_LENGTH = str(RD.ArrayLength)
    FILE_SIZE = str(RD.FileSize)

    def take(self, var: Variable, port: Port, value: Any) -> Measurement:
        return Measurement(self._number(value))

    def _number(self, value: Any) -> Number | None:
        match self:
            case DirectMeasure.VALUE:
                return as_number(value)
            case DirectMeasure.ARRAY_LENGTH:
                return len(value) if isinstance(value, list) else None
            case DirectMeasure.FILE_SIZE:
                # bytes of the primary files (without secondaryFiles); cwltool sets `size` on every File
                sizes = [f.get("size") for f in iter_files(value)]
                return sum(sizes) if sizes and all(isinstance(s, int) for s in sizes) else None
