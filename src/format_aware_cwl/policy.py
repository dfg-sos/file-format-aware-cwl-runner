"""Turn a validation result into log-only or a step failure."""

from __future__ import annotations

from dataclasses import dataclass

from .client import ERROR, FAILURE, SUCCESS, UNCERTAIN, ValidationResult

OFF, WARN, FAIL = "off", "warn", "fail"


@dataclass(frozen=True)
class Policy:
    validation: str = FAIL  # off | warn | fail
    mode: str = "basic"  # basic | metadata | content (service validation mode)
    uncertain: str = WARN  # warn | fail
    service_error: str = FAIL  # warn | fail

    @property
    def enabled(self) -> bool:
        return self.validation != OFF

    def is_fatal(self, result: ValidationResult) -> bool:
        """True if this result must abort the step."""
        if self.validation != FAIL or result.status == SUCCESS:
            return False
        if result.status == FAILURE:
            return True
        if result.status == UNCERTAIN:
            return self.uncertain == FAIL
        if result.status == ERROR:
            return self.service_error == FAIL
        return True  # unknown status: be strict


def describe(step: str, port: str, direction: str, basename: str, fmt: str, result: ValidationResult) -> str:
    where = "input" if direction == "pre" else "output"
    verdict = {
        FAILURE: "is not valid",
        UNCERTAIN: "could not be confirmed as",
        ERROR: "could not be validated as",
    }.get(result.status, "is not valid")
    return (
        f"[step {step}] {where} '{port}' file '{basename}' {verdict} {fmt}: "
        f"{result.status}{': ' + result.message if result.message else ''}"
    )
