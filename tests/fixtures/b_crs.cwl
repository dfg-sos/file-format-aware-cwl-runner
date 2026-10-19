# Fixture B: output declares expected CRS EPSG:3857; the raster is EPSG:4326 -> fails in full mode only.
cwlVersion: v1.2
$namespaces: {edam: "http://edamontology.org/", sos: "https://w3id.org/sos/cwl#"}
$schemas: [http://localhost:8080/edam_eo.owl]
class: CommandLineTool
baseCommand: cp
arguments: [$(inputs.src.path), out.tif]
inputs: {src: File}
outputs:
  raster:
    type: File
    format: edam:format_4109
    sos:expectedCRS: "EPSG:3857"
    outputBinding: {glob: out.tif}
