cwlVersion: v1.2
class: CommandLineTool
baseCommand: [sh, -c, 'echo "$0" > out.txt']
inputs:
  text: {type: string, inputBinding: {position: 1}}
outputs:
  out: {type: File, outputBinding: {glob: out.txt}}
