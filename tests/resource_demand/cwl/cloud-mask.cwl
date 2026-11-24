#!/usr/bin/env cwl-runner
# Mask clouds in a scene. Time depends on how cloudy the scene is, a derived measure computed by a
# probe (probes/cloud-fraction.cwl) before the step runs. Placeholder command.
cwlVersion: v1.2
class: CommandLineTool
$schemas: [../vocabularies/eo-formats.owl]  # domain vocabulary: formats, eo: measures
$namespaces:
  eo: "https://dfg-sos.github.io/ontologies/eo-formats#"
  rd: "https://dfg-sos.github.io/ontologies/resource-demand#"
baseCommand: [cp]
hints:
  ResourceRequirement:
    rd:ramDemand:                          # O(n)
      - {n: rd:Linear}
    rd:timeDemand:                         # O(n · c)
      - {n: rd:Linear, c: rd:Linear}
inputs:
  scene:
    type: File
    format: eo:GeoTIFF
    inputBinding: {position: 1}
    rd:complexityVariables:
      - {symbol: n, measure: eo:PixelCount}
      - {symbol: c, measure: rd:DerivedMeasure, probe: probes/cloud-fraction.cwl}
arguments: [{position: 2, valueFrom: masked.tif}]
outputs:
  masked:
    type: File
    format: eo:GeoTIFF
    outputBinding: {glob: masked.tif}
