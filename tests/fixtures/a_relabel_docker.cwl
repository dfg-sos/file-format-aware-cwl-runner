# Fixture A in containers: every step runs in alpine (DockerRequirement hint), so the checks
# go through DockerCommandLineJob (staged container paths, host paths via the pathmapper).
cwlVersion: v1.2
$namespaces: {edam: "http://edamontology.org/", sos: "https://w3id.org/sos/cwl#"}
$schemas: [http://localhost:8080/edam_eo.owl]
class: Workflow
hints:
  DockerRequirement: {dockerPull: "alpine:3.20"}
inputs:
  src: File
  name: string
outputs:
  size: {type: File, outputSource: consume/size}
steps:
  relabel: {run: tools/relabel_as_geotiff.cwl, in: {src: src, name: name}, out: [raster]}
  consume: {run: tools/consume_geotiff.cwl, in: {data: relabel/raster}, out: [size]}
