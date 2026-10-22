"""HTTP client for the SOS File Format Service."""

from __future__ import annotations

import contextlib
import os
import tempfile
import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import IO, Any
from urllib.parse import urlsplit

import httpx

VALIDATE_PATH = "/api/v1/validate"
VALIDATE_LOCAL_PATH = "/api/v1/validate/local"
COMPATIBILITY_PATH = "/api/v1/compatibility"

SUCCESS = "SUCCESS"
UNCERTAIN = "UNCERTAIN"
FAILURE = "FAILURE"
ERROR = "ERROR"  # client-side: service unreachable or rejected the request

# How a file reaches the service: by path on shared storage, or as an upload.
AUTO, LOCAL, UPLOAD = "auto", "local", "upload"


def split_format_iri(iri: str) -> tuple[str, str]:
    """Split a format IRI into (ontology_namespace, format_identifier) after the last '#' or '/'.

    The namespace keeps its separator (`…/ontologies/eo-formats#`), as the service's mappings do.
    """
    cut = max(iri.rfind("#"), iri.rfind("/"))
    if cut <= 0 or cut == len(iri) - 1:
        raise ValueError(f"not a format IRI: {iri!r}")
    return iri[: cut + 1], iri[cut + 1 :]


def parse_server_timing(header: str | None) -> dict[str, float]:
    """`receive;dur=1.8, validate;dur=812.3` -> {"receive": 1.8, "validate": 812.3}."""
    timings: dict[str, float] = {}
    for metric in (header or "").split(","):
        name, *params = (p.strip() for p in metric.split(";"))
        for param in params:
            key, _, value = param.partition("=")
            if name and key == "dur":
                with contextlib.suppress(ValueError):
                    timings[name] = float(value)
    return timings


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
    transfer: str | None = None  # local | upload, as actually used
    server_timing: dict[str, float] = field(default_factory=dict)

    @property
    def message(self) -> str:
        msgs = [e.get("message", "") for e in self.errors] or [w.get("message", "") for w in self.warnings]
        return "; ".join(m for m in msgs if m)


@dataclass
class CompatibilityResult:
    compatible: bool | None  # None = not determined (unknown format or service error)
    message: str
    unknown_formats: list[str] = field(default_factory=list)


class FormatServiceClient:
    """Thin synchronous client; one instance is shared by all jobs of a run (httpx.Client is thread-safe)."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 300.0,
        transfer: str = AUTO,
        transport: httpx.BaseTransport | None = None,
    ):
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)
        self.transfer = transfer
        self._local_disabled = False  # set once the service reports /validate/local as disabled
        self._lock = threading.Lock()
        self._compat_cache: dict[tuple[str, str, str], CompatibilityResult] = {}

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
        fields = {"ontology_namespace": namespace, "format_identifier": identifier, "mode": mode}
        if expected_crs:
            fields["expected_crs"] = expected_crs
        if expected_geometry_type:
            fields["expected_geometry_type"] = expected_geometry_type

        refs = [primary, *secondaries]
        by_path = self.transfer != UPLOAD and not any(r.is_remote for r in refs)
        if by_path and (self.transfer == LOCAL or not self._local_disabled):
            resp = self._post_local(fields, primary, secondaries)
            if isinstance(resp, ValidationResult) or self.transfer == LOCAL or resp.status_code not in (403, 404):
                return self._result(resp, LOCAL)
            if "disabled" in _detail(resp).lower():
                with self._lock:
                    self._local_disabled = True
            # auto: the service cannot read this path (outside its shared dirs) -> upload instead
        return self._result(self._post_upload(fields, primary, secondaries), UPLOAD)

    def _post_local(
        self, fields: dict[str, str], primary: FileRef, secondaries: Sequence[FileRef]
    ) -> httpx.Response | ValidationResult:
        payload = {
            **fields,
            "file_path": os.path.abspath(primary.source),
            "secondary_file_paths": [os.path.abspath(s.source) for s in secondaries],
        }
        try:
            return self._http.post(VALIDATE_LOCAL_PATH, json=payload)
        except httpx.HTTPError as exc:
            return ValidationResult(ERROR, errors=[{"message": f"format service request failed: {exc}"}])

    def _post_upload(
        self, fields: dict[str, str], primary: FileRef, secondaries: Sequence[FileRef]
    ) -> httpx.Response | ValidationResult:
        try:
            with contextlib.ExitStack() as stack:
                files = [("file", (primary.basename, stack.enter_context(self._open(primary))))]
                for sec in secondaries:
                    files.append(("secondary_files", (sec.basename, stack.enter_context(self._open(sec)))))
                return self._http.post(VALIDATE_PATH, data=fields, files=files)
        except (httpx.HTTPError, OSError) as exc:
            return ValidationResult(ERROR, errors=[{"message": f"format service request failed: {exc}"}])

    @staticmethod
    def _result(resp: httpx.Response | ValidationResult, transfer: str) -> ValidationResult:
        if isinstance(resp, ValidationResult):
            resp.transfer = transfer
            return resp
        timing = parse_server_timing(resp.headers.get("server-timing"))
        if resp.status_code != 200:
            message = f"format service HTTP {resp.status_code}: {_detail(resp)}"
            return ValidationResult(ERROR, errors=[{"message": message}], transfer=transfer, server_timing=timing)
        body = resp.json()
        return ValidationResult(
            str(body.get("status", ERROR)).upper(),
            errors=body.get("errors", []),
            warnings=body.get("warnings", []),
            infos=body.get("infos", []),
            transfer=transfer,
            server_timing=timing,
        )

    def compatibility(self, expected: str, actual: str, ontology_url: str) -> CompatibilityResult:
        """Whether `actual` is `expected` or a subclass of it.

        A format the ontology does not define gives compatible=None with `unknown_formats` set (service 422).
        """
        key = (expected, actual, ontology_url)
        if key in self._compat_cache:
            return self._compat_cache[key]
        payload = {"expected_format": expected, "actual_format": actual, "ontology_schema_url": ontology_url}
        try:
            resp = self._http.post(COMPATIBILITY_PATH, json=payload)
        except httpx.HTTPError as exc:
            return CompatibilityResult(None, f"format service request failed: {exc}")
        body = _json(resp)
        detail = body.get("detail") if isinstance(body, dict) else None
        if resp.status_code == 422 and isinstance(detail, dict) and "unknown_formats" in detail:
            result = CompatibilityResult(None, detail.get("message", ""), list(detail["unknown_formats"]))
        elif resp.status_code == 200:
            result = CompatibilityResult(bool(body.get("compatible")), body.get("message") or "")
        else:
            return CompatibilityResult(None, f"format service HTTP {resp.status_code}: {_detail(resp)}")
        self._compat_cache[key] = result
        return result

    @contextlib.contextmanager
    def _open(self, ref: FileRef) -> Iterator[IO[bytes]]:
        if not ref.is_remote:
            with open(ref.source, "rb") as fh:
                yield fh
            return
        # Remote input: spool it once and upload it.
        with tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024) as tmp:
            with self._http.stream("GET", ref.source) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_bytes():
                    tmp.write(chunk)
            tmp.seek(0)
            yield tmp  # type: ignore[misc]


def _json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return None


def _detail(resp: httpx.Response) -> str:
    body = _json(resp)
    if isinstance(body, dict) and "detail" in body:
        return str(body["detail"])
    return resp.text[:500]
