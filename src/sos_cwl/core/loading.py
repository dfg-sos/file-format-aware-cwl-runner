"""Load a CWL document with cwltool, outside a run (for design-time checks), and read its prefixed names."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from cwltool.context import LoadingContext
from cwltool.load_tool import load_tool
from cwltool.process import Process
from cwltool.workflow import Workflow, default_make_tool


def load(path: str | Path) -> Process:
    """Load as cwltool does (`--strict`): namespaced keys expanded, invalid CWL rejected."""
    context = LoadingContext({"strict": True})
    context.construct_tool_object = default_make_tool
    return load_tool(str(Path(path).resolve()) if "://" not in str(path) else str(path), context)


def command_line_tools(process: Process) -> Iterator[Process]:
    """The CommandLineTools of a tool or (nested) workflow, each once."""
    seen: set[str] = set()

    def walk(p: Process) -> Iterator[Process]:
        if isinstance(p, Workflow):
            for step in p.steps:
                yield from walk(step.embedded_tool)
        elif p.tool.get("class") == "CommandLineTool" and p.tool["id"] not in seen:
            seen.add(p.tool["id"])
            yield p

    yield from walk(process)


def namespaces(process: Process) -> dict[str, Any]:
    """$namespaces of the document that defines the tool (also for tools embedded via `run:`)."""
    return dict(process.metadata.get("$namespaces", {}))


def expand(value: Any, namespaces: Mapping[str, str]) -> Any:
    """Expand `prefix:Name` with the document's $namespaces; other values are returned unchanged.

    schema-salad expands namespaced keys but leaves values nested inside extension fields as written,
    so prefixed names there have to be expanded by the extension.
    """
    if isinstance(value, str) and ":" in value and "://" not in value:
        prefix, rest = value.split(":", 1)
        if prefix in namespaces:
            return namespaces[prefix] + rest
    return value
