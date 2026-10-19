"""HTTP client for the SOS File Format Service."""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import IO, Any
from urllib.parse import urlsplit

import httpx

VALIDATE_PATH = "/api/v1/validate"
COMPATIBILITY_PATH = "/api/v1/compatibility"
FORMAT_INFO_PATH = "/api/v1/format-info"

SUCCESS = "SUCCESS"
UNCERTAIN = "UNCERTAIN"
FAILURE = "FAILURE"
ERROR = "ERROR"  # client-side: service unreachable or rejected the request


def split_format_iri(iri: str) -> tuple[str, str]:
    """Split a format IRI into (ontology_namespace, format_identifier) at the last '#' or '/'."""
    cut = max(iri.rfind("#"), iri.rfind("/"))
    if cut <= 0 or cut == len(iri) - 1:
        raise ValueError(f"not a format IRI: {iri!r}")
    return iri[:cut], iri[cut + 1 :]


@dataclass
class FileRef:
    """A file to send to the service: a local path or a remote http(s) URL."""

    source: str
    basename: str

    @property
    def is_remote(self) -> bool:
        return urlsplit(self.source).scheme in ("http", "https")

    def size(self) -> int | None:
        if self.is_remote:
            return None
        try:
            return os.path.getsize(self.source)
        except OSError:
            return None


@dataclass
class ValidationResult:
    status: str
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    infos: list[dict[str, Any]] = field(default_factory=list)

    @property
    def message(self) -> str:
        msgs = [e.get("message", "") for e in self.errors] or [w.get("message", "") for w in self.warnings]
        return "; ".join(m for m in msgs if m)


@dataclass
class CompatibilityResult:
    compatible: bool | None  # None = could not be determined (service error)
    message: str


class FormatServiceClient:
    """Thin synchronous client; one instance is shared by all jobs of a run (httpx.Client is thread-safe)."""

    def __init__(self, base_url: str, timeout: float = 300.0, transport: httpx.BaseTransport | None = None):
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)
        self._compat_cache: dict[tuple[str, str, str], CompatibilityResult] = {}
        self._known_cache: dict[tuple[str, str], bool | None] = {}

    def close(self) -> None:
        self._http.close()

    def validate(
        self,
        primary: FileRef,
        format_iri: str,
        mode: str = "basic",
        secondaries: Sequence[FileRef] = (),
        expected_crs: str | None = None,
        expected_geometry_type: str | None = None,
    ) -> ValidationResult:
        try:
            namespace, identifier = split_format_iri(format_iri)
        except ValueError as exc:
            return ValidationResult(ERROR, errors=[{"message": str(exc)}])
        data = {"ontology_namespace": namespace, "format_identifier": identifier, "mode": mode}
        if expected_crs:
            data["expected_crs"] = expected_crs
        if expected_geometry_type:
            data["expected_geometry_type"] = expected_geometry_type
        try:
            with contextlib.ExitStack() as stack:
                files = [("file", (primary.basename, stack.enter_context(self._open(primary))))]
                for sec in secondaries:
                    files.append(("secondary_files", (sec.basename, stack.enter_context(self._open(sec)))))
                resp = self._http.post(VALIDATE_PATH, data=data, files=files)
        except (httpx.HTTPError, OSError) as exc:
            return ValidationResult(ERROR, errors=[{"message": f"format service request failed: {exc}"}])
        if resp.status_code != 200:
            return ValidationResult(
                ERROR, errors=[{"message": f"format service HTTP {resp.status_code}: {_detail(resp)}"}]
            )
        body = resp.json()
        return ValidationResult(
            str(body.get("status", ERROR)).upper(),
            errors=body.get("errors", []),
            warnings=body.get("warnings", []),
            infos=body.get("infos", []),
        )

    def compatibility(self, expected: str, actual: str, ontology_url: str) -> CompatibilityResult:
        key = (expected, actual, ontology_url)
        if key in self._compat_cache:
            return self._compat_cache[key]
        payload = {"expected_format": expected, "actual_format": actual, "ontology_schema_url": ontology_url}
        try:
            resp = self._http.post(COMPATIBILITY_PATH, json=payload)
        except httpx.HTTPError as exc:
            return CompatibilityResult(None, f"format service request failed: {exc}")
        if resp.status_code != 200:
            return CompatibilityResult(None, f"format service HTTP {resp.status_code}: {_detail(resp)}")
        body = resp.json()
        result = CompatibilityResult(bool(body.get("compatible")), body.get("message") or "")
        self._compat_cache[key] = result
        return result

    def format_known(self, format_iri: str, ontology_url: str) -> bool | None:
        """Whether the ontology defines the format (None = could not be determined).

        /format-info answers 200 even for unknown classes, just without label or relations.
        """
        key = (format_iri, ontology_url)
        if key in self._known_cache:
            return self._known_cache[key]
        payload = {"format_identifier": format_iri, "ontology_schema_url": ontology_url}
        try:
            resp = self._http.post(FORMAT_INFO_PATH, json=payload)
        except httpx.HTTPError:
            return None
        if resp.status_code == 404:
            known: bool | None = False
        elif resp.status_code != 200:
            return None
        else:
            body = resp.json()
            known = bool(body.get("label") or body.get("parents") or body.get("children") or body.get("equivalents"))
        self._known_cache[key] = known
        return known

    @contextlib.contextmanager
    def _open(self, ref: FileRef) -> Iterator[IO[bytes]]:
        if not ref.is_remote:
            with open(ref.source, "rb") as fh:
                yield fh
            return
        # Remote input: spool it once and upload it (the service has no by-reference mode yet).
        with tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024) as tmp:
            with self._http.stream("GET", ref.source) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_bytes():
                    tmp.write(chunk)
            tmp.seek(0)
            yield tmp  # type: ignore[misc]


def _detail(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("detail", resp.text))
    except ValueError:
        return resp.text[:500]
