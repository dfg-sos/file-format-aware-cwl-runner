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
cd ../sos-file-format-service && docker compose up -d --build   # API :8000, ontology :8080
```

## Runtime validation
```sh
uv run cwl-format-aware-runner --format-validation-mode full tests/fixtures/a_relabel.cwl tests/fixtures/jobs/a2.yml
```

| Flag | Default | Meaning |
|---|---|---|
| `--format-service-url` | `$SOS_FFS_URL` or `http://localhost:8000` | service base URL |
| `--format-validation off\|warn\|fail` | `fail` | `off` = plain cwltool (baseline); `warn` logs only; `fail` ends the step `permanentFail` |
| `--format-validation-mode basic\|structural\|full` | `basic` | service depth: extension / files present / open file, CRS, geometry |
| `--format-check both\|pre\|post` | `both` | validate step inputs, outputs or both |
| `--format-uncertain warn\|fail` | `warn` | handling of an `UNCERTAIN` result (e.g. formats without a validator) |
| `--format-service-error warn\|fail` | `fail` | service unreachable or request rejected (e.g. unmapped format) |
| `--format-service-timeout` | `300` | seconds per request |
| `--format-timing-log FILE.jsonl` | none | instrumentation, see below |
| `--format-run-id` | random | run id in the timing log |

Semantics:
- **Which files are checked.** Only Files that carry a `format`. Files without one are skipped and
  logged as `skip`. Arrays, records, scatter and secondaryFiles are walked, with one check per File.
- **What a file is checked against.** Its own `format` label. For outputs, cwltool has already
  evaluated any `format` expression into a concrete label. For inputs, cwltool has already checked
  that the label fits the port, so a GeoTIFF fed into a `raster` port is validated as GeoTIFF.
- **Shapefiles.** The `.shp` is the primary file and its `secondaryFiles` (`.shx`, `.dbf`, `.prj`)
  are uploaded with it.
- **Files outside the local filesystem.** Remote (`http(s)`) File locations are fetched and
  uploaded. The service has no by-reference mode yet, so every file is uploaded, even when the
  service could read it directly (open issue in sos-file-format-service).
- **What a failure does.** A failed pre-check marks the step `permanentFail` without running it. A
  failed post-check fails the step after it ran.
- **Not checked.** Cached steps (`--cachedir` hits) and ExpressionTools.
- **`full` mode extensions.** Ports can declare the CRS and geometry type the file must have:
  ```yaml
  $namespaces: {sos: "https://w3id.org/sos/cwl#"}
  outputs:
    roads: {type: File, format: edam:format_4106, sos:expectedCRS: "EPSG:4326", sos:expectedGeometryType: LineString}
  ```

### Timing log (JSONL, one object per line, all with `record` and `run_id`)
| `record` | Fields |
|---|---|
| `run` | versions (cwltool, cwl-utils, schema-salad, this package, httpx), python, host, platform, cpu_count, service_url, flags |
| `check` | step, job, port, direction (`pre`/`post`), file, size_bytes, format, mode, result, message, t_start, t_end (ns, monotonic), duration_ms |
| `main` | step, job, main_duration_ms: the tool's command (for containers including `docker run` start-up) |
| `skip` | step, job, port, direction, file, reason |
| `cached` | step |

`step` is the workflow step id; `job` is cwltool's unique job name (`_2`, `_3`… for scatter elements).

## Design-time linter
```sh
uv run cwl-format-lint --format-ontology-url http://ontology/edam_eo.owl tests/fixtures/d_shapefile_to_geotiff.cwl
uv run cwl-format-lint --json ...   # machine-readable
```
Every connection (workflow input or step output → step input or workflow output, nested workflows
included) is checked with `/compatibility`. A connection is compatible if every source format is
compatible with at least one sink format, in at least one of the ontologies.

Other statuses:
- `unknown-format`: a format that no ontology defines, checked via `/format-info`. Without this
  check it would look like `incompatible`.
- `expression`: the format is an expression; skipped.
- `unannotated`: the port has no `format`. `--strict` makes these fail the lint.

Exit code 1 on `incompatible`, `unknown-format` or service `error`.

The ontologies are all of the document's `$schemas` entries, or the repeatable
`--format-ontology-url`. The **service** fetches them, so they must be reachable from the service.
With the docker-compose setup, `localhost:8080` is not reachable from inside the API container, so
pass `--format-ontology-url http://ontology/edam_eo.owl`.

Online ontologies work. The official EDAM (`http://edamontology.org/EDAM.owl`, also versioned
`EDAM_1.25.owl`) takes about 4 s to fetch and parse the first time, then the service caches it.
It contains no EO formats (GeoTIFF, GeoJSON, Shapefile, …; only `TIFF` format_3591 and `NetCDF`
format_3650). The EO IDs `format_4100`–`format_4126` exist only in the service's adapted ontology
and are reported as `unknown-format` against official EDAM (fixture F).

## Tests
```sh
uv run pytest              # unit tests, service mocked
uv run pytest -m service   # acceptance tests against the running service (fixtures A–E)
```
Fixtures in `tests/fixtures/`:

| Fixture | What it shows |
|---|---|
| A1 / A2 | GeoJSON labelled GeoTIFF: vanilla cwltool passes, validation fails (A1 in basic mode, A2 only in full) |
| A, container | `a_relabel_docker.cwl`: the same run in Docker; skipped without Docker |
| B | wrong CRS |
| C | wrong geometry type |
| D | Shapefile → GeoTIFF (incompatible) / → vector (compatible), linter |
| E | unannotated ports are skipped |
| F | the official online EDAM, linter |

Data is generated by `tests/fixtures/make_data.py`.

## Benchmark
```sh
../sos-file-format-service/.venv/bin/python bench/make_inputs.py 1 10 100   # GeoTIFF inputs
uv run python bench/run.py bench/raster_chain.cwl bench/inputs/raster_10MB.yml --repeat 10
```
Each repetition runs a fresh process per mode (`off`, `basic`, `structural`, `full`; validation in
`warn`), with the modes interleaved. Results go to `bench/results/<timestamp>/` as `timing.jsonl`
and `runs.csv` (wall time, exit code, summed check and main-command time per run).
