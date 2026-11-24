cwlVersion: v1.2
class: CommandLineTool
baseCommand: [sh, -c, 'echo hi > plain.txt']
inputs: []
outputs:
  plain: {type: File, outputBinding: {glob: plain.txt}}
