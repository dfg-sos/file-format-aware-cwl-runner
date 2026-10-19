cwlVersion: v1.2
class: CommandLineTool
$namespaces: {edam: "http://edamontology.org/"}
baseCommand: [wc, -c]
stdout: size.txt
inputs:
  raster: {type: File, format: edam:format_4109, inputBinding: {position: 1}}
outputs:
  size: {type: stdout}
