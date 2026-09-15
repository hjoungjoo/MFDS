# SPDX-License-Identifier: GPL-3.0-only
"""Internal placement experiment; no production service or license changes.

The co-located arms use the existing ctypes comparison backend in a Python
experiment process. They model IPC removal, not a native preprocessing port.
Shared arrays carry pixels; pipes carry control and small centroid results.
Detailed coordinates stay in the local result file; publish only summary.
"""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import importlib.util
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
import time
import traceback

import numpy as np
from PIL import Image
import tetra3

from PiFinder import mf_detect_process, star_detect, utils
from PiFinder.detector_profiles import configure_profile
from replay_star_preprocess_ab import _cascade


MODES = {
    "current": (False, False, "process"),
    "moved": (True, False, "process"),
    "colocated": (True, False, "ctypes"),
    "colocated_cached": (True, True, "ctypes"),
    "current_cached": (False, True, "process"),
}


def load_module(path):
    name = "placement_preprocessor"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def calculate(accumulator, frame, fingerprint, warm):
    started = time.perf_counter()
    result = accumulator.add(frame, saturation_level=4095, fingerprint=fingerprint)
    pre_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    detection = star_detect.detect_stars(
        result.frame,
        saturation_level=None,
        cloud_window_gate=False,
        warm_pixel_map=warm,
    )
    detect_ms = (time.perf_counter() - started) * 1000
    return result, {
        "preprocess_ms": pre_ms,
        "detect_ms": detect_ms,
        "centroids": detection.centroids,
        "fluxes": detection.fluxes,
        "backend": detection.backend,
        "diagnostics": asdict(result.diagnostics),
    }


def worker(connection, raw_buffer, output_buffer, shape, path, transport, warm):
    os.environ["MF_DETECT_TRANSPORT"] = transport
    configure_profile("mf4p")
    module = load_module(path)
    accumulator = module.MFStarOnlyAccumulator(
        module.MFStarOnlyConfig(parallel_scale_workers=3)
    )
    raw = np.frombuffer(raw_buffer, dtype=np.uint16).reshape(shape)
    output = np.frombuffer(output_buffer, dtype=np.uint16).reshape(shape)
    connection.send("ready")
    try:
        while True:
            request = connection.recv()
            if request is None:
                break
            result, info = calculate(accumulator, raw, request, warm)
            np.copyto(output, result.frame)
            # Hashing is validation overhead, reported separately from kernels.
            info["evidence_hash"] = hashlib.sha256(
                result.evidence.tobytes()
            ).hexdigest()
            connection.send(info)
    except EOFError:
        pass
    except Exception:
        connection.send({"error": traceback.format_exc()})
    finally:
        accumulator.close()
        mf_detect_process.close_workers()
        connection.close()


class Endpoint:
    def __init__(self, mode, shape, reference, implementation, warm):
        remote, optimized, transport = MODES[mode]
        self.remote, self.warm = remote, warm
        path = implementation if optimized else reference
        self.accumulator = None
        self.process = None
        if not remote:
            module = load_module(path)
            self.accumulator = module.MFStarOnlyAccumulator(
                module.MFStarOnlyConfig(parallel_scale_workers=3)
            )
        else:
            context = mp.get_context("spawn")
            raw_buffer = context.RawArray("H", int(np.prod(shape)))
            output_buffer = context.RawArray("H", int(np.prod(shape)))
            self.raw = np.frombuffer(raw_buffer, dtype=np.uint16).reshape(shape)
            self.output = np.frombuffer(output_buffer, dtype=np.uint16).reshape(shape)
            self.connection, child = context.Pipe()
            self.process = context.Process(
                target=worker,
                args=(child, raw_buffer, output_buffer, shape, path, transport, warm),
            )
            self.process.start()
            child.close()
            if not self.connection.poll(30) or self.connection.recv() != "ready":
                self.close()
                raise RuntimeError("worker startup failed")

    def run(self, frame, fingerprint):
        if self.remote:
            np.copyto(self.raw, frame)
            self.connection.send(fingerprint)
            if not self.connection.poll(30):
                raise TimeoutError("preprocessing worker timed out")
            info = self.connection.recv()
            if "error" in info:
                raise RuntimeError(info["error"])
            return self.output.copy(), info
        result, info = calculate(self.accumulator, frame, fingerprint, self.warm)
        info["evidence_hash"] = hashlib.sha256(result.evidence.tobytes()).hexdigest()
        return result.frame, info

    def close(self):
        if self.accumulator is not None:
            self.accumulator.close()
        if self.process is not None:
            if self.process.is_alive():
                try:
                    self.connection.send(None)
                except (BrokenPipeError, OSError):
                    pass
                self.process.join(3)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(3)
            if self.process.is_alive():
                self.process.kill()
                self.process.join()
            self.connection.close()


