# Fixture F (linter only): official online EDAM, no EO additions.
# FASTA -> sequence format: compatible; TIFF -> NetCDF: incompatible; Shapefile (EO id) -> unknown-format.
cwlVersion: v1.2
$namespaces: {edam: "http://edamontology.org/"}
$schemas: [http://edamontology.org/EDAM.owl]
class: Workflow
inputs:
  seq: {type: File, format: edam:format_1929}
  image: {type: File, format: edam:format_3591}
  roads: {type: File, format: edam:format_4119}
outputs: []
steps:
  align:
    run: {class: CommandLineTool, baseCommand: "true", inputs: {s: {type: File, format: edam:format_1919}}, outputs: []}
    in: {s: seq}
    out: []
  climate:
    run: {class: CommandLineTool, baseCommand: "true", inputs: {c: {type: File, format: edam:format_3650}}, outputs: []}
    in: {c: image}
    out: []
  gis:
    run: {class: CommandLineTool, baseCommand: "true", inputs: {g: {type: File, format: edam:format_4126}}, outputs: []}
    in: {g: roads}
    out: []
