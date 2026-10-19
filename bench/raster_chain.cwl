# Benchmark workload: three steps passing a GeoTIFF along (each step copies its input).
cwlVersion: v1.2
$namespaces: {edam: "http://edamontology.org/", sos: "https://w3id.org/sos/cwl#"}
$schemas: [http://localhost:8080/edam_eo.owl]
class: Workflow
inputs:
  raster: {type: File, format: edam:format_4109}
outputs:
  result: {type: File, outputSource: s3/out}
steps:
  s1: {run: copy_geotiff.cwl, in: {src: raster}, out: [out]}
  s2: {run: copy_geotiff.cwl, in: {src: s1/out}, out: [out]}
  s3: {run: copy_geotiff.cwl, in: {src: s2/out}, out: [out]}
