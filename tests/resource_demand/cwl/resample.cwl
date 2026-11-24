#!/usr/bin/env cwl-runner
# Resample a raster by a scale factor. Output pixels = n * s^2, so both demands grow linearly with
# the input's pixel count and quadratically with the scale factor: O(n · s^2).
# Placeholder command; the annotation is what this example is about.
cwlVersion: v1.2
class: CommandLineTool
$schemas: [../vocabularies/eo-formats.owl]  # domain vocabulary: formats, eo: measures
$namespaces:
  eo: "https://dfg-sos.github.io/ontologies/eo-formats#"
  rd: "https://dfg-sos.github.io/ontologies/resource-demand#"
baseCommand: [cp]
hints:
  ResourceRequirement:
    ramMin: 1024
    rd:ramDemand:
      - {n: rd:Linear, s: rd:Quadratic}
    rd:timeDemand:
      - {n: rd:Linear, s: rd:Quadratic}
inputs:
  raster:
    type: File
    format: eo:GeoTIFF
    inputBinding: {position: 1}
    rd:complexityVariables:
      - {symbol: n, measure: eo:PixelCount}
  scale:
    type: float
    default: 2.0
    rd:complexityVariables:
      - {symbol: s, measure: rd:Value}
arguments: [{position: 2, valueFrom: resampled.tif}]
outputs:
  resampled:
    type: File
    format: eo:GeoTIFF
    outputBinding: {glob: resampled.tif}
