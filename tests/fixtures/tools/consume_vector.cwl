cwlVersion: v1.2
$namespaces: {edam: "http://edamontology.org/", sos: "https://w3id.org/sos/cwl#"}
$schemas: [http://localhost:8080/edam_eo.owl]
class: CommandLineTool
baseCommand: [wc, -c]
stdout: size.txt
inputs:
  data:
    type: File
    format: edam:format_4126
    inputBinding: {position: 1}
outputs:
  size: stdout
