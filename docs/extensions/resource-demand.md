# Extension: resource demand
Annotates how the memory and time of a tool grow with its inputs (**parametric dependencies**),
next to the input schema. `sos-cwl-lint` validates the annotation with SHACL against the
[SOS vocabularies](https://dfg-sos.github.io/ontologies/) and shows it in Big O notation;
`sos-cwl-runner` logs it with the measured inputs of every job. The annotation states only the
**shape**; an estimator, a separate service, fits the coefficients to the measurements.

## Annotation
```yaml
$schemas: [https://dfg-sos.github.io/ontologies/releases/eo-formats/1.2.0/eo-formats.owl]
$namespaces:
  eo:  "https://dfg-sos.github.io/ontologies/eo-formats#"
  rd:  "https://dfg-sos.github.io/ontologies/resource-demand#"
hints:
  ResourceRequirement:
    rd:ramDemand:                          # O(n + v)
      - {n: rd:Linear}
      - {v: rd:Linear}
    rd:timeDemand:                         # O(b · n + v): rasterize the zones, scan every band
      - {b: rd:Linear, n: rd:Linear}
      - {v: rd:Linear}
inputs:
  raster:
    type: File
    format: eo:GeoTIFF
    rd:complexityVariables:
      - {symbol: n, measure: eo:PixelCount}
      - {symbol: b, measure: eo:BandCount}
  zones:
    type: File
    format: eo:GeoJSON
    rd:complexityVariables:
      - {symbol: v, measure: eo:VertexCount}
```
- **Inputs** declare *what* drives demand: variables, each a `symbol` and a `measure`.
- **`ResourceRequirement`** (`hints` or `requirements`) declares *how*, per resource: a list of
  terms that are **added**, each mapping variables to complexity classes that are **multiplied**.
  `{}` is a constant; `k: rd:Constant` says `k` was considered and has no effect.
- Plain cwltool accepts and ignores the annotation. Symbols must not be `id`, `name`, `type` or
  `format`, which CWL's loader rewrites into IRIs.

| Vocabulary terms | |
|---|---|
| Resources | `rd:ramDemand` (MiB, as `ramMin`), `rd:timeDemand` (seconds, wall clock) |
| Complexity classes | `rd:Constant`, `Logarithmic`, `Linear`, `Linearithmic`, `Quadratic`, `Cubic`, `Exponential` |
| Direct measures | `rd:Value` (numbers), `rd:ArrayLength` (arrays), `rd:FileSize` (File, File[]) |
| Domain measures | `rd:Measure` subclasses from `$schemas`, e.g. `eo:PixelCount`, `eo:FeatureCount`; `rd:appliesToFormat` names their formats |
| Derived measures | `rd:DerivedMeasure` + `probe: probes/x.cwl`, see [Probes](#probes) |

Examples, all tested: [`tests/resource_demand/cwl/`](../../tests/resource_demand/cwl/).

## Design time: `sos-cwl-lint`
```sh
uv run sos-cwl-lint --extension resource-demand tests/resource_demand/cwl/zonal-stats.cwl
```
```
[resource-demand] tests/resource_demand/cwl/zonal-stats.cwl
  tests/resource_demand/cwl/zonal-stats.cwl
    n = eo:PixelCount(raster)
    b = eo:BandCount(raster)
    v = eo:VertexCount(zones)
    ram:  O(n + v)
    time: O(b · n + v)
```
The vocabularies: `rd:` is a release, `--resource-demand-vocabulary VERSION` (default `1.2.0`),
downloaded once into `~/.cache/sos-cwl/` (or `$SOS_CWL_CACHE`), or the URL or path of an unreleased
file; domain vocabularies are the document's `$schemas`. The SHACL shapes
([`shapes.ttl`](../../src/sos_cwl/extensions/resource_demand/shapes.ttl)) check that
- a `symbol` is a name and a `measure` a `rd:Measure` subclass that fits its input: its type
  (`Value` on numbers, ...) and, with `rd:appliesToFormat`, its declared format;
- `DerivedMeasure` has a `probe` and no other measure has one;
- every factor names a declared variable and a complexity class; unused variables are warnings;
- a variable has no unexpected keys (a misspelled `meassure`).

Probes are checked against their [contract](#probes) by loading them. Malformed annotations
(no `symbol`, a symbol twice, a demand that is not a list of mappings) are reported before SHACL.

## Run time: `demand` records
```sh
uv run sos-cwl-runner --trace run.jsonl --resource-demand log tests/resource_demand/cwl/concat.cwl tests/resource_demand/cwl/jobs/concat.yml
```
- `--resource-demand log` (needs `--trace`) adds a `demand` record per job of an annotated tool;
  `off` (the default) does not read the annotations. A job is never changed.
- `--resource-demand-probes` also runs the probes of derived measures; without, their value is `null`.

| `record` | Fields |
|---|---|
| `demand` | step, job, tool, source (`hints`/`requirements`), variables (`{symbol: {port, measure, value}}`, probed ones also `probe_ms` and `error`), demands (`{ram\|time: [[{variable, complexity}, ...], ...]}`) |

With the `job` record of the same `job` it forms one sample for fitting the coefficients.

## Probes
A probe computes a derived measure: `{symbol: c, measure: rd:DerivedMeasure, probe: probes/cloud-fraction.cwl}`
([example](../../tests/resource_demand/cwl/probes/cloud-fraction.cwl)). Its contract: a
`CommandLineTool` with exactly one input, of the annotated input's type, and exactly one numeric output.

The runner runs it before the job with cwltool's Python API, staged and containerised like any step
with the run's settings; its outputs go to a temporary directory. Each input is probed once per run.
A broken or failing probe never fails the job: the value is `null`, the record gets `error`. Probing
counts towards the `hook` record; cwltool's overhead makes even a trivial probe take about a second.

## Tests
```sh
uv run pytest tests/resource_demand
```
No network needed: [`tests/resource_demand/vocabularies/`](../../tests/resource_demand/vocabularies/)
holds the rd release and `eo-formats.owl`, which the examples name in `$schemas`.

## Not yet covered
- `ResourceRequirement` of a workflow or step; only the tool's own is read.
- Domain measures (`eo:PixelCount`, ...) are not taken at run time: their value is `null`.
- A probe has no time limit, and its input's format is not checked.
- Big O shorthand (`rd:timeDemand: "O(n * d)"`); only the structured form.
- Output sizes as demands, to chain estimates along a workflow.
