"""Probes: CWL tools that compute a derived measure (rd:DerivedMeasure) of an input.

Contract: a CommandLineTool with exactly one input, of the type of the annotated input, and exactly
one output, a number (int, long, float or double).

Design time, `Probe.load`: load a probe and report where it breaks the contract.
Run time, `Prober`: run a probe on a job's input value with cwltool's own Python API, so the probe
gets staging and containers like any step. It never fails the job: a broken or failing probe gives
no value and an error.
"""

from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass
from typing import Any

from cwltool.context import RuntimeContext
from cwltool.factory import Callable as CwlCallable
from cwltool.factory import Factory
from cwltool.process import Process, shortname

from sos_cwl.core import loading

from .annotations import Port, Variable
from .measures import Instrument, Measurement, Number, as_number

NUMBERS = ("int", "long", "float", "double")


class ProbeError(Exception):
    """A probe cannot be loaded or breaks the contract."""


@dataclass(frozen=True)
class Probe:
    process: Process
    input: str  # short name of its one input
    output: str  # short name of its one numeric output

    @classmethod
    def load(cls, iri: str, port: Port) -> Probe:
        """The probe for an input of the given port; ProbeError names every broken rule."""
        try:
            process = loading.load(iri)
        except Exception as exc:  # cwltool raises several types for missing or invalid documents
            raise ProbeError(f"probe {_name(iri)} cannot be loaded: {exc}") from exc
        tool = process.tool
        problems = []
        if tool.get("class") != "CommandLineTool":
            problems.append(f"is a {tool.get('class')}, not a CommandLineTool")
        inputs, outputs = tool["inputs"], tool["outputs"]
        if len(inputs) != 1:
            problems.append(f"needs exactly one input, has {len(inputs)}")
        elif (given := Port.from_param(inputs[0]).type) != port.type:
            problems.append(f"input is {given}, the annotated input is {port.type}")
        if len(outputs) != 1:
            problems.append(f"needs exactly one output, has {len(outputs)}")
        elif (kind := Port.from_param(outputs[0]).kind) not in NUMBERS:
            problems.append(f"output must be a number ({', '.join(NUMBERS)}), is {kind}")
        if problems:
            raise ProbeError(f"probe {_name(iri)}: " + "; ".join(problems))
        return cls(process, shortname(inputs[0]["id"]), shortname(outputs[0]["id"]))


def _name(iri: str) -> str:
    return iri.rsplit("/", 1)[-1]


class Prober(Instrument):
    """Runs the probes of one cwltool run: each probe is loaded once, each input value probed once.

    The probes run with the run's settings (containers, cache, ...), but their outputs go to a temporary
    directory, never into the run's --outdir.
    """

    def __init__(self, runtime_context: RuntimeContext):
        self._outdir = tempfile.TemporaryDirectory(prefix="sos-cwl-probes-")  # instead of the run's --outdir
        context = runtime_context.copy()
        context.outdir = self._outdir.name
        self._cwl_factory = Factory(runtime_context=context)  # runs a probe like a step, with the run's settings
        self._loaded_probes: dict[str, Probe] = {}  # by IRI
        self._measurements: dict[tuple[str, str], Measurement] = {}  # by (probe IRI, unstaged value as JSON)

    def close(self) -> None:
        self._outdir.cleanup()

    def take(self, var: Variable, port: Port, value: Any) -> Measurement:
        if not (iri := var.probe):
            return Measurement(None)
        unstaged = _unstaged(value)
        key = (iri, json.dumps(unstaged, sort_keys=True, default=str))
        if key not in self._measurements:
            start = time.perf_counter()
            try:
                result, error = self._call(iri, port, unstaged), None
            except ProbeError as exc:
                result, error = None, str(exc)
            self._measurements[key] = Measurement(result, (time.perf_counter() - start) * 1000, error)
        return self._measurements[key]

    def _call(self, iri: str, port: Port, value: Any) -> Number:
        """Run the probe on an unstaged value."""
        if iri not in self._loaded_probes:
            self._loaded_probes[iri] = Probe.load(iri, port)  # a broken probe raises again for the next value
        probe = self._loaded_probes[iri]
        try:
            out = CwlCallable(probe.process, self._cwl_factory)(**{probe.input: value})
        except Exception as exc:  # whatever went wrong, the job goes on without the value
            raise ProbeError(f"probe {_name(iri)} failed: {exc}") from exc
        result = out.get(probe.output) if isinstance(out, dict) else None
        if (number := as_number(result)) is None:
            raise ProbeError(f"probe {_name(iri)} returned {result!r}, not a number")
        return number


def _unstaged(value: Any) -> Any:
    """The input value as before staging: without the job's `path`/`dirname` (inside a container, container
    paths), so the probe stages the files itself from their `location`, and the same file is the same value."""
    if isinstance(value, list):
        return [_unstaged(v) for v in value]
    if isinstance(value, dict):
        staged = ("path", "dirname") if value.get("class") in ("File", "Directory") else ()
        return {k: _unstaged(v) for k, v in value.items() if k not in staged}
    return value
