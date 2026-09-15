# SPDX-License-Identifier: GPL-3.0-only
"""Offline diagnosis of the 2026-09-15 fixed Moon/city field.

The mask is deliberately scene-specific: after undoing the TIFF display rotation,
city x < 400 and a radius-160 circle at (x=772,y=600). This is an ablation, not an
automatic horizon/Moon locator or a deployment profile. Override mask coordinates
when pointing changes; they are expressed in the unrotated sensor frame.
Only output files and this
process's detector environment are changed. All coordinates remain local outputs.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import numpy as np
from PIL import Image
import tetra3
from PiFinder import star_detect, solver_frame_map as sfm, utils
from PiFinder.detector_profiles import configure_profile
from PiFinder.mf_star_only_preprocess import MFStarOnlyAccumulator, MFStarOnlyConfig
from PiFinder.mf_manual_lens import calibration_lens_key
from PiFinder.mf_wide_calibration import CalibrationProfileStore
from PiFinder.mf_wide_distortion import active_coefficients
from PiFinder.optics import build_optical_train
from PiFinder.sqm.camera_profiles import get_camera_profile
from replay_star_preprocess_ab import _cascade

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("corpus", type=Path)
p.add_argument("output", type=Path)
p.add_argument(
    "--config",
    type=Path,
    required=True,
    help="Read-only capture-time PiFinder configuration",
)
p.add_argument("--frames", type=int, default=8)
p.add_argument("--temporal", type=int, default=5)
p.add_argument("--modes", default="")
p.add_argument("--sources", default="raw,pre")
p.add_argument("--tail", action="store_true")
p.add_argument("--city-x", type=int, default=400)
p.add_argument("--moon-x", type=float, default=772)
p.add_argument("--moon-y", type=float, default=600)
p.add_argument(
    "--moon-radius", type=float, default=160, help="Zero disables Moon exclusion"
)
p.add_argument("--mask-guard", type=float, default=16)
p.add_argument("--no-save-pre", action="store_true")
a = p.parse_args()
if a.frames < 2 or a.temporal < 2:
    p.error("At least two frames and a temporal window of two are required")
if a.modes and any(
    m not in {"mf4p", "mf2", "sep", "mf4p_mask", "mf2_mask", "sky_tiles"}
    for m in a.modes.split(",")
):
    p.error("Unsupported comparison mode")
if any(x not in {"raw", "pre"} for x in a.sources.split(",")):
    p.error("sources must be raw, pre, or raw,pre")
if a.frames > len(list(a.corpus.glob("raw_*.tiff"))):
    p.error("Not enough RAW files")
if not (0 <= a.city_x < 1920 and 0 <= a.moon_x < 1920 and 0 <= a.moon_y < 1080):
    p.error("Mask coordinates must be inside the 1920x1080 sensor frame")
if not (0 <= a.moon_radius < 1920 and 0 <= a.mask_guard < 1920):
    p.error("Invalid mask radius or guard")
if "sky_tiles" in a.modes and a.city_x != 400:
    p.error("sky_tiles geometry is only defined for the original city boundary")
a.output.mkdir(parents=True, exist_ok=False)
(a.output / "experiment.json").write_text(
    json.dumps(
        {k: str(v) if isinstance(v, Path) else v for k, v in vars(a).items()}, indent=2
    )
)
c = json.loads(a.config.read_text())
cfg = SimpleNamespace(get_option=lambda key, default=None: c.get(key, default))
profile = get_camera_profile("imx462_color")
focal = float(c["camera_lens_focal_length_mm"])
cal = CalibrationProfileStore(cfg).load_active(
    "imx462_color", calibration_lens_key("manual", focal), profile
)
geometry = {
    "rotation_deg": sfm.stage5_rotation_deg(
        c.get("screen_direction"), c.get("camera_rotation")
    ),
    "crop_width_px": int(profile.raw_size[0] - sum(profile.crop_x)),
    "base_fov_degrees": build_optical_train(
        "imx462_color", "manual", focal
    ).fov_degrees,
    "distortion": active_coefficients(cal),
}
(a.output / "geometry.json").write_text(json.dumps(geometry, indent=2))
t3 = tetra3.Tetra3(str(utils.tetra3_dir / "data/default_database.npz"))
acc = MFStarOnlyAccumulator(
    MFStarOnlyConfig(parallel_scale_workers=3, temporal_frames=a.temporal)
)
files = sorted(a.corpus.glob("raw_*.tiff"))
indices = list(range(a.frames // 2)) + list(
    range(len(files) - (a.frames - a.frames // 2), len(files))
)
if a.tail:
    indices = list(range(len(files) - a.frames, len(files)))
rows = []
frames = []
last = -1


def points_for(frame, mode, pre=False):
    configure_profile("mf2" if mode == "sky_tiles" else mode.replace("_mask", ""))
    arr = frame.copy() if mode.endswith("_mask") or mode == "sky_tiles" else frame
    if mode.endswith("_mask") or mode == "sky_tiles":
        y, x = np.ogrid[: frame.shape[0], : frame.shape[1]]
        excluded = (x < a.city_x) | (
            (x - a.moon_x) ** 2 + (y - a.moon_y) ** 2 < a.moon_radius**2
        )
        arr[excluded] = 64 if pre else 0

    def detect(part):
        return star_detect.detect_stars(
            np.ascontiguousarray(part),
            sigma=4,
            saturation_level=None if pre else 4095,
            cloud_window_gate=False,
        )

    if mode == "sky_tiles":
        os.environ["MF_DETECT_SIGMA"] = "3.0"
        groups = []
        fallback = 0
        for y0, y1 in [(0, 572), (508, 1080)]:
            for x0, x1 in [(400, 1192), (1128, 1920)]:
                d = detect(arr[y0:y1, x0:x1])
                fallback += int(d is not None and d.fallback_reason is not None)
                pts = (
                    np.empty((0, 2)) if d is None else d.centroids + np.array([y0, x0])
                )
                pts = pts[
                    (pts[:, 0] > y0 + 12)
                    & (pts[:, 0] < y1 - 12)
                    & (pts[:, 1] > x0 + 12)
                    & (pts[:, 1] < x1 - 12)
                ]
                groups.append(pts)
        combined = []
        for i in range(max(map(len, groups))):
            for group in groups:
                if i < len(group) and all(
                    np.linalg.norm(group[i] - v) > 3 for v in combined
                ):
                    combined.append(group[i])
        pts = np.array(combined, dtype=float).reshape(-1, 2)[:48]
    else:
        d = detect(arr)
        fallback = int(d is not None and d.fallback_reason is not None)
        pts = np.empty((0, 2)) if d is None else d.centroids
    if mode.endswith("_mask") or mode == "sky_tiles":
        pts = pts[
            (pts[:, 1] > a.city_x + a.mask_guard)
            & (
                (a.moon_radius == 0)
                | (
                    (pts[:, 1] - a.moon_x) ** 2 + (pts[:, 0] - a.moon_y) ** 2
                    > (a.moon_radius + a.mask_guard) ** 2
                )
            )
        ]
    return pts, fallback


try:
    for idx in indices:
        if idx != last + 1:
            acc.reset()
        last = idx
        path = files[idx]
        raw = np.ascontiguousarray(
            np.rot90(np.asarray(Image.open(path), dtype=np.uint16), -1)
        )
        start = time.perf_counter()
        pre = acc.add(raw, saturation_level=4095, fingerprint=("fixed", raw.shape))
        pre_ms = (time.perf_counter() - start) * 1000
        if not a.no_save_pre:
            np.save(a.output / (path.stem + "_pre.npy"), pre.frame)
        frames.append(
            {
                "file": path.name,
                "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "preprocess_ms": pre_ms,
                "diagnostics": asdict(pre.diagnostics),
            }
        )
        for source, frame in [("raw", raw), ("pre", pre.frame)]:
            if source not in a.sources.split(","):
                continue
            if source == "pre" and pre.diagnostics.frame_count < 2:
                continue
            modes = ["mf4p", "mf2", "sep", "mf4p_mask"] + (
                ["sky_tiles"] if source == "raw" else []
            )
            if a.modes:
                modes = a.modes.split(",")
            for mode in modes:
                started = time.perf_counter()
                pts, fallback = points_for(frame, mode, source == "pre")
                detect_ms = (time.perf_counter() - started) * 1000
                with tetra3.search_budget(2600):
                    sol, route, reason, solve_ms = _cascade(
                        t3,
                        np.empty((0, 2)),
                        pts,
                        frame.shape,
                        "preprocessed_" if source == "pre" else "",
                        geometry,
                    )
                row = {
                    "file": path.name,
                    "source": source,
                    "mode": mode,
                    "candidates": len(pts),
                    "city_candidates": int(np.sum(pts[:, 1] < a.city_x)),
                    "moon_candidates": int(
                        np.sum(
                            (pts[:, 1] - a.moon_x) ** 2 + (pts[:, 0] - a.moon_y) ** 2
                            < a.moon_radius**2
                        )
                    ),
                    "fallback_calls": fallback,
                    "detect_ms": detect_ms,
                    "solve_ms": solve_ms,
                    "solved": bool(sol),
                    "path": route,
                    "reason": reason,
                    "rmse": sol.get("RMSE"),
                    "prob": sol.get("Prob"),
                    "matches": sol.get("Matches"),
                    "ra": sol.get("RA"),
                    "dec": sol.get("Dec"),
                    "points": pts.tolist(),
                }
                rows.append(row)
                with (a.output / "rows.jsonl").open("a") as f:
                    f.write(json.dumps(row) + "\n")
            print(
                path.stem,
                source,
                [
                    (r["mode"], r["candidates"], r["solved"], r["reason"])
                    for r in rows
                    if r["file"] == path.name and r["source"] == source
                ],
                flush=True,
            )
finally:
    acc.close()
summary = {}
for source, mode in sorted(set((r["source"], r["mode"]) for r in rows)):
    part = [r for r in rows if (r["source"], r["mode"]) == (source, mode)]
    solved = [r for r in part if r["solved"]]
    summary[source + "_" + mode] = {
        "n": len(part),
        "solved": len(solved),
        "candidates_median": float(np.median([r["candidates"] for r in part])),
        "city_candidates_median": float(
            np.median([r["city_candidates"] for r in part])
        ),
        "fallback_calls": sum(r["fallback_calls"] for r in part),
        "reasons": dict(
            (reason, sum(r["reason"] == reason for r in part))
            for reason in set(r["reason"] for r in part)
        ),
    }
    for key in ["detect_ms", "solve_ms", "rmse", "matches"]:
        vals = [r[key] for r in part if r[key] is not None]
        summary[source + "_" + mode][key] = {
            "p50": float(np.median(vals)) if vals else None,
            "p95": float(np.percentile(vals, 95)) if vals else None,
        }
(a.output / "frames.json").write_text(json.dumps(frames, indent=2))
(a.output / "summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
