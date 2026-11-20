"""Turn a validation result into log-only or a step failure."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .client import Mode, ValidationResult, ValidationStatus


class Reaction(StrEnum):
    """What a problem leads to (`--format-validation`, `--format-uncertain`, `--format-service-error`)."""

    OFF = "off"  # not validated at all (only for --format-validation)
    WARN = "warn"  # logged
    FAIL = "fail"  # the step ends permanentFail


class Phase(StrEnum):
    """When a job's files are validated."""

    PRE = "pre"  # a job's inputs, before its command runs
    POST = "post"  # its outputs, after

    @property
    def ports(self) -> str:
        return "input" if self is Phase.PRE else "output"


class Check(StrEnum):
    """Which files of a job are validated (`--format-check`)."""

    BOTH = "both"
    PRE = "pre"
    POST = "post"

    @property
    def phases(self) -> frozenset[Phase]:
        return frozenset(Phase) if self is Check.BOTH else frozenset({Phase(self.value)})


@dataclass(frozen=True)
class Policy:
    validation: Reaction = Reaction.FAIL
    mode: Mode = Mode.BASIC
    uncertain: Reaction = Reaction.WARN
    service_error: Reaction = Reaction.FAIL

    @property
    def enabled(self) -> bool:
        return self.validation != Reaction.OFF

    def is_fatal(self, result: ValidationResult) -> bool:
        """True if this result must abort the step."""
        if self.validation != Reaction.FAIL or result.status == ValidationStatus.SUCCESS:
            return False
        if result.status == ValidationStatus.FAILURE:
            return True
        if result.status == ValidationStatus.UNCERTAIN:
            return self.uncertain == Reaction.FAIL
        if result.status == ValidationStatus.ERROR:
            return self.service_error == Reaction.FAIL
        return True  # unknown status: be strict


# keyed by str: the service may answer a status that is not a ValidationStatus
VERDICTS: dict[str, str] = {
    ValidationStatus.FAILURE: "is not valid",
    ValidationStatus.UNCERTAIN: "could not be confirmed as",
    ValidationStatus.ERROR: "could not be validated as",
}


def describe(step: str, port: str, phase: Phase, basename: str, fmt: str, result: ValidationResult) -> str:
    verdict = VERDICTS.get(result.status, "is not valid")
    return (
        f"[step {step}] {phase.ports} '{port}' file '{basename}' {verdict} {fmt}: "
        f"{result.status}{': ' + result.message if result.message else ''}"
    )
