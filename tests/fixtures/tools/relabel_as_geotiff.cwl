# Copies any file and declares the result GeoTIFF without looking at it (the label-stamping gap).
cwlVersion: v1.2
$namespaces: {edam: "http://edamontology.org/", sos: "https://w3id.org/sos/cwl#"}
$schemas: [http://localhost:8080/edam_eo.owl]
class: CommandLineTool
baseCommand: cp
arguments: [$(inputs.src.path), $(inputs.name)]
inputs:
  src: File
  name: string
outputs:
  raster: {type: File, format: edam:format_4109, outputBinding: {glob: $(inputs.name)}}
