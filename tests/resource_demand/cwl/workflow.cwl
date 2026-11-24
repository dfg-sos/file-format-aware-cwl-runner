#!/usr/bin/env cwl-runner
# Resample a mask, then polygonize it: annotations are read per step.
cwlVersion: v1.2
class: Workflow
$schemas: [../vocabularies/eo-formats.owl]  # domain vocabulary: formats, eo: measures
$namespaces:
  eo: "https://dfg-sos.github.io/ontologies/eo-formats#"
inputs:
  mask: {type: File, format: eo:GeoTIFF}
outputs:
  polygons: {type: File, outputSource: polygonize/polygons}
steps:
  resample:
    run: resample.cwl
    in: {raster: mask}
    out: [resampled]
  polygonize:
    run: polygonize.cwl
    in: {mask: resample/resampled}
    out: [polygons]
