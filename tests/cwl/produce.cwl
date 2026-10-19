cwlVersion: v1.2
class: CommandLineTool
$namespaces: {edam: "http://edamontology.org/", sos: "https://w3id.org/sos/cwl#"}
baseCommand: [sh, -c, 'echo "{\"type\": \"FeatureCollection\", \"features\": []}" > out.tif']
inputs: []
outputs:
  raster:
    type: File
    format: edam:format_4109   # GeoTIFF label, but content is GeoJSON
    sos:expectedCRS: "EPSG:4326"
    outputBinding: {glob: out.tif}
