cwlVersion: v1.2
class: CommandLineTool
baseCommand: [wc, -c]
stdout: count.txt
inputs:
  file: {type: File, inputBinding: {position: 1}}
outputs:
  count: {type: stdout}
