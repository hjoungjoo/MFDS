"""Summarize detector coordinates using recorded elapsed times, without a sky truth claim."""

import argparse
import json
from pathlib import Path
import numpy as np

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("comparison", type=Path)
parser.add_argument("manifest", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--pair", default="sep,mf2q")
args = parser.parse_args()
report = json.loads(args.comparison.read_text())
manifest = [json.loads(line) for line in args.manifest.read_text().splitlines()]
times = {Path(r["file"]).stem: r["elapsed_s"] for r in manifest}
summary = report["summary"]
for mode in summary:
    rows = [r for r in report["rows"] if r["mode"] == mode and r["ra"] is not None]
    if len(rows) < 3:
        summary[mode]["linear_detrended_radial_arcsec"] = None
        continue
    t = np.array([times[Path(r["file"]).stem] for r in rows])
    ra = np.unwrap(np.deg2rad([r["ra"] for r in rows]))
    dec = np.deg2rad([r["dec"] for r in rows])
    points = np.column_stack([ra * np.cos(np.median(dec)), dec]) * 180 / np.pi * 3600
    design = np.column_stack([np.ones(len(t)), t - t.mean()])
    residual = points - design @ np.linalg.lstsq(design, points, rcond=None)[0]
    radial = np.linalg.norm(residual, axis=1)
    summary[mode]["linear_detrended_radial_arcsec"] = {
        k: float(v)
        for k, v in zip(
            ["p50", "p95", "max"],
            [np.median(radial), np.percentile(radial, 95), np.max(radial)],
        )
    }
byfile = {}
for r in report["rows"]:
    if r["ra"] is not None:
        byfile.setdefault(r["file"], {})[r["mode"]] = r
seps = []
left, right = args.pair.split(",")
for part in byfile.values():
    if left not in part or right not in part:
        continue
    a, b = part[left], part[right]
    ra1, ra2 = np.deg2rad([a["ra"], b["ra"]])
    d1, d2 = np.deg2rad([a["dec"], b["dec"]])
    hav = (
        np.sin((d1 - d2) / 2) ** 2
        + np.cos(d1) * np.cos(d2) * np.sin((ra1 - ra2) / 2) ** 2
    )
    seps.append(float(np.rad2deg(2 * np.arcsin(np.sqrt(np.clip(hav, 0, 1)))) * 3600))
summary["paired_agreement_arcsec"] = {
    "frames": len(seps),
    "p50": float(np.median(seps)) if seps else None,
    "p95": float(np.percentile(seps, 95)) if seps else None,
    "max": max(seps) if seps else None,
}
print(json.dumps(summary, indent=2))
args.output.write_text(json.dumps(summary, indent=2) + "\n")
