# SPDX-License-Identifier: GPL-3.0-only
"""Alternate ctypes/process on the same recorded RAW and cached preprocessed frames.

Detailed coordinates stay local; only summary and code hashes are publishable.
Preprocessing generation, camera IPC, UI/SQM and mount movement are excluded.
"""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
from PIL import Image
import tetra3

from PiFinder import mf_detect_process, star_detect, utils
from PiFinder.detector_profiles import configure_profile
from replay_star_preprocess_ab import _cascade


def summarize(rows):
    summary = {}
    for arm in ("raw", "preprocessed"):
        selected = [r for r in rows if r["arm"] == arm]
        summary[arm] = {}
        for mode in ("ctypes", "process"):
            part = [r for r in selected if r["mode"] == mode]
            summary[arm][mode] = {
                "attempts": len(part),
                "solved": sum(r["ra"] is not None for r in part),
                "backends": dict(Counter(r["backend"] for r in part)),
                "routes": dict(Counter(r["route"] for r in part)),
            }
            for key in ("detect_ms", "solve_ms", "total_ms", "rmse", "matches"):
                values = [r[key] for r in part if r[key] is not None]
                summary[arm][mode][key] = {
                    "p50": float(np.median(values)) if values else None,
                    "p95": float(np.percentile(values, 95)) if values else None,
                }
        pairs = {}
        for row in selected:
            pairs.setdefault(row["file"], {})[row["mode"]] = row
        common = [
            p for p in pairs.values() if all(r["ra"] is not None for r in p.values())
        ]
        summary[arm]["paired"] = {
            "identical_detections": sum(
                p["process"]["identical_detection"] for p in pairs.values()
            ),
            "both_solved": len(common),
            "regressions": sum(
                p["ctypes"]["ra"] is not None and p["process"]["ra"] is None
                for p in pairs.values()
            ),
            "gains": sum(
                p["ctypes"]["ra"] is None and p["process"]["ra"] is not None
                for p in pairs.values()
            ),
            "identical_solutions": sum(
                all(
                    p["ctypes"][k] == p["process"][k]
                    for k in ("ra", "dec", "roll", "rmse", "matches", "route")
                )
                for p in common
            ),
            "max_abs_rmse_delta_arcsec": max(
                (abs(p["ctypes"]["rmse"] - p["process"]["rmse"]) for p in common),
                default=None,
            ),
        }
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--wide", action="store_true")
    args = parser.parse_args()
    if args.output.exists() or args.frames < 1 or args.start < 0:
        parser.error("new output and positive frame count required")
    paths = sorted(args.cache.glob("*.npy"))[args.start : args.start + args.frames]
    if not paths:
        parser.error("no cached frames")
    configure_profile("mf4p")
    solvers = {
        mode: tetra3.Tetra3(str(utils.tetra3_dir / "data/default_database.npz"))
        for mode in ("ctypes", "process")
    }
    warm_path = utils.data_dir / "sep_warm_pixels.npy"
    warm = np.load(warm_path) if warm_path.exists() else None
    rows, cold = [], {}
    try:
        for index, path in enumerate(paths):
            meta = json.loads(path.with_suffix(".json").read_text())
            if meta["frame_count"] < 2:
                continue
            source = args.corpus / (path.stem + ".tiff")
            if hashlib.sha256(source.read_bytes()).hexdigest() != meta["source_sha256"]:
                raise ValueError("source/cache mismatch")
            raw = np.ascontiguousarray(
                np.rot90(np.asarray(Image.open(source), dtype=np.uint16), -1)
            )
            for arm, image in (("raw", raw), ("preprocessed", np.load(path))):
                modes = (
                    ["ctypes", "process"] if index % 2 == 0 else ["process", "ctypes"]
                )
                detections, pair_rows = {}, []
                for mode in modes:
                    os.environ["MF_DETECT_TRANSPORT"] = mode
                    kwargs = dict(
                        saturation_level=4095 if arm == "raw" else None,
                        warm_pixel_map=warm,
                        cloud_window_gate=args.wide and arm == "raw",
                    )
                    if mode not in cold:
                        start = time.perf_counter()
                        star_detect.detect_stars(image, **kwargs)
                        cold[mode] = (time.perf_counter() - start) * 1000
                    start = time.perf_counter()
                    detection = star_detect.detect_stars(image, **kwargs)
                    detect_ms = (time.perf_counter() - start) * 1000
                    if detection is None:
                        raise RuntimeError("no detection object")
                    detections[mode] = detection
                    solution, route, reason, solve_ms = _cascade(
                        solvers[mode],
                        np.empty((0, 2)),
                        detection.centroids,
                        image.shape,
                        "preprocessed_" if arm == "preprocessed" else "",
                        meta["geometry"],
                    )
                    pair_rows.append(
                        dict(
                            file=path.name,
                            arm=arm,
                            mode=mode,
                            backend=detection.backend,
                            candidates=len(detection.centroids),
                            detect_ms=detect_ms,
                            solve_ms=solve_ms,
                            total_ms=detect_ms + solve_ms,
                            route=route,
                            reason=reason,
                            ra=solution.get("RA"),
                            dec=solution.get("Dec"),
                            roll=solution.get("Roll"),
                            rmse=solution.get("RMSE"),
                            matches=solution.get("Matches"),
                            source_sha256=meta["source_sha256"],
                        )
                    )
                identical = all(
                    np.array_equal(
                        getattr(detections["ctypes"], key),
                        getattr(detections["process"], key),
                    )
                    for key in ("centroids", "fluxes")
                )
                for row in pair_rows:
                    row["identical_detection"] = identical
                rows.extend(pair_rows)
                if not identical:
                    raise AssertionError(
                        f"transport changed detection: {path.name}/{arm}"
                    )
            if index % 15 == 0:
                print(path.name, "completed", flush=True)
    finally:
        mf_detect_process.close_workers()
    if not rows:
        raise ValueError("no warmed frames")
    files = [
        Path(__file__),
        Path(star_detect.__file__).resolve(),
        Path(mf_detect_process.__file__).resolve(),
        star_detect.native_library_path(),
        mf_detect_process.native_server_path(),
    ]
    result = dict(
        source_hashes={
            str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
        },
        cold_detect_ms=cold,
        summary=summarize(rows),
        rows=rows,
    )
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result["summary"], indent=2), flush=True)


if __name__ == "__main__":
    main()
