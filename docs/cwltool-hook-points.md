# How the core hooks into cwltool

The core extends cwltool without forking or patching it. It uses one documented extension point, the
tool factory in `LoadingContext`. It also replaces two methods on each job object cwltool creates,
which works because cwltool ships as pure Python and its executors call those methods through the
instance. Everything below refers to the pinned cwltool 3.3.20260925135507. A cwltool upgrade must
re-check these points; the tests listed at the end do.

Code: [`src/sos_cwl/core/tool.py`](../src/sos_cwl/core/tool.py).

## Hook points

| Extension hook | Where the core attaches | What it relies on |
|---|---|---|
| `on_tool(tool)` | `LoadingContext.construct_tool_object = Runtime.make_tool`: every `CommandLineTool` becomes an `ExtensibleCommandLineTool`; other classes go to cwltool's `default_make_tool` | cwltool builds every process through this factory, workflow steps included (`load_tool.py`, `workflow.py`) |
| `before_job(ctx)` | `ExtensibleCommandLineTool.job()` calls cwltool's `job()` and runs the hook on each job before yielding it | the yielded `JobBase` already holds the bound inputs (`j.builder.job`) and the path mapper |
| `after_job(ctx, outputs)` | the job's `collect_outputs` is replaced by a wrapper that collects as before, then runs the hook | `JobBase._execute` calls `self.collect_outputs(...)` after the command; outputs carry their `format` |
| `job` trace record | the job's `run` is replaced by a wrapper that times it (only with `--trace`) | both executors call `job.run(runtime_context)` (`executors.py`) |

### Failing a step
- **Before the job:** the core calls `j.output_callback({}, "permanentFail")` and does not yield the
  job. The command never runs, the step ends `permanentFail`, and steps that do not depend on it still run.
- **After the job:** the wrapper raises `WorkflowException`. `JobBase._execute` catches it, so the
  step ends `permanentFail` with the extensions' reasons as message.

### Files
- `File.path` in the bound inputs is the staged path, which for container jobs is the path inside
  the container. `JobContext.resolve(location)` returns the host path via
  `j.pathmapper.mapper(location).resolved`.
- Collected outputs have `file://` locations on the host and the `format` the tool declares.
- Namespaced fields on ports (e.g. `sos:expectedCRS`) are kept in `tool["inputs"]` / `tool["outputs"]`,
  keyed by the expanded IRI (`https://dfg-sos.github.io/ontologies/cwl#expectedCRS`).

### Step names
`step` is `runtimeContext.name` (the workflow step id), or the tool's short id when a tool is run
directly. `job` is cwltool's unique job name (`_2`, `_3`, … for scatter elements).

## Special cases
- **Container jobs** (`DockerCommandLineJob`) go through the same hooks. The `job` duration covers
  the whole `docker run`, including container start-up and, the first time, the image pull.
- **Cache hits** (`--cachedir`): cwltool yields a `CallbackJob` instead of a `JobBase`. Nothing is
  executed, so no hooks run; the core writes a `cached` record.
- **No active extension**: the job is yielded unchanged, so the run is plain cwltool. With `--trace`
  only `run` is wrapped, for the `job` record.

## Tests
- [`tests/core/test_runner.py`](../tests/core/test_runner.py): all hooks with a recording
  extension, failing before and after a job, cache hits, the trace.
- [`tests/format_validation/test_runner.py`](../tests/format_validation/test_runner.py): host jobs
  with a mocked format service.
- `tests/format_validation/test_integration.py::test_container_jobs_are_checked`: Docker jobs
  against a running service (`-m integration`).
