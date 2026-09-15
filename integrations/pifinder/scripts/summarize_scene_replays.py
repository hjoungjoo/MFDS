# SPDX-License-Identifier: GPL-3.0-only
"""Summarize offline scene replays, including the existing continuity gate.

Input folders must contain diagnose_moon_city outputs and accessible local corpora.
The sidereal-adjusted scatter is a fixed-pointing approximation, not absolute
accuracy. No raw coordinates or individual images are copied to this summary.
"""

import argparse
import json
from pathlib import Path
from collections import Counter
import numpy as np
from PiFinder.solve_acceptance import SolveContinuityGate, angular_separation_deg

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("root", type=Path)
args = parser.parse_args()
root = args.root
summary = {}


def stat(v):
    return (
        {"p50": float(np.median(v)), "p95": float(np.percentile(v, 95))}
        if v
        else {"p50": None, "p95": None}
    )


for out in sorted(
    p for p in root.iterdir() if p.is_dir() and (p / "summary.json").exists()
):
    exp = json.loads((out / "experiment.json").read_text())
    corpus = Path(exp["corpus"])
    frames = {f["file"]: f for f in json.loads((out / "frames.json").read_text())}
    times = {
        r["file"]: r["wall_timestamp"]
        for r in map(json.loads, (corpus / "manifest.jsonl").read_text().splitlines())
    }
    rows = list(map(json.loads, (out / "rows.jsonl").read_text().splitlines()))
    res = {}
    for source, mode in sorted(set((r["source"], r["mode"]) for r in rows)):
        group = [r for r in rows if (r["source"], r["mode"]) == (source, mode)]
        gate = SolveContinuityGate()
        accepted = []
        reasons = []
        for r in group:
            if r["solved"]:
                d = gate.evaluate(
                    {"RA": r["ra"], "Dec": r["dec"]},
                    r["path"],
                    times[r["file"]],
                    stationary=True,
                    prefer_preprocessed=source == "pre",
                )
                reasons.append(d.reason)
                if d.accepted:
                    accepted.append(r)
        solved = [r for r in group if r["solved"]]
        mature = [
            r
            for r in group
            if source == "raw"
            or frames[r["file"]]["diagnostics"]["frame_count"] >= exp["temporal"]
        ]
        total = [
            r["detect_ms"]
            + r["solve_ms"]
            + (frames[r["file"]]["preprocess_ms"] if source == "pre" else 0)
            for r in group
        ]
        result = {
            "attempts": len(group),
            "quality_pass": len(solved),
            "continuity_pass": len(accepted),
            "mature_attempts": len(mature),
            "mature_quality_pass": sum(r["solved"] for r in mature),
            "last10_quality_pass": sum(r["solved"] for r in group[-10:]),
            "continuity_reasons": dict(Counter(reasons)),
            "failure_reasons": dict(Counter(r["reason"] for r in group)),
            "fallback_calls": sum(r["fallback_calls"] for r in group),
            "candidates": stat([r["candidates"] for r in group]),
            "city_candidates": stat([r["city_candidates"] for r in group]),
            "rmse_arcsec": stat([r["rmse"] for r in solved]),
            "matches": stat([r["matches"] for r in solved]),
            "detect_ms": stat([r["detect_ms"] for r in group]),
            "solve_ms": stat([r["solve_ms"] for r in group]),
            "serial_processing_ms": stat(total),
            "preprocess_ms": stat([frames[r["file"]]["preprocess_ms"] for r in group])
            if source == "pre"
            else None,
        }
        if len(solved) > 1:
            # Apparent stationary-direction consistency, not an absolute accuracy metric.
            t0 = times[solved[0]["file"]]
            pts = [
                ((r["ra"] - (times[r["file"]] - t0) * 360 / 86164.0905) % 360, r["dec"])
                for r in solved
            ]
            dist = np.array(
                [[angular_separation_deg(*a, *b) * 3600 for b in pts] for a in pts]
            )
            ref = int(np.argmin(dist.sum(axis=0)))
            result["sidereal_corrected_center_separation_arcsec"] = stat(
                dist[ref].tolist()
            )
        res[source + "_" + mode] = result
    summary[out.name] = {
        "temporal": exp["temporal"],
        "frames_replayed": exp["frames"],
        "results": res,
    }
(root / "aggregate.json").write_text(json.dumps(summary, indent=2))
for name, part in summary.items():
    print(
        name,
        {
            k: f"{v['quality_pass']}/{v['attempts']} (continuity {v['continuity_pass']})"
            for k, v in part["results"].items()
        },
    )
