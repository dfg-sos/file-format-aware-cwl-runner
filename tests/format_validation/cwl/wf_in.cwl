cwlVersion: v1.2
class: Workflow
inputs:
  raster: {type: File, format: "https://dfg-sos.github.io/ontologies/eo-formats#GeoTIFF"}
outputs:
  size: {type: File, outputSource: consume/size}
steps:
  consume: {run: consume.cwl, in: {raster: raster}, out: [size]}
