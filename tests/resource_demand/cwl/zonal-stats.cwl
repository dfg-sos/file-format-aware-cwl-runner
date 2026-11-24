#!/usr/bin/env cwl-runner
# Statistics of a raster per zone (polygon). The zones are rasterized once onto the raster's grid,
# then every band is scanned: time O(b · n + v); memory holds the zone grid, one band and the
# polygons: O(n + v). Illustrative shapes. Placeholder command.
cwlVersion: v1.2
class: CommandLineTool
$schemas: [../vocabularies/eo-formats.owl]  # domain vocabulary: formats, eo: measures
$namespaces:
  eo: "https://dfg-sos.github.io/ontologies/eo-formats#"
  rd: "https://dfg-sos.github.io/ontologies/resource-demand#"
baseCommand: [echo, '{}']
stdout: stats.json
hints:
  ResourceRequirement:
    rd:ramDemand:                          # O(n + v)
      - {n: rd:Linear}
      - {v: rd:Linear}
    rd:timeDemand:                         # O(b · n + v)
      - {b: rd:Linear, n: rd:Linear}
      - {v: rd:Linear}
inputs:
  raster:
    type: File
    format: eo:GeoTIFF
    rd:complexityVariables:
      - {symbol: n, measure: eo:PixelCount}
      - {symbol: b, measure: eo:BandCount}
  zones:
    type: File
    format: eo:GeoJSON
    rd:complexityVariables:
      - {symbol: v, measure: eo:VertexCount}
outputs:
  stats: {type: stdout}
