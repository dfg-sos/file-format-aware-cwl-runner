cwlVersion: v1.2
class: Workflow
inputs:
  text: string
outputs:
  count: {type: File, outputSource: consume/count}
steps:
  produce:
    run: produce.cwl
    in: {text: text}
    out: [out]
  consume:
    run: consume.cwl
    in: {file: produce/out}
    out: [count]
