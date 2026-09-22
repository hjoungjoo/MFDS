# SPDX-License-Identifier: GPL-3.0-only
"""Offline NumPy/NEON A/B with exact full preprocessing output checks."""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import time

import numpy as np
from PIL import Image

from PiFinder.mf_star_only_preprocess import MFStarOnlyAccumulator, MFStarOnlyConfig


class TimedReduction:
    def __init__(self, backend):
        self.backend = backend
        self.elapsed_ms = 0.0

    def __call__(self, *args):
        start = time.perf_counter()
        result = self.backend(*args)
        self.elapsed_ms = (time.perf_counter() - start) * 1000
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path, help="New JSON file; never overwrites")
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--backend", choices=("neon", "auto"), default="neon")
    parser.add_argument("--saturation", type=int, default=4095)
    args = parser.parse_args()
    files = sorted(args.corpus.glob("raw_*.tiff"))[: args.frames]
    if args.frames < 6 or len(files) < 6 or args.repeats < 1:
        parser.error("At least six frames and one repeat required")
    if not 1 <= args.workers <= 4 or not 1 <= args.saturation <= 65535:
        parser.error("Invalid worker count or saturation")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        output.write('{"status":"running"}\n')
    root = Path(__file__).resolve().parents[3]
    sources = (
        "integrations/pifinder/PiFinder/mf_star_only_preprocess.py",
        "integrations/pifinder/native/temporal_reduce.cpp",
        "integrations/pifinder/native/temporal_reduce.h",
        "build/libmf_temporal_reduce.so",
    )
    library = Path(
        os.environ.get(
            "MF_PREPROCESS_REDUCTION_LIBRARY",
            str(root / "build/libmf_temporal_reduce.so"),
        )
    ).resolve()
    report = {
        "status": "running",
        "scope": "offline full preprocessing; excludes exposure, detector, solver and UI",
        "platform": platform.platform(),
        "corpus": str(args.corpus.resolve()),
        "backend_requested": args.backend,
        "library_path": str(library),
        "library_sha256": hashlib.sha256(library.read_bytes()).hexdigest()
        if library.is_file()
        else None,
        "workers": args.workers,
        "saturation": args.saturation,
        "warmup_frames_per_repeat": 4,
        "input_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files
        },
        "source_sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            if (root / name).is_file()
            else None
            for name in sources
        },
        "rows": [],
    }
    try:
        for repeat in range(args.repeats):
            accumulators = {
                name: MFStarOnlyAccumulator(
                    MFStarOnlyConfig(
                        accelerator="cpu",
                        reduction_backend=mode,
                        parallel_scale_workers=args.workers,
                    )
                )
                for name, mode in (("numpy", "numpy"), ("optimized", args.backend))
            }
            timers = {}
            for name, accumulator in accumulators.items():
                timer = TimedReduction(accumulator.reduction_backend)
                timers[name] = timer
                accumulator.reduction_backend = timer
            try:
                for index, path in enumerate(files):
                    with Image.open(path) as image:
                        frame = np.array(image, dtype=np.uint16)
                    row = {"repeat": repeat, "file": path.name, "warmup": index < 4}
                    outputs = {}
                    order = (
                        ("numpy", "optimized")
                        if (repeat + index) % 2 == 0
                        else ("optimized", "numpy")
                    )
                    for name in order:
                        start = time.perf_counter()
                        outputs[name] = accumulators[name].add(
                            frame,
                            saturation_level=args.saturation,
                            fingerprint=frame.shape,
                        )
                        row[name + "_ms"] = (time.perf_counter() - start) * 1000
                        row[name + "_reduce_ms"] = timers[name].elapsed_ms
                    a, b = outputs["numpy"], outputs["optimized"]
                    if (
                        a.frame.tobytes() != b.frame.tobytes()
                        or a.evidence.tobytes() != b.evidence.tobytes()
                        or asdict(a.diagnostics) != asdict(b.diagnostics)
                    ):
                        raise AssertionError(f"Preprocessing output mismatch: {path}")
                    row["active_backend"] = timers["optimized"].backend.active_backend
                    row["fallback_reason"] = timers["optimized"].backend.fallback_reason
                    report["rows"].append(row)
                print(
                    f"repeat {repeat + 1}: {len(files)} exact frame/evidence/diagnostic pairs",
                    flush=True,
                )
            finally:
                for accumulator in accumulators.values():
                    accumulator.close()
        measured = [row for row in report["rows"] if not row["warmup"]]
        report["summary_ms"] = {
            key: {
                "p50": float(np.median([row[key] for row in measured])),
                "p95": float(np.percentile([row[key] for row in measured], 95)),
            }
            for key in (
                "numpy_ms",
                "optimized_ms",
                "numpy_reduce_ms",
                "optimized_reduce_ms",
            )
        }
        report["exact_pairs"] = len(report["rows"])
        report["status"] = "passed"
        print(json.dumps(report["summary_ms"], indent=2))
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        raise
    finally:
        args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
