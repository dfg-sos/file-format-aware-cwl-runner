# SOS CWL Runner
Unmodified [cwltool](https://github.com/common-workflow-language/cwltool) with the CWL extensions of
the DFG project SOS. A small **core** hooks into cwltool; **extensions** use the hooks.

| Extension | Design time (`sos-cwl-lint`) | Run time (`sos-cwl-runner`) | Docs |
|---|---|---|---|
| `format-validation` | connected ports have compatible formats | validate the real files of each step with the [SOS File Format Service](https://github.com/dfg-sos/file-format-service) | [format-validation.md](docs/extensions/format-validation.md) |

The extension fields (`sos:expectedCRS`, `sos:expectedGeometryType`) and the vocabularies they
refer to are defined at [dfg-sos.github.io/ontologies](https://dfg-sos.github.io/ontologies/).

Pinned versions: cwltool 3.3.20260925135507, cwl-utils 0.45 (see `pyproject.toml` / `uv.lock`).

## Use
```sh
uv sync
uv run sos-cwl-runner [cwltool flags] [extension flags] workflow.cwl job.yml
uv run sos-cwl-lint [--extension NAME] [--strict] documents.cwl...
```
- `sos-cwl-runner` accepts every cwltool flag, plus each extension's flags (`--format-...`).
  `uv run sos-cwl-runner --help` lists them by extension.
- `sos-cwl-lint` runs the design-time checks of all extensions, or of those given with `--extension`.
  Exit code 1 on errors (`--strict`: also on warnings).

Without any extension flags `sos-cwl-runner` behaves like plain cwltool.

### Run trace
`--trace FILE.jsonl` appends a trace of the run, for analysing it afterwards: one JSON object per line,
each with `record` and `run_id` (`--run-id`, default random). Records of one run join on `run_id`, `step`
(the workflow step id) and `job` (cwltool's unique job name, `_2`, `_3`… for scatter elements).
The core writes:

| `record` | Fields |
|---|---|
| `run` | wall_time, versions (cwltool, cwl-utils, schema-salad, and each extension's distribution with its requirements), python, host, platform, machine, processor, cpu_count, extensions, arguments (the core's and every extension's, not cwltool's) |
| `job` | step, job, t_start, t_end (ns, monotonic), duration_ms: the whole job as cwltool runs it (staging, for containers image pull and start-up, the command, collecting outputs including the `after_job` hooks; `before_job` hooks run before it) |
| `hook` | extension, hook (`before_job`/`after_job`), step, job, failed, t_start, t_end, duration_ms: one extension hook for one job |
| `cached` | step (a `--cachedir` hit; no hooks run) |

The extensions add their own observations (`check`, `skip`), see their docs.

## Layout
```
src/sos_cwl/core/                           hooks into cwltool, CLIs, run trace; knows no extension
src/sos_cwl/extensions/format_validation/   File Format Service client, runtime validation, format lint
tests/core/                                 the hooks, with a recording extension
tests/format_validation/                    one folder per extension, with its own fixtures
docs/cwltool-hook-points.md                 how the core hooks into cwltool (no fork)
```
Each extension imports only `sos_cwl.core`, never another extension, and the core imports no
extension (checked by `tests/core/test_layering.py`). The core finds the extensions through the
entry point group `sos_cwl.extensions` in `pyproject.toml`.

## Writing an extension
Subclass `sos_cwl.core.extension.Extension`, override the hooks you need and register the class
under `[project.entry-points."sos_cwl.extensions"]`:

| Hook | When |
|---|---|
| `add_arguments(group)`, `configure(args)` | building and parsing cwltool's arguments; the core creates the group, titled `title` (or `name`), and records its arguments in the trace; `configure` raises `UsageError` for invalid combinations |
| `on_tool(tool)` | every CommandLineTool cwltool constructs (load time) |
| `before_job(ctx) -> Verdict` | before a job's command; `Verdict.fail(...)` ends the step `permanentFail` without running it |
| `after_job(ctx, outputs) -> Verdict` | after its outputs are collected (only if `wants_outputs`); `Verdict.fail(...)` fails the step |
| `active` | only active extensions get the job hooks, so an inactive one costs nothing at run time |
| `close()` | after the run |
| `add_lint_arguments(group)`, `lint(document, args) -> LintResult` | `sos-cwl-lint` |

`ctx` ([`JobContext`](src/sos_cwl/core/extension.py)) gives the step and job name, the bound inputs,
the tool, `resolve(location)` for host paths of staged files and `record(kind, **fields)` to add an
observation of the job to the run trace (a no-op without `--trace`).

## Tests
```sh
uv run pytest                    # all unit tests (format service mocked; integration tests deselected)
uv run pytest tests/core         # the core alone, without any extension
uv run pytest tests/format_validation -m integration   # against a running File Format Service, see format-validation.md
```

## Evaluation
The evaluation of the format extension (fault-injection scenarios, overhead benchmarks on an HPC
node, raw results) lives in the artifact repository
[format-aware-cwl-icsa27-artifact](https://github.com/dfg-sos/format-aware-cwl-icsa27-artifact).
It uses version 0.2.0 of this repository.
