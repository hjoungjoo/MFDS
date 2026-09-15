"""Measure offline preprocessing + detection + solving on recorded RAW frames.

The operating camera/service remains active. This excludes exposure, IPC, SQM,
publication and mount settling; it is not a capture-to-GOTO latency measurement.
"""

import argparse
import json
import os
from pathlib import Path
import time

import numpy as np
from PIL import Image
import tetra3

from PiFinder import star_detect, utils
from PiFinder.mf_star_only_preprocess import MFStarOnlyAccumulator, MFStarOnlyConfig
from replay_star_preprocess_ab import _cascade


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--modes", default="sep,mf")
    args = parser.parse_args()
    paths = sorted(args.corpus.glob("raw_*.tiff"))[: args.frames]
    t3 = tetra3.Tetra3(str(utils.tetra3_dir / "data/default_database.npz"))
    accumulator = MFStarOnlyAccumulator(
        MFStarOnlyConfig(parallel_scale_workers=args.workers)
    )
    warm_path = utils.data_dir / "sep_warm_pixels.npy"
    warm_map = np.load(warm_path) if warm_path.exists() else None
    rows = []
    try:
        for index, path in enumerate(paths):
            meta = json.loads((args.cache / (path.stem + ".json")).read_text())
            frame = np.ascontiguousarray(
                np.rot90(np.asarray(Image.open(path), dtype=np.uint16), -1)
            )
            started = time.perf_counter()
            pre = accumulator.add(
                frame,
                saturation_level=4095,
                fingerprint=(frame.shape, meta["exposure_us"], meta["gain"]),
            )
            preprocess_ms = (time.perf_counter() - started) * 1000
            # Check parallel execution retains the serial replay's exact pixels.
            np.testing.assert_array_equal(
                pre.frame, np.load(args.cache / (path.stem + ".npy"))
            )
            if pre.diagnostics.frame_count < 2:
                continue
            modes = args.modes.split(",")
            offset = index % len(modes)
            for mode in modes[offset:] + modes[:offset]:
                os.environ["PIFINDER_DETECTOR"] = "sep" if mode == "sep" else "mf"
                os.environ["MF_DETECT_RANKING"] = "response"
                os.environ["MF_DETECT_REFINE"] = "0"
                os.environ["MF_DETECT_BINNING"] = (
                    mode[2] if len(mode) > 2 and mode.startswith("mf") else "2"
                )
                os.environ["MF_DETECT_PYRAMID"] = (
                    "2"
                    if "p" in mode and mode != "sep"
                    else "1"
                    if "o" in mode
                    else "0"
                )
                started = time.perf_counter()
                detected = star_detect.detect_stars(
                    pre.frame,
                    sigma=4.0,
                    saturation_level=None,
                    cloud_window_gate=False,
                    warm_pixel_map=warm_map,
                )
                detect_ms = (time.perf_counter() - started) * 1000
                solution, route, reason, solve_ms = _cascade(
                    t3,
                    np.empty((0, 2)),
                    detected.centroids,
                    frame.shape,
                    "preprocessed_",
                    meta["geometry"],
                )
                rows.append(
                    {
                        "file": path.name,
                        "mode": mode,
                        "preprocess_ms": preprocess_ms,
                        "detect_ms": detect_ms,
                        "solve_ms": solve_ms,
                        "total_ms": preprocess_ms + detect_ms + solve_ms,
                        "solved": solution.get("RA") is not None,
                        "route": route,
                        "reason": reason,
                    }
                )
            print(path.name, "completed", flush=True)
    finally:
        accumulator.close()
    summary = {"workers": args.workers, "serial_parallel_pixels_identical": True}
    for mode in args.modes.split(","):
        part = [row for row in rows if row["mode"] == mode]
        summary[mode] = {
            "attempts": len(part),
            "solved": sum(r["solved"] for r in part),
        }
        for key in ["preprocess_ms", "detect_ms", "solve_ms", "total_ms"]:
            values = [row[key] for row in part]
            summary[mode][key] = {
                "p50": float(np.median(values)),
                "p95": float(np.percentile(values, 95)),
                "max": float(np.max(values)),
            }
    args.output.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
