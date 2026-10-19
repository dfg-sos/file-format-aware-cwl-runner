# Fixture D: Shapefile workflow input into a geotiff step input (linter: incompatible).
cwlVersion: v1.2
$namespaces: {edam: "http://edamontology.org/", sos: "https://w3id.org/sos/cwl#"}
$schemas: [http://localhost:8080/edam_eo.owl]
class: Workflow
inputs:
  roads: {type: File, format: edam:format_4119, secondaryFiles: [^.shx, ^.dbf, ^.prj]}
outputs:
  size: {type: File, outputSource: consume/size}
steps:
  consume: {run: tools/consume_geotiff.cwl, in: {data: roads}, out: [size]}
