#!/usr/bin/env cwl-runner
# Turn a binary raster mask (e.g. a settlement footprint) into polygons. The scan is linear in the
# pixel count n; building polygons grows with the foreground pixels d, which file size does not show.
# Illustrative shapes, to be confirmed with micro-benchmarks. Placeholder command.
cwlVersion: v1.2
class: CommandLineTool
$schemas: [../vocabularies/eo-formats.owl]  # domain vocabulary: formats, eo: measures
$namespaces:
  eo: "https://dfg-sos.github.io/ontologies/eo-formats#"
  rd: "https://dfg-sos.github.io/ontologies/resource-demand#"
baseCommand: [echo, '{"type": "FeatureCollection", "features": []}']
stdout: polygons.geojson
hints:
  ResourceRequirement:
    rd:ramDemand:                          # O(n + d)
      - {n: rd:Linear}
      - {d: rd:Linear}
    rd:timeDemand:                         # O(n + d log d)
      - {n: rd:Linear}
      - {d: rd:Linearithmic}
inputs:
  mask:
    type: File
    format: eo:GeoTIFF
    rd:complexityVariables:
      - {symbol: n, measure: eo:PixelCount}
      - {symbol: d, measure: eo:ValidPixelCount}
outputs:
  polygons:
    type: File
    format: eo:GeoJSON
    outputBinding: {glob: polygons.geojson}
