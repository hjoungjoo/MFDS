"""Compare detectors on identical saved preprocessed frames and solver geometry."""

import argparse
import json
import os
from pathlib import Path
import time

import numpy as np
import tetra3

from PiFinder import star_detect, utils
from replay_star_preprocess_ab import _cascade


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--modes", default="sep,mf2,mf1")
    parser.add_argument("--alternate", action="store_true")
    args = parser.parse_args()
    # This historical benchmark compares pure detector variants. The MF-first
    # RAW/preprocessed policy is measured by compare_raw_preprocessed_detectors.
    os.environ["MF_DETECT_SEP_FALLBACK"] = "0"
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
        frame = np.load(path)
        modes = args.modes.split(",")
        if args.alternate:
            offset = index % len(modes)
            modes = modes[offset:] + modes[:offset]
        for mode in modes:
            os.environ["PIFINDER_DETECTOR"] = "sep" if mode == "sep" else "mf"
            if mode != "sep":
                os.environ["MF_DETECT_PYRAMID"] = (
                    "2" if "p" in mode else "1" if "o" in mode else "0"
                )
                os.environ["MF_DETECT_BINNING"] = mode[2]
                os.environ["MF_DETECT_RANKING"] = (
                    "response" if mode.endswith("q") else "flux"
                )
                os.environ["MF_DETECT_REFINE"] = "1" if mode.endswith("r") else "0"
                os.environ["MF_DETECT_MAX_STARS"] = (
                    mode.split("n")[1] if "n" in mode else "48"
                )
            started = time.perf_counter()
            detection = star_detect.detect_stars(
                frame,
                sigma=4.0,
                saturation_level=None,
                cloud_window_gate=False,
                warm_pixel_map=warm_map,
            )
            detect_ms = (time.perf_counter() - started) * 1000
            solution, route, reason, solve_ms = _cascade(
                t3,
                np.empty((0, 2)),
                detection.centroids,
                frame.shape,
                "preprocessed_",
                meta["geometry"],
            )
            rows.append(
                {
                    "file": path.name,
                    "mode": mode,
                    "route": route,
                    "reason": reason,
                    "candidates": len(detection.centroids),
                    "detect_ms": detect_ms,
                    "solve_ms": solve_ms,
                    "detect_solve_ms": detect_ms + solve_ms,
                    "preprocess_ms": meta["preprocess_ms"],
                    "ra": solution.get("RA"),
                    "dec": solution.get("Dec"),
                    "matches": solution.get("Matches"),
                    "rmse": solution.get("RMSE"),
                    "centroids": detection.centroids.tolist(),
                    "matched_centroids": np.asarray(
                        solution.get("matched_centroids", [])
                    ).tolist(),
                }
            )
        if len(rows) % 30 == 0:
            print(path.name, "completed", flush=True)
    summary = {}
    for mode in args.modes.split(","):
        part = [r for r in rows if r["mode"] == mode]
        solved = [r for r in part if r["ra"] is not None]
        summary[mode] = {"attempts": len(part), "solved": len(solved)}
        for key in [
            "detect_ms",
            "solve_ms",
            "detect_solve_ms",
            "candidates",
            "rmse",
            "matches",
        ]:
            values = [r[key] for r in part if r[key] is not None]
            summary[mode][key] = {
                "p50": float(np.median(values)) if values else None,
                "p95": float(np.percentile(values, 95)) if values else None,
            }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {"cache": str(args.cache), "summary": summary, "rows": rows}, indent=2
        )
    )
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
