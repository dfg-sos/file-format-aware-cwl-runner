cwlVersion: v1.2
class: Workflow
inputs:
  raster: {type: File, format: "http://edamontology.org/format_4109"}
outputs:
  size: {type: File, outputSource: consume/size}
steps:
  consume: {run: consume.cwl, in: {raster: raster}, out: [size]}
