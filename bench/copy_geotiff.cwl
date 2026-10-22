cwlVersion: v1.2
$namespaces: {eo: "https://dfg-sos.github.io/ontologies/eo-formats#", sos: "https://dfg-sos.github.io/ontologies/cwl#"}
$schemas: [https://dfg-sos.github.io/ontologies/eo-formats.owl]
class: CommandLineTool
baseCommand: cp
arguments: [$(inputs.src.path), out.tif]
inputs:
  src: {type: File, format: eo:GeoTIFF}
outputs:
  out:
    type: File
    format: eo:GeoTIFF
    sos:expectedCRS: "EPSG:4326"
    outputBinding: {glob: out.tif}
