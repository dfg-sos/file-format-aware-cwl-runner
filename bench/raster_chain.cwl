# Benchmark workload: three steps passing a GeoTIFF along (each step copies its input).
cwlVersion: v1.2
$namespaces: {eo: "https://dfg-sos.github.io/ontologies/eo-formats#", sos: "https://dfg-sos.github.io/ontologies/cwl#"}
$schemas: [https://dfg-sos.github.io/ontologies/eo-formats.owl]
class: Workflow
inputs:
  raster: {type: File, format: eo:GeoTIFF}
outputs:
  result: {type: File, outputSource: s3/out}
steps:
  s1: {run: copy_geotiff.cwl, in: {src: raster}, out: [out]}
  s2: {run: copy_geotiff.cwl, in: {src: s1/out}, out: [out]}
  s3: {run: copy_geotiff.cwl, in: {src: s2/out}, out: [out]}
