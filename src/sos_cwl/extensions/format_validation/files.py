"""Turn CWL File objects into the FileRefs the format service client sends."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sos_cwl.core.files import default_resolve

from .client import FileRef


def to_ref(f: Mapping[str, Any], resolve: Callable[[str], str] = default_resolve) -> FileRef:
    location = str(f.get("location") or f.get("path"))
    basename = str(f.get("basename") or location.rstrip("/").rsplit("/", 1)[-1])
    return FileRef(resolve(location), basename)


def secondary_refs(f: Mapping[str, Any], resolve: Callable[[str], str] = default_resolve) -> list[FileRef]:
    return [to_ref(s, resolve) for s in f.get("secondaryFiles") or [] if s.get("class") == "File"]
