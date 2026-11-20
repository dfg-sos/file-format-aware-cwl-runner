cwlVersion: v1.2
class: Workflow
inputs: {}
outputs:
  size: {type: File, outputSource: consume/size}
steps:
  produce: {run: produce.cwl, in: {}, out: [raster]}
  consume: {run: consume.cwl, in: {raster: produce/raster}, out: [size]}
