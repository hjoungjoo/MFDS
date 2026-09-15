"""Experimental nonblocking RAW + independently solved preprocessed anchors.

No service publication: camera-centre coordinates and diagnostics stay local.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import threading
import time

import numpy as np
from PIL import Image
import tetra3

from PiFinder import star_detect, utils
from PiFinder.latest_frame_worker import LatestFrameWorker
from PiFinder.mf_star_only_preprocess import MFStarOnlyAccumulator, MFStarOnlyConfig
from PiFinder.preprocessed_anchor import PreprocessedAnchor, SkySample
from compare_raw_preprocessed_detectors import configure_mode
from replay_star_preprocess_ab import _cascade


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--frames", type=int, default=36)
    parser.add_argument("--interval", type=float, default=0.4)
    args = parser.parse_args()
    configure_mode("mf4p")
    frames = []
    for p in sorted(args.cache.glob("*.npy"))[: args.frames]:
        meta = json.loads(p.with_suffix(".json").read_text())
        raw = np.ascontiguousarray(
            np.rot90(
                np.asarray(
                    Image.open(args.corpus / (p.stem + ".tiff")), dtype=np.uint16
                ),
                -1,
            )
        )
        frames.append((p.name, raw, meta))
    raw_solver = tetra3.Tetra3(str(utils.tetra3_dir / "data/default_database.npz"))
    accumulator = MFStarOnlyAccumulator(MFStarOnlyConfig(parallel_scale_workers=3))
    warm_path = utils.data_dir / "sep_warm_pixels.npy"
    warm = np.load(warm_path) if warm_path.exists() else None
    worker_state = {"generation": None, "epochs": [], "solver": None}
    main_thread = threading.get_ident()

    def background(job):
        assert threading.get_ident() != main_thread
        if worker_state["solver"] is None:
            worker_state["solver"] = tetra3.Tetra3(
                str(utils.tetra3_dir / "data/default_database.npz")
            )
        if job["generation"] != worker_state["generation"]:
            worker_state["epochs"] = []
            worker_state["generation"] = job["generation"]
        worker_state["epochs"].append(job["epoch"])
        worker_state["epochs"] = worker_state["epochs"][-5:]
        started = time.perf_counter()
        pre = accumulator.add(
            job["frame"],
            saturation_level=4095,
            fingerprint=(
                job["generation"],
                job["meta"]["exposure_us"],
                job["meta"]["gain"],
            ),
        )
        pre_ms = (time.perf_counter() - started) * 1000
        if pre.diagnostics.frame_count < 2:
            return {"sample": None, "preprocess_ms": pre_ms}
        started = time.perf_counter()
        detected = star_detect.detect_stars(
            pre.frame,
            sigma=4.0,
            saturation_level=None,
            warm_pixel_map=warm,
            cloud_window_gate=False,
        )
        detect_ms = (time.perf_counter() - started) * 1000
        solution, route, _, solve_ms = _cascade(
            worker_state["solver"],
            np.empty((0, 2)),
            detected.centroids,
            pre.frame.shape,
            "preprocessed_",
            job["meta"]["geometry"],
        )
        sample = (
            SkySample(job["index"], job["epoch"], solution["RA"], solution["Dec"])
            if solution.get("RA") is not None
            else None
        )
        return {
            "sample": sample,
            "preprocess_ms": pre_ms,
            "detect_ms": detect_ms,
            "solve_ms": solve_ms,
            "window_start_s": worker_state["epochs"][0],
            "route": route,
            "rmse": solution.get("RMSE"),
        }

    worker = LatestFrameWorker(background, thread_name="anchor-preprocess-and-solve")
    fusion = PreprocessedAnchor()
    rows = []
    completed_rows = []
    start = time.perf_counter()
    try:
        for index, (filename, raw, meta) in enumerate(frames):
            begin = time.perf_counter()
            epoch = begin - start
            job = {
                "index": index,
                "epoch": epoch,
                "generation": fusion.generation,
                "frame": raw,
                "meta": meta,
            }
            worker.offer(job)
            raw_start = time.perf_counter()
            detection = star_detect.detect_stars(
                raw,
                sigma=4.0,
                saturation_level=4095,
                warm_pixel_map=warm,
                cloud_window_gate=False,
            )
            solution, _, _, _ = _cascade(
                raw_solver,
                np.empty((0, 2)),
                detection.centroids,
                raw.shape,
                "",
                meta["geometry"],
            )
            raw_ms = (time.perf_counter() - raw_start) * 1000
            raw_solved = solution.get("RA") is not None
            if raw_solved:
                fusion.add_raw(SkySample(index, epoch, solution["RA"], solution["Dec"]))
            completed = worker.poll()
            now = time.perf_counter() - start
            if completed is not None:
                if completed.error is not None:
                    raise completed.error
                value = completed.value
                item = {
                    "source_frame": completed.item["index"],
                    "elapsed_ms": completed.elapsed_ms,
                    "accepted": False,
                    "generation": completed.item["generation"],
                }
                if value["sample"] is not None:
                    item["accepted"] = fusion.add_preprocessed(
                        value["sample"],
                        generation=completed.item["generation"],
                        window_start_s=value["window_start_s"],
                        now_s=now,
                    )
                    item["source_age_s"] = now - value["sample"].exposure_s
                item["reason"] = fusion.last_reason
                item["window_shake_arcsec"] = fusion.last_window_shake_arcsec
                completed_rows.append(item)
            estimate = fusion.estimate(now)
            elapsed = (time.perf_counter() - begin) * 1000
            rows.append(
                {
                    "file": filename,
                    "foreground_ms": elapsed,
                    "raw_ms": raw_ms,
                    "raw_solved": raw_solved,
                    "epoch": epoch,
                    "estimate": vars(estimate) if estimate else None,
                }
            )
            print(
                filename,
                f"{elapsed:.1f}ms",
                estimate.source if estimate else "unavailable",
                flush=True,
            )
            time.sleep(max(0, args.interval - (time.perf_counter() - begin)))
        stats = vars(worker.stats())
    finally:
        worker.close()
        accumulator.close()
    times = [r["foreground_ms"] for r in rows]
    background_times = [r["elapsed_ms"] for r in completed_rows]
    summary = {
        "frames": len(rows),
        "input_interval_s": args.interval,
        "raw_solved": sum(r["raw_solved"] for r in rows),
        "sources": dict(
            Counter(
                r["estimate"]["source"] if r["estimate"] else "unavailable"
                for r in rows
            )
        ),
        "foreground_ms": {
            "p50": float(np.median(times)),
            "p95": float(np.percentile(times, 95)),
        },
        "background_ms": {
            "p50": float(np.median(background_times)),
            "p95": float(np.percentile(background_times, 95)),
        },
        "anchor_accepts": sum(r["accepted"] for r in completed_rows),
        "worker": stats,
        "background_solver_independent": worker_state["solver"] is not raw_solver,
        "foreground_waits_for_preprocessing": False,
    }
    args.output.write_text(
        json.dumps(
            {"summary": summary, "rows": rows, "completed": completed_rows}, indent=2
        )
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