def metrics(values):
    return {
        "p50": float(np.median(values)) if values else None,
        "p95": float(np.percentile(values, 95)) if values else None,
    }


def summarize(rows):
    summary = {}
    for mode in MODES:
        selected = [r for r in rows if r["mode"] == mode and r["index"] >= 4]
        if not selected:
            continue
        summary[mode] = {
            "attempts": len(selected),
            "solved": sum(r["ra"] is not None for r in selected),
            "backends": dict(Counter(r["backend"] for r in selected)),
            "exact_pixels_evidence_detections_diagnostics": all(
                r["exact"] for r in selected
            ),
            "exact_solution": sum(r["exact_solution"] for r in selected),
        }
        for key in (
            "preprocess_ms",
            "detect_ms",
            "pipeline_ms",
            "solve_ms",
            "total_ms",
            "rmse",
        ):
            summary[mode][key] = metrics(
                [r[key] for r in selected if r[key] is not None]
            )
        raw = [value for r in selected for value in r["raw_probe_ms"]]
        summary[mode]["raw_probe_count"] = len(raw)
        summary[mode]["raw_probe_ms"] = metrics(raw)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--implementation", required=True, type=Path)
    parser.add_argument("--frames", type=int, default=20)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--modes", default=",".join(MODES))
    parser.add_argument("--raw-probe", action="store_true")
    parser.add_argument("--wide", action="store_true")
    args = parser.parse_args()
    if args.output.exists() or args.frames < 5 or args.repeats < 1 or args.start < 0:
        parser.error(
            "new output, >=5 frames, nonnegative start and positive repeats required"
        )
    modes = args.modes.split(",")
    if "current" not in modes or any(m not in MODES for m in modes):
        parser.error("known modes including current required")
    paths = sorted(args.cache.glob("*.npy"))[args.start : args.start + args.frames]
    if len(paths) != args.frames:
        parser.error("insufficient frames")
    frames = []
    for path in paths:
        meta = json.loads(path.with_suffix(".json").read_text())
        source = args.corpus / (path.stem + ".tiff")
        if hashlib.sha256(source.read_bytes()).hexdigest() != meta["source_sha256"]:
            raise ValueError("source/cache hash mismatch")
        frame = np.ascontiguousarray(
            np.rot90(np.asarray(Image.open(source), dtype=np.uint16), -1)
        )
        frames.append((path.name, frame, meta))
    configure_profile("mf4p")
    os.environ["MF_DETECT_TRANSPORT"] = "process"
    warm_path = utils.data_dir / "sep_warm_pixels.npy"
    warm = np.load(warm_path) if warm_path.exists() else None
    solvers = {
        mode: tetra3.Tetra3(str(utils.tetra3_dir / "data/default_database.npz"))
        for mode in modes
    }
    rows, startup = [], []
    for repeat in range(args.repeats):
        endpoints = {}
        try:
            for mode in modes:
                started = time.perf_counter()
                endpoints[mode] = Endpoint(
                    mode, frames[0][1].shape, args.reference, args.implementation, warm
                )
                startup.append(
                    {
                        "mode": mode,
                        "repeat": repeat,
                        "ms": (time.perf_counter() - started) * 1000,
                    }
                )
            # One task at a time; only requested RAW probes overlap preprocessing.
            with ThreadPoolExecutor(max_workers=1) as executor:
                for index, (filename, frame, meta) in enumerate(frames):
                    offset = (index + repeat) % len(modes)
                    order = modes[offset:] + modes[:offset]
                    pair = {}
                    for mode in order:
                        started = time.perf_counter()
                        future = executor.submit(
                            endpoints[mode].run,
                            frame,
                            (frame.shape, json.dumps(meta["geometry"], sort_keys=True)),
                        )
                        probes, next_probe = [], time.perf_counter()
                        if args.raw_probe:
                            while not future.done():
                                if time.perf_counter() >= next_probe:
                                    raw_start = time.perf_counter()
                                    star_detect.detect_stars(
                                        frame,
                                        saturation_level=4095,
                                        cloud_window_gate=args.wide,
                                        warm_pixel_map=warm,
                                    )
                                    probes.append(
                                        (time.perf_counter() - raw_start) * 1000
                                    )
                                    next_probe = max(
                                        next_probe + 0.1, time.perf_counter()
                                    )
                                else:
                                    time.sleep(0.001)
                        output, info = future.result()
                        pipeline_ms = (time.perf_counter() - started) * 1000
                        solution, route, reason, solve_ms = _cascade(
                            solvers[mode],
                            np.empty((0, 2)),
                            info["centroids"],
                            frame.shape,
                            "preprocessed_",
                            meta["geometry"],
                        )
                        row = {
                            k: v
                            for k, v in info.items()
                            if k not in ("centroids", "fluxes")
                        }
                        row.update(
                            mode=mode,
                            repeat=repeat,
                            index=index,
                            file=filename,
                            pipeline_ms=pipeline_ms,
                            solve_ms=solve_ms,
                            total_ms=pipeline_ms + solve_ms,
                            raw_probe_ms=probes,
                            ra=solution.get("RA"),
                            dec=solution.get("Dec"),
                            roll=solution.get("Roll"),
                            rmse=solution.get("RMSE"),
                            matches=solution.get("Matches"),
                            route=route,
                            reason=reason,
                        )
                        pair[mode] = (output, info, row)
                    baseline = pair["current"]
                    for output, info, row in pair.values():
                        row["exact"] = bool(
                            np.array_equal(output, baseline[0])
                            and all(
                                np.array_equal(info[k], baseline[1][k])
                                for k in ("centroids", "fluxes")
                            )
                            and info["evidence_hash"] == baseline[1]["evidence_hash"]
                            and info["diagnostics"] == baseline[1]["diagnostics"]
                        )
                        row["exact_solution"] = all(
                            row[k] == baseline[2][k]
                            for k in ("ra", "dec", "roll", "rmse", "matches", "route")
                        )
                        if not row["exact"]:
                            raise AssertionError(
                                f"changed numerical output: {filename}/{row['mode']}"
                            )
                        rows.append(row)
                    print(
                        f"repeat={repeat} frame={index + 1}/{len(frames)} exact",
                        flush=True,
                    )
        finally:
            for endpoint in endpoints.values():
                endpoint.close()
            mf_detect_process.close_workers()
    hashes = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (
            Path(__file__),
            args.reference,
            args.implementation,
            Path(star_detect.__file__).resolve(),
            mf_detect_process.native_server_path(),
            star_detect.native_library_path(),
        )
    }
    result = {
        "summary": summarize(rows),
        "startup": startup,
        "source_hashes": hashes,
        "raw_probe": args.raw_probe,
        "shape": list(frames[0][1].shape),
        "warmup_excluded_per_repeat": 4,
        "rows": rows,
    }
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
