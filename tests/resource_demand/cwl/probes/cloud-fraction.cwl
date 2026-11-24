#!/usr/bin/env cwl-runner
# Probe for the derived measure of cloud-mask.cwl: prints a single number (here a placeholder).
cwlVersion: v1.2
class: CommandLineTool
requirements: {InlineJavascriptRequirement: {}}
baseCommand: [echo, "0.25"]
stdout: value.txt
inputs:
  scene: File
outputs:
  value:
    type: float
    outputBinding:
      glob: value.txt
      loadContents: true
      outputEval: $(parseFloat(self[0].contents))
