#!/usr/bin/python
"""Replay one RAW corpus through the production raw/preprocessed solve cascade.

The two arms consume the same lossless frames.  The preprocessed arm uses a
temporal window ending at the current frame, matching the live solver; frame 1
is therefore a warm-up frame and is not counted as a preprocessed attempt.

The test-branch detector defaults to MF first, SEP on extraction failure only.
PIFINDER_DETECTOR=sep reproduces the SEP arm of historical reports. Historical
Cedar CSV columns are zero; no Cedar imports or sockets exist.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import statistics
import time
from typing import Any, Iterable

import numpy as np
from PIL import Image
import tetra3

from PiFinder import star_detect
from PiFinder import sep_detect, solver_frame_map as sfm, utils
from PiFinder.config import Config
from PiFinder.mf_star_only_preprocess import MFStarOnlyAccumulator, MFStarOnlyConfig
from PiFinder.mf_manual_lens import calibration_lens_key
from PiFinder.mf_cloud_gate import wide_cloud_gate_enabled
from PiFinder.mf_wide_calibration import CalibrationProfileStore
from PiFinder.mf_wide_distortion import (
    active_coefficients,
    undistort_global_centroids,
)
from PiFinder.optics import build_optical_train
from PiFinder.solve_acceptance import (
    SolveContinuityGate,
    angular_separation_deg,
    solution_quality_decision,
)
from PiFinder.sqm.camera_profiles import get_camera_profile


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path, help="directory containing RAW TIFFs")
    parser.add_argument("--glob", default="raw_*.tiff", help="input filename glob")
    parser.add_argument("--camera", default="imx462_color")
    parser.add_argument("--lens", default="6mm")
    parser.add_argument("--manual-focal", type=float)
    parser.add_argument("--display-rotation", type=int, default=90)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--preprocess-workers", type=int, choices=(2, 3, 4), default=3)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", type=Path, help="CSV output path")
    return parser.parse_args()


def _undo_display_rotation(frame: np.ndarray, degrees: int) -> np.ndarray:
    rotation = int(degrees) % 360
    if rotation not in {0, 90, 180, 270}:
        raise ValueError("display rotation must be a multiple of 90 degrees")
    return np.ascontiguousarray(np.rot90(frame, -(rotation // 90)))


def _frame_controls(path: Path) -> tuple[float | None, float | None]:
    """Read capture-time exposure/gain from an optional indexed sidecar."""

    suffix = path.stem.removeprefix("raw_")
    sidecar = path.with_name(f"controls_{suffix}.json")
    if not sidecar.exists():
        return None, None
    try:
        payload = json.loads(sidecar.read_text())
        return (
            float(payload["exposure"]["actual_us"]),
            float(payload["gain"]["actual"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None, None


class DisabledCedar:
    """Empty historical tier: this replay never connects to Cedar Detect."""

    def __init__(self, address=None):
        pass

    def close(self):
        pass

    def detect(self, frame):
        return np.empty((0, 2)), 0.0


def _center_square(centroids: np.ndarray, frame_hw: tuple[int, int]) -> np.ndarray:
    points = np.asarray(centroids, dtype=np.float64).reshape(-1, 2)
    height, width = map(float, frame_hw)
    side = min(height, width)
    y0, x0 = (height - side) / 2.0, (width - side) / 2.0
    keep = (
        (points[:, 0] >= y0)
        & (points[:, 0] < y0 + side)
        & (points[:, 1] >= x0)
        & (points[:, 1] < x0 + side)
    )
    return points[keep]


def _band_counts(centroids: np.ndarray, height: int) -> str:
    points = np.asarray(centroids, dtype=np.float64).reshape(-1, 2)
    counts = [
        int(np.count_nonzero((points[:, 0] >= lo) & (points[:, 0] < hi)))
        for lo, hi in (
            (0, height / 3.0),
            (height / 3.0, 2.0 * height / 3.0),
            (2.0 * height / 3.0, height + 1),
        )
    ]
    return "/".join(map(str, counts))


def _solve(
    t3: tetra3.Tetra3,
    centroids: np.ndarray,
    frame_hw: tuple[int, int],
    path: str,
    *,
    rotation_deg: float,
    crop_width_px: int,
    base_fov_degrees: float,
    distortion: dict[str, float] | None,
) -> tuple[dict[str, Any], str, float]:
    started = time.perf_counter()
    source = np.asarray(centroids, dtype=np.float64).reshape(-1, 2)
    if distortion is not None:
        source = undistort_global_centroids(source, frame_hw, distortion)
    rotated, canvas = sfm.rotate_centroids(source, frame_hw, rotation_deg)
    fov = sfm.fov_estimate_deg(
        canvas[1], crop_width_px, base_fov_degrees=base_fov_degrees
    )
    solution = t3.solve_from_centroids(
        rotated,
        canvas,
        fov_estimate=fov,
        fov_max_error=fov / 3.0,
        match_max_error=0.005,
        return_matches=True,
        target_pixel=((canvas[0] - 1) / 2.0, (canvas[1] - 1) / 2.0),
        solve_timeout=1000,
    )
    decision = solution_quality_decision(solution, path)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if not decision.accepted:
        return {}, decision.reason, elapsed_ms
    return dict(solution), decision.reason, elapsed_ms


def _cascade(
    t3: tetra3.Tetra3,
    cedar: np.ndarray,
    sep: np.ndarray,
    frame_hw: tuple[int, int],
    prefix: str,
    geometry: dict[str, Any],
) -> tuple[dict[str, Any], str, str, float]:
    cedar_center = _center_square(cedar, frame_hw)
    sep_center = _center_square(sep, frame_hw)
    stages: list[tuple[str, np.ndarray]] = []
    if prefix:
        if len(cedar_center) >= 4:
            stages.append((f"{prefix}cedar_center", cedar_center))
        if len(sep_center) >= 5:
            stages.append((f"{prefix}sep_center", sep_center))
    else:
        # The production raw cascade skips a centre attempt if it is exactly
        # the same candidate set as the later full-frame attempt.
        if 4 <= len(cedar_center) < len(cedar):
            stages.append(("cedar_center", cedar_center))
        if 5 <= len(sep_center) < len(sep):
            stages.append(("sep_center", sep_center))
    if len(cedar) >= 4:
        stages.append((f"{prefix}cedar_full", cedar))
    if len(sep) >= 5:
        stages.append((f"{prefix}sep_full", sep))

    last_reason = "insufficient_centroids"
    elapsed_ms = 0.0
    for path, points in stages:
        solution, reason, solve_ms = _solve(t3, points, frame_hw, path, **geometry)
        elapsed_ms += solve_ms
        last_reason = reason
        if solution.get("RA") is not None:
            return solution, path, reason, elapsed_ms
    return {}, "", last_reason, elapsed_ms


def _solution_fields(solution: dict[str, Any]) -> dict[str, Any]:
    if not solution:
        return {"ra": "", "dec": "", "matches": 0, "rmse": "", "prob": ""}
    return {
        "ra": float(solution["RA"]),
        "dec": float(solution["Dec"]),
        "matches": int(solution.get("Matches") or 0),
        "rmse": float(solution.get("RMSE") or 0.0),
        "prob": float(solution.get("Prob") or 0.0),
    }


def _median(values: Iterable[float]) -> float | None:
    items = list(values)
    return statistics.median(items) if items else None


def _route_summary(rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
    solved = [row for row in rows if row[f"{name}_path"]]
    continuity = [row for row in solved if row[f"{name}_continuity"]]
    coordinates = [
        (float(row[f"{name}_ra"]), float(row[f"{name}_dec"])) for row in solved
    ]
    separations: list[float] = []
    if coordinates:
        reference = min(
            coordinates,
            key=lambda point: sum(
                angular_separation_deg(*point, *other) for other in coordinates
            ),
        )
        separations = [
            angular_separation_deg(*reference, *point) for point in coordinates
        ]
    return {
        "attempts": len([row for row in rows if row[f"{name}_attempted"]]),
        "quality_solved": len(solved),
        "continuity_accepted": len(continuity),
        "paths": dict(Counter(row[f"{name}_path"] or "none" for row in rows)),
        "cedar_candidates_median": _median(
            float(row[f"{name}_cedar"]) for row in rows if row[f"{name}_attempted"]
        ),
        "sep_candidates_median": _median(
            float(row[f"{name}_sep"]) for row in rows if row[f"{name}_attempted"]
        ),
        "matches_median": _median(float(row[f"{name}_matches"]) for row in solved),
        "rmse_median_arcsec": _median(float(row[f"{name}_rmse"]) for row in solved),
        "separation_median_deg": _median(separations),
        "separation_max_deg": max(separations) if separations else None,
        "coordinate_outliers_over_2deg": sum(value > 2.0 for value in separations),
        "detector_ms_median": _median(
            float(row[f"{name}_detect_ms"]) for row in rows if row[f"{name}_attempted"]
        ),
        "solve_ms_median": _median(
            float(row[f"{name}_solve_ms"]) for row in rows if row[f"{name}_attempted"]
        ),
    }


def main() -> int:
    args = _arguments()
    files = sorted(args.corpus.glob(args.glob))
    if args.limit:
        files = files[: args.limit]
    if args.cache_dir:
        args.cache_dir.mkdir(parents=True, exist_ok=True)
    if not files:
        raise SystemExit(f"no input files matched {args.corpus / args.glob}")

    profile = get_camera_profile(args.camera)
    crop_width = int(profile.raw_size[0] - sum(profile.crop_x))
    cfg = Config()
    calibration = CalibrationProfileStore(cfg).load_active(
        args.camera, calibration_lens_key(args.lens, args.manual_focal), profile
    )
    geometry = {
        "rotation_deg": sfm.stage5_rotation_deg(
            cfg.get_option("screen_direction"), cfg.get_option("camera_rotation")
        ),
        "crop_width_px": crop_width,
        "base_fov_degrees": build_optical_train(
            args.camera, args.lens, args.manual_focal
        ).fov_degrees,
        "distortion": active_coefficients(calibration),
    }
    warm_map = None
    warm_map_path = utils.data_dir / "sep_warm_pixels.npy"
    if warm_map_path.exists():
        warm_map = np.asarray(np.load(warm_map_path), dtype=np.int32)

    t3 = tetra3.Tetra3(str(utils.tetra3_dir / "data" / "default_database.npz"))
    cedar_client = DisabledCedar()
    accumulator = MFStarOnlyAccumulator(
        MFStarOnlyConfig(parallel_scale_workers=args.preprocess_workers)
    )
    raw_continuity = SolveContinuityGate()
    pre_continuity = SolveContinuityGate()
    rows: list[dict[str, Any]] = []

    try:
        for index, path in enumerate(files, start=1):
            display_frame = np.asarray(Image.open(path), dtype=np.uint16)
            frame = _undo_display_rotation(display_frame, args.display_rotation)
            frame_hw = (int(frame.shape[0]), int(frame.shape[1]))
            exposure_us, gain = _frame_controls(path)

            raw_cedar_all, raw_cedar_ms = cedar_client.detect(frame)
            raw_cedar = sep_detect.filter_plain_centroids(
                raw_cedar_all,
                frame,
                saturation_level=float(2**profile.bit_depth - 1),
                warm_pixel_map=warm_map,
            )
            raw_sep_started = time.perf_counter()
            raw_sep_result = star_detect.detect_stars(
                frame,
                sigma=float(cfg.get_option("solver_sep_sigma") or 4.0),
                saturation_level=float(2**profile.bit_depth - 1),
                warm_pixel_map=warm_map,
                cloud_window_gate=wide_cloud_gate_enabled(args.lens, args.manual_focal),
            )
            raw_sep_ms = (time.perf_counter() - raw_sep_started) * 1000.0
            raw_sep = (
                np.empty((0, 2)) if raw_sep_result is None else raw_sep_result.centroids
            )
            raw_solution, raw_path, raw_reason, raw_solve_ms = _cascade(
                t3, raw_cedar, raw_sep, frame_hw, "", geometry
            )
            raw_gate = (
                raw_continuity.evaluate(raw_solution, raw_path, float(index))
                if raw_solution
                else None
            )

            pre_started = time.perf_counter()
            pre_result = accumulator.add(
                frame,
                saturation_level=float(2**profile.bit_depth - 1),
                fingerprint=(
                    args.camera,
                    args.lens,
                    frame_hw,
                    exposure_us,
                    gain,
                ),
            )
            preprocess_ms = (time.perf_counter() - pre_started) * 1000.0
            pre_attempted = pre_result.diagnostics.frame_count >= 2
            if args.cache_dir:
                np.save(args.cache_dir / (path.stem + ".npy"), pre_result.frame)
                (args.cache_dir / (path.stem + ".json")).write_text(
                    json.dumps(
                        {
                            "source_sha256": hashlib.sha256(
                                path.read_bytes()
                            ).hexdigest(),
                            "frame_count": pre_result.diagnostics.frame_count,
                            "preprocess_ms": preprocess_ms,
                            "geometry": geometry,
                            "exposure_us": exposure_us,
                            "gain": gain,
                        }
                    )
                )
            pre_cedar_all = np.empty((0, 2))
            pre_cedar = np.empty((0, 2))
            pre_sep = np.empty((0, 2))
            pre_detect_ms = 0.0
            pre_solution: dict[str, Any] = {}
            pre_path = ""
            pre_reason = "warmup"
            pre_solve_ms = 0.0
            pre_gate = None
            if pre_attempted:
                pre_cedar_all, pre_cedar_ms = cedar_client.detect(pre_result.frame)
                pre_cedar = sep_detect.filter_plain_centroids(
                    pre_cedar_all,
                    pre_result.frame,
                    saturation_level=None,
                    warm_pixel_map=warm_map,
                )
                pre_sep_started = time.perf_counter()
                pre_sep_result = star_detect.detect_stars(
                    pre_result.frame,
                    sigma=float(cfg.get_option("solver_sep_sigma") or 4.0),
                    saturation_level=None,
                    warm_pixel_map=warm_map,
                    cloud_window_gate=False,
                )
                pre_sep_ms = (time.perf_counter() - pre_sep_started) * 1000.0
                pre_sep = (
                    np.empty((0, 2))
                    if pre_sep_result is None
                    else pre_sep_result.centroids
                )
                pre_detect_ms = pre_cedar_ms + pre_sep_ms + preprocess_ms
                pre_solution, pre_path, pre_reason, pre_solve_ms = _cascade(
                    t3,
                    pre_cedar,
                    pre_sep,
                    frame_hw,
                    "preprocessed_",
                    geometry,
                )
                pre_gate = (
                    pre_continuity.evaluate(pre_solution, pre_path, float(index))
                    if pre_solution
                    else None
                )

            row: dict[str, Any] = {
                "index": index,
                "file": path.name,
                "exposure_us": "" if exposure_us is None else exposure_us,
                "gain": "" if gain is None else gain,
                "raw_attempted": True,
                "raw_cedar_raw": len(raw_cedar_all),
                "raw_cedar": len(raw_cedar),
                "raw_cedar_bands": _band_counts(raw_cedar, frame_hw[0]),
                "raw_sep": len(raw_sep),
                "raw_sep_bands": _band_counts(raw_sep, frame_hw[0]),
                "raw_cedar_ms": raw_cedar_ms,
                "raw_sep_ms": raw_sep_ms,
                "raw_detect_ms": raw_cedar_ms + raw_sep_ms,
                "raw_solve_ms": raw_solve_ms,
                "raw_path": raw_path,
                "raw_reason": raw_reason,
                "raw_continuity": bool(raw_gate and raw_gate.accepted),
                "raw_continuity_reason": raw_gate.reason if raw_gate else "no_solution",
                "pre_attempted": pre_attempted,
                "pre_window": pre_result.diagnostics.frame_count,
                "pre_hard_mask_fraction": pre_result.diagnostics.hard_mask_fraction,
                "pre_persistent_pixels": pre_result.diagnostics.persistent_pixels,
                "pre_cedar_raw": len(pre_cedar_all),
                "pre_cedar": len(pre_cedar),
                "pre_cedar_bands": _band_counts(pre_cedar, frame_hw[0]),
                "pre_sep": len(pre_sep),
                "pre_sep_bands": _band_counts(pre_sep, frame_hw[0]),
                "preprocess_ms": preprocess_ms,
                "pre_cedar_ms": pre_cedar_ms if pre_attempted else 0.0,
                "pre_sep_ms": pre_sep_ms if pre_attempted else 0.0,
                "pre_detect_ms": pre_detect_ms,
                "pre_solve_ms": pre_solve_ms,
                "pre_path": pre_path,
                "pre_reason": pre_reason,
                "pre_continuity": bool(pre_gate and pre_gate.accepted),
                "pre_continuity_reason": pre_gate.reason if pre_gate else "no_solution",
            }
            row.update(
                {
                    f"raw_{key}": value
                    for key, value in _solution_fields(raw_solution).items()
                }
            )
            row.update(
                {
                    f"pre_{key}": value
                    for key, value in _solution_fields(pre_solution).items()
                }
            )
            rows.append(row)
            print(
                f"{index:02d}/{len(files):02d} "
                f"raw C/S={len(raw_cedar)}/{len(raw_sep)} {raw_path or '-'} "
                f"pre[{pre_result.diagnostics.frame_count}] "
                f"C/S={len(pre_cedar)}/{len(pre_sep)} {pre_path or '-'}",
                flush=True,
            )
    finally:
        cedar_client.close()

    output = args.output or (args.corpus / "ab_results.csv")
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    paired = [row for row in rows if row["pre_attempted"]]
    agreements = [
        angular_separation_deg(
            float(row["raw_ra"]),
            float(row["raw_dec"]),
            float(row["pre_ra"]),
            float(row["pre_dec"]),
        )
        for row in paired
        if row["raw_path"] and row["pre_path"]
    ]
    summary = {
        "corpus": str(args.corpus),
        "frames": len(rows),
        "geometry": geometry,
        "raw": _route_summary(rows, "raw"),
        "preprocessed": _route_summary(rows, "pre"),
        "paired": {
            "frames": len(paired),
            "both_solved": sum(
                bool(row["raw_path"] and row["pre_path"]) for row in paired
            ),
            "raw_only": sum(
                bool(row["raw_path"] and not row["pre_path"]) for row in paired
            ),
            "preprocessed_only": sum(
                bool(not row["raw_path"] and row["pre_path"]) for row in paired
            ),
            "neither": sum(
                bool(not row["raw_path"] and not row["pre_path"]) for row in paired
            ),
            "agreement_median_deg": _median(agreements),
            "disagreements_over_2deg": sum(value > 2.0 for value in agreements),
        },
    }
    summary_path = output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"CSV: {output}")
    print(f"summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
