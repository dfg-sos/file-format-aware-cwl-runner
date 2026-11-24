"""The run trace (`--trace FILE.jsonl`): what happened in a run, one JSON object per line.

Every record has `record` (its kind) and `run_id`. The core writes `run` (environment, versions, arguments),
`job` (how long a job ran), `cached` and `hook` (how long an extension's job hook took); extensions add their own
observations through `JobContext.record`. Records of one run join on `run_id`, `step` and `job`.
"""

from __future__ import annotations

import json
import os
import platform
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any


def now_ns() -> int:
    return time.perf_counter_ns()


def duration_ms(t_start: int, t_end: int) -> float:
    return (t_end - t_start) / 1e6


@dataclass(frozen=True)
class RunInfo:
    """What a run was started with; written to the `run` record."""

    versions: dict[str, str | None]  # distribution -> version (None if not installed)
    extensions: list[str]
    arguments: dict[str, Any]  # every recorded argument destination -> its parsed value


class Trace:
    """Thread-safe append-only JSONL writer. With path=None all writes are no-ops.

    Opening a trace writes its `run` record first, so every trace says what it was run with.
    """

    def __init__(self, path: str | None, run: RunInfo, run_id: str | None = None):
        self.run_id = run_id or uuid.uuid4().hex
        self._lock = threading.Lock()
        self._fh = open(path, "a", encoding="utf-8") if path else None  # noqa: SIM115 (closed in close())
        self._run_record(run)

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

    def _run_record(self, run: RunInfo) -> None:
        """First record of a run: environment, package versions, extensions and their arguments."""
        self.write(
            "run",
            wall_time=time.time(),
            python=platform.python_version(),
            host=platform.node(),
            platform=platform.platform(),
            machine=platform.machine(),
            processor=platform.processor(),
            cpu_count=os.cpu_count(),
            **asdict(run),
        )

    def close(self) -> None:
        if self._fh is not None:
            with self._lock:
                self._fh.close()
                self._fh = None
