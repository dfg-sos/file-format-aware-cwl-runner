#!/usr/bin/env cwl-runner
# Count the features of vector files. Time grows with the features of all files; memory is constant
# (an empty term). Placeholder command.
cwlVersion: v1.2
class: CommandLineTool
$schemas: [../vocabularies/eo-formats.owl]  # domain vocabulary: formats, eo: measures
$namespaces:
  eo: "https://dfg-sos.github.io/ontologies/eo-formats#"
  rd: "https://dfg-sos.github.io/ontologies/resource-demand#"
baseCommand: [wc, -c]
stdout: count.txt
hints:
  ResourceRequirement:
    rd:ramDemand:                          # O(1)
      - {}
    rd:timeDemand:                         # O(f)
      - {f: rd:Linear}
inputs:
  layers:
    type: File[]
    format: eo:Vector
    inputBinding: {position: 1}
    rd:complexityVariables:
      - {symbol: f, measure: eo:FeatureCount}
outputs:
  count: {type: stdout}
