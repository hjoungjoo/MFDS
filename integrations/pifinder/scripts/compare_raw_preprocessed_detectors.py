"""Pair each RAW exposure with cached preprocessing under MF-first detection.

This isolates detector/solver quality. Cached preprocessing time is reported
separately; it is not a measurement of live auto-scheduling throughput.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image
import tetra3

from PiFinder import star_detect, utils
from PiFinder.detector_profiles import configure_profile
from replay_star_preprocess_ab import _cascade


def configure_mode(mode):
    configure_profile(mode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--wide", action="store_true")
    parser.add_argument("--modes", default="mf4p,mf2,sep")
    args = parser.parse_args()
    modes = args.modes.split(",")
    files = sorted(args.cache.glob("*.npy"))[args.start :]
    if args.limit:
        files = files[: args.limit]
    t3 = tetra3.Tetra3(str(utils.tetra3_dir / "data/default_database.npz"))
    warm_path = utils.data_dir / "sep_warm_pixels.npy"
    warm_map = np.load(warm_path) if warm_path.exists() else None
    rows = []
    for index, path in enumerate(files):
        meta = json.loads(path.with_suffix(".json").read_text())
        if meta["frame_count"] < 2:
            continue
        raw = np.ascontiguousarray(
            np.rot90(
                np.asarray(
                    Image.open(args.corpus / (path.stem + ".tiff")), dtype=np.uint16
                ),
                -1,
            )
        )
        pre = np.load(path)
        offset = index % len(modes)
        for mode in modes[offset:] + modes[:offset]:
            configure_mode(mode)
            arms = [("raw", raw), ("preprocessed", pre)]
            if index % 2:
                arms.reverse()
            for arm, frame in arms:
                started = time.perf_counter()
                detection = star_detect.detect_stars(
                    frame,
                    sigma=4.0,
                    saturation_level=4095 if arm == "raw" else None,
                    warm_pixel_map=warm_map,
                    cloud_window_gate=args.wide and arm == "raw",
                )
                detect_ms = (time.perf_counter() - started) * 1000
                points = (
                    detection.centroids if detection is not None else np.empty((0, 2))
                )
                solution, route, reason, solve_ms = _cascade(
                    t3,
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
                        "backend": detection.backend
                        if detection is not None
                        else "none",
                        "fallback_reason": detection.fallback_reason
                        if detection is not None
                        else "no_detection",
                        "primary_candidates": detection.primary_candidates
                        if detection is not None
                        else 0,
                        "candidates": len(points),
                        "detect_ms": detect_ms,
                        "solve_ms": solve_ms,
                        "detect_solve_ms": detect_ms + solve_ms,
                        "preprocess_ms_cached": meta["preprocess_ms"],
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
    summary = {}
    for mode in modes:
        summary[mode] = {}
        for arm in ["raw", "preprocessed"]:
            part = [r for r in rows if r["mode"] == mode and r["arm"] == arm]
            data = {
                "attempts": len(part),
                "solved": sum(r["ra"] is not None for r in part),
                "sep_calls": sum(r["backend"] == "sep" for r in part),
                "sep_fallback_calls": sum(
                    r["fallback_reason"] is not None for r in part
                ),
                "backends": dict(Counter(r["backend"] for r in part)),
            }
            for key in [
                "detect_ms",
                "solve_ms",
                "detect_solve_ms",
                "candidates",
                "rmse",
                "matches",
            ]:
                values = [r[key] for r in part if r[key] is not None]
                data[key] = {
                    "p50": float(np.median(values)) if values else None,
                    "p95": float(np.percentile(values, 95)) if values else None,
                }
            summary[mode][arm] = data
        by_file = {}
        for row in rows:
            if row["mode"] == mode:
                by_file.setdefault(row["file"], {})[row["arm"]] = row
        pairs = Counter()
        for part in by_file.values():
            a, b = part["raw"]["ra"] is not None, part["preprocessed"]["ra"] is not None
            pairs[
                "both"
                if a and b
                else "raw_only"
                if a
                else "preprocessed_only"
                if b
                else "neither"
            ] += 1
        summary[mode]["pairs"] = dict(pairs)
    args.output.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
