"""Find annotated File objects in CWL job orders and outputs and turn them into FileRefs."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from typing import Any
from urllib.parse import urlsplit

from schema_salad.ref_resolver import uri_file_path

from .client import FileRef


def iter_files(value: Any) -> Iterator[Mapping[str, Any]]:
    """Yield every File object in a port value (arrays and records walked recursively).

    secondaryFiles are not yielded on their own; they travel with their primary.
    Directories are skipped (out of scope for v1).
    """
    if isinstance(value, Mapping):
        cls = value.get("class")
        if cls == "File":
            yield value
        elif cls is None:  # record
            for v in value.values():
                yield from iter_files(v)
    elif isinstance(value, list):
        for v in value:
            yield from iter_files(v)


def default_resolve(location: str) -> str:
    """Map a CWL location to something the client can read: a local path or an http(s) URL."""
    scheme = urlsplit(location).scheme
    if scheme == "file":
        return uri_file_path(location)
    return location  # http(s) or already a path


def to_ref(f: Mapping[str, Any], resolve: Callable[[str], str] = default_resolve) -> FileRef:
    location = str(f.get("location") or f.get("path"))
    basename = str(f.get("basename") or location.rstrip("/").rsplit("/", 1)[-1])
    return FileRef(resolve(location), basename)


def secondary_refs(f: Mapping[str, Any], resolve: Callable[[str], str] = default_resolve) -> list[FileRef]:
    return [to_ref(s, resolve) for s in f.get("secondaryFiles") or [] if s.get("class") == "File"]
