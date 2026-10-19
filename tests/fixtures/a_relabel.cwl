# Fixture A: a GeoJSON file is labelled GeoTIFF and consumed as GeoTIFF.
# Vanilla cwltool succeeds. A1 (name out.geojson) fails in basic mode, A2 (out.tif) only in full mode.
cwlVersion: v1.2
$namespaces: {edam: "http://edamontology.org/", sos: "https://w3id.org/sos/cwl#"}
$schemas: [http://localhost:8080/edam_eo.owl]
class: Workflow
inputs:
  src: File
  name: string
outputs:
  size: {type: File, outputSource: consume/size}
steps:
  relabel: {run: tools/relabel_as_geotiff.cwl, in: {src: src, name: name}, out: [raster]}
  consume: {run: tools/consume_geotiff.cwl, in: {data: relabel/raster}, out: [size]}
