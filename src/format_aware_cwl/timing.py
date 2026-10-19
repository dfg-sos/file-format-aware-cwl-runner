"""JSONL instrumentation log for the evaluation (one JSON object per line)."""

from __future__ import annotations

import json
import os
import platform
import threading
import time
import uuid
from importlib.metadata import PackageNotFoundError, version
from typing import Any


def now_ns() -> int:
    return time.perf_counter_ns()


def _version(pkg: str) -> str | None:
    try:
        return version(pkg)
    except PackageNotFoundError:
        return None


class TimingLog:
    """Thread-safe append-only JSONL writer. With path=None all writes are no-ops."""

    def __init__(self, path: str | None, run_id: str | None = None):
        self.run_id = run_id or uuid.uuid4().hex
        self._lock = threading.Lock()
        self._fh = open(path, "a", encoding="utf-8") if path else None  # noqa: SIM115 (closed in close())

    @property
    def enabled(self) -> bool:
        return self._fh is not None

    def write(self, record_type: str, **fields: Any) -> None:
        if self._fh is None:
            return
        line = json.dumps({"record": record_type, "run_id": self.run_id, **fields}, default=str)
        with self._lock:
            self._fh.write(line + "\n")
            self._fh.flush()

    def run_record(self, flags: dict[str, Any], service_url: str | None) -> None:
        self.write(
            "run",
            wall_time=time.time(),
            versions={
                p: _version(p) for p in ("cwltool", "cwl-utils", "schema-salad", "format-aware-cwl-runner", "httpx")
            },
            python=platform.python_version(),
            host=platform.node(),
            platform=platform.platform(),
            machine=platform.machine(),
            processor=platform.processor(),
            cpu_count=os.cpu_count(),
            service_url=service_url,
            flags=flags,
        )

    def close(self) -> None:
        if self._fh is not None:
            with self._lock:
                self._fh.close()
                self._fh = None


def duration_ms(t_start: int, t_end: int) -> float:
    return (t_end - t_start) / 1e6
