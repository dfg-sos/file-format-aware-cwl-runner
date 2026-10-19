"""Reproduce the validation-overhead benchmark with one command.

    uv run python bench/run.py bench/raster_chain.cwl bench/inputs/raster_10MB.yml --repeat 10

Every repetition is a fresh `cwltool-sos` process per mode (off = baseline, no service calls).
Validation uses `warn` so an invalid file never shortens a run. Writes to the output dir:
  timing.jsonl  every run/check/main record (see README)
  runs.csv      one row per run: wall time, exit code, summed check and main-command time
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("workflow")
    p.add_argument("job", nargs="?")
    p.add_argument("--repeat", type=int, default=5)
    p.add_argument("--modes", default="off,basic,structural,full")
    p.add_argument("--out", default="bench/results")
    p.add_argument("--service-url", default="http://localhost:8000")
    p.add_argument("--no-container", action="store_true", help="passed through to cwltool")
    p.add_argument("--warmup", type=int, default=1, help="unrecorded runs before measuring")
    args = p.parse_args()

    out = Path(args.out) / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    log = out / "timing.jsonl"
    modes = args.modes.split(",")
    rows = []
    for rep in range(-args.warmup, args.repeat):
        for mode in modes:  # interleave modes so drift affects all equally
            run_id = f"{mode}-{rep}"
            cmd = [
                sys.executable,
                "-m",
                "format_aware_cwl.cli",
                "--quiet",
                "--format-service-url",
                args.service_url,
                "--format-run-id",
                run_id,
            ]
            if mode == "off":
                cmd += ["--format-validation", "off"]
            else:
                cmd += ["--format-validation", "warn", "--format-validation-mode", mode]
            if rep >= 0:
                cmd += ["--format-timing-log", str(log)]
            if args.no_container:
                cmd.append("--no-container")
            with tempfile.TemporaryDirectory() as tmp:
                cmd += ["--outdir", tmp, args.workflow, *([args.job] if args.job else [])]
                t0 = time.perf_counter()
                rc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
                wall_ms = (time.perf_counter() - t0) * 1000
            if rep >= 0:
                rows.append({"run_id": run_id, "mode": mode, "rep": rep, "wall_ms": round(wall_ms, 3), "exit": rc})
            print(f"{run_id:16} exit={rc} {wall_ms:9.1f} ms", file=sys.stderr)

    sums: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    if log.exists():
        for line in log.read_text().splitlines():
            r = json.loads(line)
            if r["record"] == "check":
                sums[r["run_id"]]["check_ms"] += r["duration_ms"]
                sums[r["run_id"]]["checks"] += 1
            elif r["record"] == "main":
                sums[r["run_id"]]["main_ms"] += r["main_duration_ms"]
    with open(out / "runs.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["run_id", "mode", "rep", "wall_ms", "exit", "checks", "check_ms", "main_ms"])
        w.writeheader()
        for row in rows:
            s = sums[row["run_id"]]
            w.writerow(
                {
                    **row,
                    "checks": int(s["checks"]),
                    "check_ms": round(s["check_ms"], 3),
                    "main_ms": round(s["main_ms"], 3),
                }
            )
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
