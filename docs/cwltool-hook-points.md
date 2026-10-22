# cwltool 3.3 hook points (spike results)

Run on cwltool 3.3.20260925135507 (PyPI ships only a pure-Python `py3-none-any` wheel, so
instance attributes and module functions can be patched), Python 3.12.
The throwaway spike code has been removed. Each finding below is covered by a test:
`tests/test_runner.py` (host jobs, mocked service) and
`tests/test_integration.py::test_container_jobs_are_checked` (Docker jobs, live service).

## Confirmed (`CommandLineJob` / `--no-container` path)
| Question | Result |
|---|---|
| Our `CommandLineTool` subclass is used for workflow steps via `LoadingContext.construct_tool_object` | yes |
| Pre-check in `job()` before yield sees bound inputs | yes. `j.builder.job` holds Files with `format`; `File.path` is the staged path, `j.pathmapper.mapper(location).resolved` is the host path |
| Post-check by wrapping `j.collect_outputs` sees the stamped `format` | yes. `location` is `file://` on the host |
| Raising `WorkflowException` in the wrapper | job, step and workflow end `permanentFail` with our message |
| Step label | `j.name` (`produce`, `consume`); `runtimeContext.part_of` = `step <name>` |
| Namespaced port extension `sos:expectedCRS` | kept on `tool["outputs"][i]` under `https://dfg-sos.github.io/ontologies/cwl#expectedCRS` |
| Main-command timing | patching `cwltool.job._job_popen` works; it receives `name=j.name`, so each timing is tied to its job |
| Mislabelled output (GeoJSON content stamped as GeoTIFF) | passes vanilla checks downstream (fixture A premise holds) |

## Container path (`tests/fixtures/a_relabel_docker.cwl`)
- Containerised steps run as `DockerCommandLineJob`. The same pre-check and post-wrapper fired.
- `File.path` was the container path (`/var/lib/cwl/stg…/out.tif`); `pathmapper…resolved` gave the host path.
- `_job_popen` timing covers the whole `docker run` (~1 s for a trivial command), so for container
  steps `main_duration_ms` includes container start-up. Note this in the paper.

## Service check on the spike output
A GeoJSON payload named `out.tif` and labelled `eo:GeoTIFF` (fixture A2):
- `basic`: SUCCESS (extension only).
- `full`: FAILURE, cause `file_open_error` (RasterIO cannot open it).

This is fixture A2: label checks and `basic` miss it, `full` catches it.

**Verdict: extension approach is viable; no fork needed.**
