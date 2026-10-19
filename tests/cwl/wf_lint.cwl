cwlVersion: v1.2
class: Workflow
$namespaces: {edam: "http://edamontology.org/"}
$schemas: [http://ontology.test/edam.owl]
inputs:
  roads: {type: File, format: edam:format_4119}
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
      inputs: {r: {type: File, format: [edam:format_4109, edam:format_4100]}}
      outputs: {size: {type: File, outputSource: c2/size}}
      steps:
        c2: {run: consume.cwl, in: {raster: r}, out: [size]}
    in: {r: roads}
    out: [size]
