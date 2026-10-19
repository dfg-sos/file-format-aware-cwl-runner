# Fixture C: output declares LineString geometry; with points.geojson it fails in full mode, roads.geojson passes.
cwlVersion: v1.2
$namespaces: {edam: "http://edamontology.org/", sos: "https://w3id.org/sos/cwl#"}
$schemas: [http://localhost:8080/edam_eo.owl]
class: CommandLineTool
baseCommand: cp
arguments: [$(inputs.src.path), out.geojson]
inputs: {src: File}
outputs:
  lines:
    type: File
    format: edam:format_4106
    sos:expectedCRS: "EPSG:4326"
    sos:expectedGeometryType: LineString
    outputBinding: {glob: out.geojson}
