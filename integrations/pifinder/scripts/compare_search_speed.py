"""Alternate legacy/optimized Tetra3 on identical MF centroids and cached images.

Each strategy owns its cache. Detection is timed once per image and shared, so
the reported total isolates changes in search. Preprocessing cost is excluded.
Detailed coordinates stay in the local output; only summary is publishable.
"""

import argparse
from collections import Counter
import hashlib
import inspect
import json
import os
from pathlib import Path
import time

import numpy as np
from PIL import Image
import tetra3

from PiFinder import star_detect, utils
from PiFinder.detector_profiles import configure_profile
from replay_star_preprocess_ab import _cascade


def summarize(rows):
    result = {}
    for arm in ("raw", "preprocessed"):
        result[arm] = {}
        for mode in ("legacy", "optimized"):
            part = [r for r in rows if r["arm"] == arm and r["mode"] == mode]
            data = {
                "attempts": len(part),
                "solved": sum(r["ra"] is not None for r in part),
                "sep_calls": sum(r["backend"] == "sep" for r in part),
                "routes": dict(Counter(r["route"] for r in part)),
            }
            for key in ("detect_ms", "solve_ms", "total_ms", "rmse", "matches"):
                values = [r[key] for r in part if r[key] is not None]
                data[key] = {
                    "p50": float(np.median(values)) if values else None,
                    "p95": float(np.percentile(values, 95)) if values else None,
                }
            result[arm][mode] = data
        pairs = {}
        for row in rows:
            if row["arm"] == arm:
                pairs.setdefault(row["file"], {})[row["mode"]] = row
        common = [
            pair
            for pair in pairs.values()
            if all(r["ra"] is not None for r in pair.values())
        ]
        result[arm]["paired"] = {
            "regressions": sum(
                p["legacy"]["ra"] is not None and p["optimized"]["ra"] is None
                for p in pairs.values()
            ),
            "gains": sum(
                p["legacy"]["ra"] is None and p["optimized"]["ra"] is not None
                for p in pairs.values()
            ),
            "both_solved": len(common),
            "max_abs_rmse_delta_arcsec": max(
                (abs(p["legacy"]["rmse"] - p["optimized"]["rmse"]) for p in common),
                default=None,
            ),
            "identical_solution_count": sum(
                all(
                    p["legacy"][k] == p["optimized"][k]
                    for k in ("ra", "dec", "rmse", "matches", "route")
                )
                for p in common
            ),
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--wide", action="store_true")
    args = parser.parse_args()
    if args.output.exists() or args.start < 0 or args.frames < 1:
        parser.error("new output, start >= 0, frames >= 1 required")
    paths = sorted(args.cache.glob("*.npy"))[args.start : args.start + args.frames]
    if not paths:
        parser.error("no cached frames")
    configure_profile("mf4p")
    solvers = {}
    previous = os.environ.get("TETRA3_SEARCH_OPTIMIZED")
    try:
        for mode, value in (("legacy", "0"), ("optimized", "1")):
            os.environ["TETRA3_SEARCH_OPTIMIZED"] = value
            solvers[mode] = tetra3.Tetra3(
                str(utils.tetra3_dir / "data/default_database.npz")
            )
            if solvers[mode]._search_optimized != (value == "1"):
                raise RuntimeError("Tetra3 search switch unavailable")
    finally:
        if previous is None:
            os.environ.pop("TETRA3_SEARCH_OPTIMIZED", None)
        else:
            os.environ["TETRA3_SEARCH_OPTIMIZED"] = previous
    warm_path = utils.data_dir / "sep_warm_pixels.npy"
    warm = np.load(warm_path) if warm_path.exists() else None
    rows = []
    for index, path in enumerate(paths):
        meta = json.loads(path.with_suffix(".json").read_text())
        if meta["frame_count"] < 2:
            continue
        source = args.corpus / (path.stem + ".tiff")
        if hashlib.sha256(source.read_bytes()).hexdigest() != meta["source_sha256"]:
            raise ValueError(f"source/cache mismatch: {source.name}")
        raw = np.ascontiguousarray(
            np.rot90(np.asarray(Image.open(source), dtype=np.uint16), -1)
        )
        arms = [("raw", raw), ("preprocessed", np.load(path))]
        if index % 2:
            arms.reverse()
        for arm, frame in arms:
            started = time.perf_counter()
            detection = star_detect.detect_stars(
                frame,
                sigma=4.0,
                saturation_level=4095 if arm == "raw" else None,
                warm_pixel_map=warm,
                cloud_window_gate=args.wide and arm == "raw",
            )
            detect_ms = (time.perf_counter() - started) * 1000
            points = detection.centroids if detection is not None else np.empty((0, 2))
            modes = ["legacy", "optimized"]
            if index % 2:
                modes.reverse()
            for mode in modes:
                solution, route, reason, solve_ms = _cascade(
                    solvers[mode],
                    np.empty((0, 2)),
                    points,
                    frame.shape,
                    "preprocessed_" if arm == "preprocessed" else "",
                    meta["geometry"],
                )
                rows.append(
                    {
                        "file": path.name,
                        "mode": mode,
                        "arm": arm,
                        "source_sha256": meta["source_sha256"],
                        "cache_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "backend": detection.backend
                        if detection is not None
                        else "none",
                        "candidates": len(points),
                        "detect_ms": detect_ms,
                        "solve_ms": solve_ms,
                        "total_ms": detect_ms + solve_ms,
                        "route": route,
                        "reason": reason,
                        "ra": solution.get("RA"),
                        "dec": solution.get("Dec"),
                        "rmse": solution.get("RMSE"),
                        "matches": solution.get("Matches"),
                    }
                )
        if index % 15 == 0:
            print(path.name, "completed", flush=True)
    if not rows:
        raise ValueError("No warmed frames to compare")
    sources = [
        Path(inspect.getfile(tetra3.Tetra3)),
        Path(inspect.getfile(star_detect)),
        star_detect.native_library_path(),
        Path(__file__),
    ]
    result = {
        "source_hashes": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources
        },
        "summary": summarize(rows),
        "rows": rows,
    }
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result["summary"], indent=2), flush=True)


if __name__ == "__main__":
    main()
