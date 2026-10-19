"""Write GeoTIFF benchmark inputs of roughly the given sizes in MB (EPSG:4326, uncompressed uint8).

../sos-file-format-service/.venv/bin/python bench/make_inputs.py 1 10 100
"""

import math
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

OUT = Path(__file__).parent / "inputs"

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    rng = np.random.default_rng(0)
    for mb in map(float, sys.argv[1:] or ["1", "10", "100"]):
        side = int(math.sqrt(mb * 1024 * 1024))
        path = OUT / f"raster_{mb:g}MB.tif"
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=side,
            height=side,
            count=1,
            dtype="uint8",
            crs="EPSG:4326",
            transform=from_origin(9.0, 50.0, 1e-4, 1e-4),
        ) as dst:
            dst.write(rng.integers(0, 255, (1, side, side), dtype="uint8"))
        job = OUT / f"raster_{mb:g}MB.yml"
        job.write_text(
            f'raster: {{class: File, location: {path.name}, format: "http://edamontology.org/format_4109"}}\n'
        )
        print(path, path.stat().st_size)
