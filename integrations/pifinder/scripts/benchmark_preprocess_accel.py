# SPDX-License-Identifier: GPL-3.0-only
"""Offline CPU/V3D A/B: full preprocessing, DoG and MF4p centroid agreement."""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image
from scipy.optimize import linear_sum_assignment

from PiFinder.mf_detect_process import NativeWorker
from PiFinder.mf_star_only_preprocess import MFStarOnlyAccumulator, MFStarOnlyConfig


class TimedResponse:
    def __init__(self, backend):
        self.backend = backend
        self.elapsed_ms = 0.0

    def __call__(self, frame, period):
        start = time.perf_counter()
        result = self.backend(frame, period)
        self.elapsed_ms = (time.perf_counter() - start) * 1000
        return result

    def close(self):
        self.backend.close()


def compare_stars(cpu, gpu):
    result = {"cpu_count": len(cpu), "gpu_count": len(gpu)}
    if not len(cpu) or not len(gpu):
        result["max_centroid_delta_px"] = None
        return result
    distances = np.linalg.norm(cpu[:, None, :2] - gpu[None, :, :2], axis=2)
    rows, columns = linear_sum_assignment(distances)
    result["max_centroid_delta_px"] = float(distances[rows, columns].max())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path, help="New JSON file; never overwrites")
    parser.add_argument("--glob", default="raw_*.tiff")
    parser.add_argument("--frames", type=int, default=16)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--saturation", type=int, default=4095)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    files = sorted(args.corpus.glob(args.glob))[: args.frames]
    if args.frames < 6 or len(files) < 6 or args.repeats < 1:
        parser.error("At least six frames and one repeat required")
    if not 1 <= args.saturation <= 65535 or not 1 <= args.workers <= 4:
        parser.error("Invalid saturation or worker count")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve output before expensive work. Partial/error runs remain identifiable.
    with args.output.open("x") as output:
        output.write('{"status":"running"}\n')
    report = {
        "status": "running",
        "scope": "offline preprocessing and MF4p; excludes exposure/solver/UI",
        "corpus": str(args.corpus.resolve()),
        "warmup_frames_per_repeat": 4,
        "workers": args.workers,
        "saturation": args.saturation,
        "source_sha256": {},
        "input_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files
        },
        "rows": [],
    }
    root = Path(__file__).resolve().parents[3]
    for name in [
        "integrations/pifinder/PiFinder/mf_star_only_preprocess.py",
        "integrations/pifinder/native/preprocess_gpu.cpp",
        "build/libmf_preprocess_gpu.so",
        "build/mf_detect_star_server",
    ]:
        path = root / name
        report["source_sha256"][name] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
    try:
        for repeat in range(args.repeats):
            accumulators = {
                mode: MFStarOnlyAccumulator(
                    MFStarOnlyConfig(
                        accelerator=mode,
                        parallel_scale_workers=args.workers,
                    )
                )
                for mode in ("cpu", "gpu")
            }
            timers = {}
            worker = None
            try:
                for mode, accumulator in accumulators.items():
                    timers[mode] = TimedResponse(accumulator.point_backend)
                    accumulator.point_backend = timers[mode]
                for index, path in enumerate(files):
                    with Image.open(path) as image:
                        frame = np.array(image, dtype=np.uint16)
                    if worker is None:
                        worker = NativeWorker(frame.nbytes, timeout=5.0)
                    results, detections = {}, {}
                    row = {"repeat": repeat, "file": path.name, "warmup": index < 4}
                    order = (
                        ("cpu", "gpu") if (index + repeat) % 2 == 0 else ("gpu", "cpu")
                    )
                    row["order"] = order
                    for mode in order:
                        start = time.perf_counter()
                        result = accumulators[mode].add(
                            frame,
                            saturation_level=args.saturation,
                            fingerprint=frame.shape,
                        )
                        row[mode] = {
                            "preprocess_ms": (time.perf_counter() - start) * 1000,
                            "dog_ms": timers[mode].elapsed_ms,
                            "backend": timers[mode].backend.active_backend,
                            "diagnostics": asdict(result.diagnostics),
                        }
                        results[mode] = result
                        # mode=2 is MF4p: 1/4 detection followed by 1/2 refinement.
                        detections[mode], row[mode]["detect_ms"] = worker.detect(
                            result.frame,
                            args.saturation,
                            4,
                            4.5,
                            2,
                            128,
                        )
                    cpu, gpu = results["cpu"], results["gpu"]
                    difference = np.abs(
                        cpu.frame.astype(np.int32) - gpu.frame.astype(np.int32)
                    )
                    row["max_pixel_delta"] = int(difference.max())
                    row["changed_pixels"] = int(np.count_nonzero(difference))
                    row["max_evidence_delta"] = float(
                        np.abs(cpu.evidence - gpu.evidence).max()
                    )
                    row["stars"] = compare_stars(detections["cpu"], detections["gpu"])
                    report["renderer"] = timers["gpu"].backend.renderer
                    report["rows"].append(row)
                    print(
                        f"repeat {repeat+1} frame {index+1}/{len(files)} CPU {row['cpu']['preprocess_ms']:.1f} GPU {row['gpu']['preprocess_ms']:.1f} ms",
                        flush=True,
                    )
            finally:
                for accumulator in accumulators.values():
                    accumulator.close()
                if worker is not None:
                    worker.close()
        report["summary"] = {}
        measured = [row for row in report["rows"] if not row["warmup"]]
        for mode in ("cpu", "gpu"):
            report["summary"][mode] = {
                metric: {
                    "p50": float(np.median(values)),
                    "p95": float(np.percentile(values, 95)),
                }
                for metric in ("preprocess_ms", "dog_ms", "detect_ms")
                for values in [[row[mode][metric] for row in measured]]
            }
        report["status"] = "complete"
    except BaseException as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        raise
    finally:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
