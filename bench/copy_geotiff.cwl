cwlVersion: v1.2
$namespaces: {edam: "http://edamontology.org/", sos: "https://w3id.org/sos/cwl#"}
$schemas: [http://localhost:8080/edam_eo.owl]
class: CommandLineTool
baseCommand: cp
arguments: [$(inputs.src.path), out.tif]
inputs:
  src: {type: File, format: edam:format_4109}
outputs:
  out:
    type: File
    format: edam:format_4109
    sos:expectedCRS: "EPSG:4326"
    outputBinding: {glob: out.tif}
