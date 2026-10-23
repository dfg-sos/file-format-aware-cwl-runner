# format-aware-cwl-runner
CWL integration for the SOS File Format Service: design-time format linting and runtime input/output validation for CWL workflows, as an extension to cwltool.

Vanilla cwltool checks format *labels*: a tool's declared output `format` is stamped onto the
produced File without looking at it, so a mislabelled file passes every downstream check.
`cwl-format-aware-runner` runs unmodified cwltool and sends the actual files to the
[SOS File Format Service](../sos-file-format-service) before (pre) and after (post) every step.

- `cwl-format-aware-runner`: cwltool plus runtime validation. Accepts all cwltool flags.
- `cwl-format-lint`: static check that connected ports have compatible formats (ontology subclass).

Pinned versions: cwltool 3.3.20260925135507, cwl-utils 0.45 (see `pyproject.toml` / `uv.lock`).
How it hooks into cwltool: [docs/cwltool-hook-points.md](docs/cwltool-hook-points.md).

## Setup
```sh
uv sync
docker run -d --name sos-ffs -p 8000:8000 \
  -v "$PWD/tests/fixtures/mappings:/app/mappings:ro" \
  ghcr.io/dfg-sos/file-format-service:latest   # API on :8000
```
The service ships no ontology or format mappings. `tests/fixtures/mappings/eo-formats.json` maps
the EO formats ontology's classes to the validator's format IDs; without a mapping, validation
rejects every format. Formats without a validator (EsriJSON, GeoZarr, OSM_JSON, OSM_XML, PBF, VRT,
WKB, XDMF) are not mapped.
Formats come from the standalone EO formats ontology published at
[dfg-sos.github.io/ontologies](https://dfg-sos.github.io/ontologies/) (namespace
`https://dfg-sos.github.io/ontologies/eo-formats#`, readable names like `GeoTIFF`, `Shapefile`,
`Vector`). The `sos:` extension fields are documented there as well. Workflows declare it like this:
```yaml
$namespaces: {eo: "https://dfg-sos.github.io/ontologies/eo-formats#"}
$schemas: [https://dfg-sos.github.io/ontologies/eo-formats.owl]
```

To let the service read files in place instead of receiving uploads, share the directories that
hold the workflow's inputs and cwltool's working directories with the service. Mount them under the
same path and list them in `SOS_FFS_SHARED_DIRS`:
```sh
docker run ... -v /data/runs:/data/runs:ro -e SOS_FFS_SHARED_DIRS=/data/runs ...
```

## Runtime validation
```sh
uv run cwl-format-aware-runner --format-validation-mode full tests/fixtures/a_relabel.cwl tests/fixtures/jobs/a2.yml
```

| Flag | Default | Meaning |
|---|---|---|
| `--format-service-url` | `$SOS_FFS_URL` or `http://localhost:8000` | service base URL |
| `--format-validation off\|warn\|fail` | `fail` | `off` = plain cwltool (baseline); `warn` logs only; `fail` ends the step `permanentFail` |
| `--format-validation-mode basic\|structural\|full` | `basic` | service depth: `basic` checks the file names only (extensions, multi-file components), `structural` also that the files exist, `full` also that they open as the format, plus CRS and geometry |
| `--format-check both\|pre\|post` | `both` | validate step inputs, outputs or both |
| `--format-uncertain warn\|fail` | `warn` | handling of an `UNCERTAIN` result, including formats the service cannot validate (not mapped, no validator) |
| `--format-service-error warn\|fail` | `fail` | service unreachable or request rejected (e.g. unmapped format) |
| `--format-file-transfer auto\|local\|upload` | `auto` | how files reach the service in `structural`/`full` mode: `local` sends paths (`/validate/<mode>/local`), `upload` sends the bytes, `auto` sends paths and falls back to upload when the service cannot read them. In `basic` mode no files are transferred, only their paths are sent. |
| `--format-service-timeout` | `300` | seconds per request |
| `--format-timing-log FILE.jsonl` | none | instrumentation, see below |
| `--format-run-id` | random | run id in the timing log |

Semantics:
- **Which files are checked.** Only Files that carry a `format`. Files without one are skipped and
  logged as `skip`. Arrays, records, scatter and secondaryFiles are walked, with one check per File.
- **What a file is checked against.** Its own `format` label. For outputs, cwltool has already
  evaluated any `format` expression into a concrete label. For inputs, cwltool has already checked
  that the label fits the port, so a GeoTIFF fed into a `Raster` port is validated as GeoTIFF.
- **Shapefiles.** The `.shp` is the primary file and its `secondaryFiles` (`.shx`, `.dbf`, `.prj`)
  are sent with it.
- **How files reach the service.**
  - In `basic` mode only the file names are sent (`/validate/basic`), so nothing is transferred and
    no shared directories are needed.
  - In `structural` and `full` mode, local files are sent by path. If the service has local validation disabled, or the path lies
    outside its shared directories, `auto` uploads the file instead. A "disabled" answer is
    remembered for the rest of the run.
  - Outputs live in cwltool's temporary output directories. Put those inside a shared directory
    with `--tmp-outdir-prefix` (and `--tmpdir-prefix`), otherwise outputs are uploaded.
  - Remote (`http(s)`) File locations are fetched and uploaded.
