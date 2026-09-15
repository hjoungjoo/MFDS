# SPDX-License-Identifier: GPL-3.0-only
"""Compare full-first search on recorded MF2 sky-mask centroids.

Inputs are diagnose_moon_city output folders for 1920x1080 sensor images.
Only solver search is timed; this does not rerun detection or a live pipeline.
Individual output rows contain celestial coordinates and must remain local.
"""

import argparse
import json
from pathlib import Path
import numpy as np
import tetra3
from PiFinder import utils
from replay_star_preprocess_ab import _solve, _center_square
from PiFinder.solve_acceptance import SolveContinuityGate

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("replays", type=Path, nargs="+")
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
t3 = tetra3.Tetra3(str(utils.tetra3_dir / "data/default_database.npz"))
summary = {}
for p in args.replays:
    name = p.name
    geometry = json.loads((p / "geometry.json").read_text())
    exp = json.loads((p / "experiment.json").read_text())
    corpus = Path(exp["corpus"])
    times = {
        r["file"]: r["wall_timestamp"]
        for r in map(json.loads, (corpus / "manifest.jsonl").read_text().splitlines())
    }
    rows = [
        r
        for r in map(json.loads, (p / "rows.jsonl").read_text().splitlines())
        if r["source"] == "raw" and r["mode"] == "mf2_mask"
    ]
    out = []
    gate = SolveContinuityGate()
    for row in rows:
        pts = np.asarray(row["points"])
        center = _center_square(pts, (1080, 1920))
        stages = []
        if len(pts) >= 5:
            stages.append(("sep_full", pts))
        if 5 <= len(center) < len(pts):
            stages.append(("sep_center", center))
        elapsed = 0
        sol = {}
        reason = "insufficient_centroids"
        path = ""
        calls = []
        with tetra3.search_budget(2600):
            for route, points in stages:
                sol, reason, ms = _solve(t3, points, (1080, 1920), route, **geometry)
                elapsed += ms
                calls.append(route)
                if sol:
                    path = route
                    break
        accepted = (
            gate.evaluate(sol, path, times[row["file"]], stationary=True).accepted
            if sol
            else False
        )
        out.append(
            {
                "file": row["file"],
                "original_solved": row["solved"],
                "original_solve_ms": row["solve_ms"],
                "solved": bool(sol),
                "continuity": accepted,
                "solve_ms": elapsed,
                "path": path,
                "calls": calls,
                "rmse": sol.get("RMSE"),
                "matches": sol.get("Matches"),
                "ra": sol.get("RA"),
                "dec": sol.get("Dec"),
            }
        )
    (args.output / (name + "_rows.json")).write_text(json.dumps(out, indent=2))
    d = {
        "n": len(out),
        "original_solved": sum(r["original_solved"] for r in out),
        "solved": sum(r["solved"] for r in out),
        "continuity": sum(r["continuity"] for r in out),
        "lost_original_success": sum(
            r["original_solved"] and not r["solved"] for r in out
        ),
        "new_success": sum(r["solved"] and not r["original_solved"] for r in out),
    }
    for key in ["original_solve_ms", "solve_ms", "rmse", "matches"]:
        v = [r[key] for r in out if r[key] is not None]
        d[key] = (
            {"p50": float(np.median(v)), "p95": float(np.percentile(v, 95))}
            if v
            else None
        )
    summary[name] = d
    print(name, json.dumps(d), flush=True)
(args.output / "summary.json").write_text(json.dumps(summary, indent=2))
