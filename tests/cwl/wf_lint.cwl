cwlVersion: v1.2
class: Workflow
$namespaces: {eo: "https://dfg-sos.github.io/ontologies/eo-formats#"}
$schemas: [http://ontology.test/eo-formats.owl]
inputs:
  roads: {type: File, format: eo:Shapefile}
outputs:
  out: {type: File, outputSource: inner/size}
steps:
  consume:
    run: consume.cwl
    in: {raster: roads}
    out: [size]
  inner:
    run:
      class: Workflow
      inputs: {r: {type: File, format: [eo:GeoTIFF, eo:COG]}}
      outputs: {size: {type: File, outputSource: c2/size}}
      steps:
        c2: {run: consume.cwl, in: {raster: r}, out: [size]}
    in: {r: roads}
    out: [size]
