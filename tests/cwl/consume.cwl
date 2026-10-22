cwlVersion: v1.2
class: CommandLineTool
$namespaces: {eo: "https://dfg-sos.github.io/ontologies/eo-formats#"}
baseCommand: [wc, -c]
stdout: size.txt
inputs:
  raster: {type: File, format: eo:GeoTIFF, inputBinding: {position: 1}}
outputs:
  size: {type: stdout}
