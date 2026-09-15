"""Exercise preserved auto scheduling on recorded stationary RAW exposures.

Uses the real policy, worker, temporal preprocessing, detectors, bias and
continuity gate. This harness excludes camera IPC, SQM, mount and UI work.
"""

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image
import tetra3

from PiFinder import star_detect, utils
from PiFinder.latest_frame_worker import LatestFrameWorker
from PiFinder.mf_star_only_preprocess import MFStarOnlyAccumulator, MFStarOnlyConfig
from PiFinder.preprocess_bias import PreprocessBiasTracker
from PiFinder.solve_acceptance import SolveContinuityGate
from PiFinder.solver_scheduling import SolverSchedulingPolicy
from compare_raw_preprocessed_detectors import configure_mode
from replay_star_preprocess_ab import _cascade


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", choices=["mf2", "mf4p"], required=True)
    parser.add_argument("--frames", type=int, default=24)
    parser.add_argument("--interval", type=float, default=0.4)
    parser.add_argument("--wide", action="store_true", help="Apply RAW cloud gate")
    parser.add_argument(
        "--preprocess-source", type=Path, help="Explicit reference module"
    )
    args = parser.parse_args()
    if args.output.exists() or args.frames < 1:
        parser.error("new output and positive frame count required")
    accumulator_type, config_type = MFStarOnlyAccumulator, MFStarOnlyConfig
    source = Path(sys.modules[MFStarOnlyAccumulator.__module__].__file__).resolve()
    if args.preprocess_source is not None:
        source = args.preprocess_source.resolve()
        spec = importlib.util.spec_from_file_location(
            "auto_preprocess_reference", source
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        accumulator_type, config_type = (
            module.MFStarOnlyAccumulator,
            module.MFStarOnlyConfig,
        )
    configure_mode(args.mode)
    frames = []
    for path in sorted(args.cache.glob("*.npy"))[: args.frames]:
        meta = json.loads(path.with_suffix(".json").read_text())
        raw_path = args.corpus / (path.stem + ".tiff")
        if hashlib.sha256(raw_path.read_bytes()).hexdigest() != meta["source_sha256"]:
            raise ValueError("source/cache hash mismatch")
        raw = np.ascontiguousarray(
            np.rot90(
                np.asarray(Image.open(raw_path), dtype=np.uint16),
                -1,
            )
        )
        frames.append((path.name, raw, meta))
    t3 = tetra3.Tetra3(str(utils.tetra3_dir / "data/default_database.npz"))
    warm_path = utils.data_dir / "sep_warm_pixels.npy"
    warm = np.load(warm_path) if warm_path.exists() else None
    policy = SolverSchedulingPolicy("auto")
    bias = PreprocessBiasTracker()
    continuity = SolveContinuityGate()
    accumulators = [
        accumulator_type(config_type(parallel_scale_workers=3)) for _ in range(2)
    ]
    counts = Counter()

    def preprocess(job, accumulator):
        started = time.perf_counter()
        result = accumulator.add(
            job["frame"],
            saturation_level=4095,
            fingerprint=(
                job["generation"],
                job["frame"].shape,
                json.dumps(job["meta"]["geometry"], sort_keys=True),
            ),
        )
        if result.diagnostics.frame_count < 2:
            return None
        detection = star_detect.detect_stars(
            result.frame,
            sigma=4.0,
            saturation_level=None,
            cloud_window_gate=False,
            warm_pixel_map=warm,
        )
        return result, detection, (time.perf_counter() - started) * 1000

    worker = LatestFrameWorker(lambda job: preprocess(job, accumulators[1]))
    rows = []
    background_rows = []
    generation = 0
    previous_execution = "sync"
    try:
        for index, (filename, raw, meta) in enumerate(frames):
            started = time.perf_counter()
            with tetra3.search_budget(3000):
                raw_detection = star_detect.detect_stars(
                    raw,
                    sigma=4.0,
                    saturation_level=4095,
                    cloud_window_gate=args.wide,
                    warm_pixel_map=warm,
                )
                counts["raw_sep_calls"] += int(
                    raw_detection.fallback_reason is not None
                )
                raw_solution, raw_route, _, _ = _cascade(
                    t3,
                    np.empty((0, 2)),
                    raw_detection.centroids,
                    raw.shape,
                    "",
                    meta["geometry"],
                )
            raw_ms = (time.perf_counter() - started) * 1000
            raw_solved = raw_solution.get("RA") is not None
            execution = policy.choose(raw_solved=raw_solved)
            if execution != previous_execution:
                generation += 1
                worker.clear_pending()
                if execution == "sync":
                    accumulators[0].reset()
                previous_execution = execution
            job = {
                "file": filename,
                "frame": raw,
                "meta": meta,
                "generation": generation,
                "raw_solution": dict(raw_solution),
                "index": index,
            }
            pre_output = None
            paired_job = job
            if execution == "async":
                completed = worker.exchange(job)
                if completed is not None and completed.error is not None:
                    raise completed.error
                if (
                    completed is not None
                    and completed.is_fresh()
                    and completed.item["generation"] == generation
                ):
                    pre_output = completed.value
                    paired_job = completed.item
                    background_rows.append(
                        {"file": paired_job["file"], "ms": completed.elapsed_ms}
                    )
            else:
                pre_output = preprocess(job, accumulators[0])
            selected, route = raw_solution, raw_route
            calibration_source = None
            if pre_output is not None:
                pre, detection, _ = pre_output
                counts["preprocessed_sep_calls"] += int(
                    detection.fallback_reason is not None
                )
                with tetra3.search_budget(2600):
                    trusted, pre_route, _, _ = _cascade(
                        t3,
                        np.empty((0, 2)),
                        detection.centroids,
                        pre.frame.shape,
                        "preprocessed_",
                        paired_job["meta"]["geometry"],
                    )
                if (
                    execution == "async"
                    and completed is not None
                    and not completed.is_fresh()
                ):
                    counts["expired_results"] += 1
                    trusted = {}
                if trusted.get("RA") is not None:
                    if paired_job["raw_solution"]:
                        calibration_source = paired_job["file"]
                        if bias.update(paired_job["raw_solution"], trusted):
                            counts["bias_updates"] += 1
                        else:
                            bias.reset()
                            policy.reset("raw_preprocessed_disagreement")
                    if execution == "sync":
                        selected, route = trusted, pre_route
            if execution == "async" and raw_solved:
                selected = bias.apply(raw_solution)
                assert (
                    route == raw_route
                )  # A completed old solve never replaces current RAW.
            accepted = False
            if selected.get("RA") is not None:
                decision = continuity.evaluate(
                    selected,
                    route,
                    float(index),
                    stationary=True,
                    prefer_preprocessed=True,
                )
                accepted = decision.accepted
            policy.record_publication(accepted=accepted)
            if policy.reason == "raw_publication_stalled":
                bias.reset()
            elapsed_ms = (time.perf_counter() - started) * 1000
            rows.append(
                {
                    "file": filename,
                    "execution": execution,
                    "raw_solved": raw_solved,
                    "published": accepted,
                    "raw_ms": raw_ms,
                    "foreground_ms": elapsed_ms,
                    "raw_rmse": raw_solution.get("RMSE"),
                    "selected_rmse": selected.get("RMSE"),
                    "selected_matches": selected.get("Matches"),
                    "bias_ready": bias.ready,
                    "calibration_source": calibration_source,
                    "route": route,
                }
            )
            print(filename, execution, f"{elapsed_ms:.1f}ms", flush=True)
            time.sleep(max(0, args.interval - (time.perf_counter() - started)))
        stats = vars(worker.stats())
    finally:
        worker.close()
        for accumulator in accumulators:
            accumulator.close()
    summary = {
        "mode": args.mode,
        "preprocess_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "wide_cloud_gate": args.wide,
        "search_optimized": t3._search_optimized,
        "frames": len(rows),
        "input_interval_s": args.interval,
        "raw_solved": sum(r["raw_solved"] for r in rows),
        "published": sum(r["published"] for r in rows),
        "executions": dict(Counter(r["execution"] for r in rows)),
        "counts": dict(counts),
        "worker": stats,
    }
    for execution in ["sync", "async"]:
        part = [r for r in rows if r["execution"] == execution]
        values = [r["foreground_ms"] for r in part]
        summary[execution + "_foreground_ms"] = {
            "p50": float(np.median(values)) if values else None,
            "p95": float(np.percentile(values, 95)) if values else None,
        }
    values = [r["ms"] for r in background_rows]
    summary["background_ms"] = {
        "p50": float(np.median(values)) if values else None,
        "p95": float(np.percentile(values, 95)) if values else None,
    }
    args.output.write_text(
        json.dumps(
            {"summary": summary, "rows": rows, "background_rows": background_rows},
            indent=2,
        )
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
