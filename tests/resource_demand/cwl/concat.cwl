#!/usr/bin/env cwl-runner
# Concatenate files, k times. Uses only direct measures, which the runner takes from the CWL values:
# b bytes in total (rd:FileSize), m files (rd:ArrayLength), k repetitions (rd:Value).
cwlVersion: v1.2
class: CommandLineTool
$namespaces:
  rd: "https://dfg-sos.github.io/ontologies/resource-demand#"
baseCommand: [sh, -c, 'k=$0; shift; for i in $(seq $k); do cat "$@"; done > out.txt']
hints:
  ResourceRequirement:
    rd:ramDemand:                          # O(m)
      - {m: rd:Linear}
    rd:timeDemand:                         # O(k · b)
      - {k: rd:Linear, b: rd:Linear}
inputs:
  times:
    type: int
    inputBinding: {position: 1}
    rd:complexityVariables:
      - {symbol: k, measure: rd:Value}
  files:
    type: File[]
    inputBinding: {position: 2}
    rd:complexityVariables:
      - {symbol: b, measure: rd:FileSize}
      - {symbol: m, measure: rd:ArrayLength}
outputs:
  out: {type: File, outputBinding: {glob: out.txt}}
