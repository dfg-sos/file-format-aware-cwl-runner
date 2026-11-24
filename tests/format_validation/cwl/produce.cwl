cwlVersion: v1.2
class: CommandLineTool
$namespaces: {eo: "https://dfg-sos.github.io/ontologies/eo-formats#", sos: "https://dfg-sos.github.io/ontologies/cwl#"}
baseCommand: [sh, -c, 'echo "{\"type\": \"FeatureCollection\", \"features\": []}" > out.tif']
inputs: []
outputs:
  raster:
    type: File
    format: eo:GeoTIFF   # GeoTIFF label, but content is GeoJSON
    sos:expectedCRS: "EPSG:4326"
    outputBinding: {glob: out.tif}