- **What a failure does.** A failed pre-check marks the step `permanentFail` without running it. A
  failed post-check fails the step after it ran.
- **Service rejections.** A format the service cannot validate counts as `UNCERTAIN`
  (`--format-uncertain`). Invalid `sos:` metadata (e.g. `sos:expectedGeometryType` on a raster, or an
  unknown CRS) counts as an error (`--format-service-error`), because the workflow annotation is wrong.
- **Not checked.** Cached steps (`--cachedir` hits) and ExpressionTools.
- **`full` mode extensions.** Ports can declare the CRS and geometry type the file must have:
  ```yaml
  $namespaces: {sos: "https://dfg-sos.github.io/ontologies/cwl#"}
  outputs:
    roads: {type: File, format: eo:GeoJSON, sos:expectedCRS: "EPSG:4326", sos:expectedGeometryType: LineString}
  ```

### Timing log (JSONL, one object per line, all with `record` and `run_id`)
| `record` | Fields |
|---|---|
| `run` | versions (cwltool, cwl-utils, schema-salad, this package, httpx), python, host, platform, cpu_count, service_url, flags |
| `check` | step, job, port, direction (`pre`/`post`), file, size_bytes, format, mode, result, message, transfer (`local`/`upload`; `null` in basic mode, where no file is sent), server_timing (the service's `Server-Timing` durations in ms, e.g. `receive`/`resolve`, `validate`), t_start, t_end (ns, monotonic), duration_ms (client round trip) |
| `main` | step, job, main_duration_ms: the tool's command (for containers including `docker run` start-up) |
| `skip` | step, job, port, direction, file, reason |
| `cached` | step |

`step` is the workflow step id; `job` is cwltool's unique job name (`_2`, `_3`… for scatter elements).

## Design-time linter
```sh
uv run cwl-format-lint tests/fixtures/d_shapefile_to_geotiff.cwl
uv run cwl-format-lint --json ...   # machine-readable
```
Every connection (workflow input or step output → step input or workflow output, nested workflows
included) is checked with `/compatibility`. A connection is compatible if every source format is
compatible with at least one sink format, in at least one of the ontologies.

Other statuses:
- `unknown-format`: a format that no ontology defines (the service answers 422), e.g. a typo or
  the wrong ontology.
- `expression`: the format is an expression; skipped.
- `unannotated`: the port has no `format`. `--strict` makes these fail the lint.

Exit code 1 on `incompatible`, `unknown-format` or service `error`.

The ontologies are all of the document's `$schemas` entries, or the repeatable
`--format-ontology-url`. The **service** fetches them, so they must be reachable from the service.
Use `--format-ontology-url file:///ontology/eo-formats.owl` for a copy mounted into the service.

Other online ontologies work too. The official EDAM (`http://edamontology.org/EDAM.owl`) takes
about 4 s to fetch and parse the first time, then the service caches it. It contains no EO
formats, so `eo:` formats checked against EDAM alone are `unknown-format` (fixture F).

## Tests
```sh
uv run pytest              # unit tests, service mocked
uv run pytest -m service   # acceptance tests against the running service (fixtures A–F)
SOS_FFS_TEST_SHARED_DIR=/path/shared/with/service uv run pytest -m service   # also tests by-path validation
```
Fixtures in `tests/fixtures/`:

| Fixture | What it shows |
|---|---|
| A1 / A2 | GeoJSON labelled GeoTIFF: vanilla cwltool passes, validation fails (A1 in basic mode, A2 only in full) |
| A, container | `a_relabel_docker.cwl`: the same run in Docker; skipped without Docker |
| B | wrong CRS |
| C | wrong geometry type |
| D | Shapefile → GeoTIFF (incompatible) / → Vector (compatible), linter |
| E | unannotated ports are skipped |
| F | the official online EDAM (EO formats are unknown there), linter |

Data is generated by `tests/fixtures/make_data.py`.

## Benchmark
```sh
../sos-file-format-service/.venv/bin/python bench/make_inputs.py 1 10 100   # GeoTIFF inputs
uv run python bench/run.py bench/raster_chain.cwl bench/inputs/raster_10MB.yml --repeat 10
# upload vs. by-path (inputs and --tmp-outdir-prefix inside the service's shared dirs):
uv run python bench/run.py ... --transfers upload,local --tmp-outdir-prefix /shared/tmp/
```
Each repetition runs a fresh process per variant: `off`, `basic` (no file transfer), and `structural` and
`full` combined with each transfer, with validation in `warn`. The variants are interleaved.
Results go to `bench/results/<timestamp>/`:
- `timing.jsonl`: every log record;
- `runs.csv`: per run the wall time, exit code, and summed check, service-side validation and
  main-command time.
