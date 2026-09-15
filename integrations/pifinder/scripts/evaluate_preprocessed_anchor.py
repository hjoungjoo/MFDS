"""Compare delayed anchor variants on measured pairs and known coordinate motion."""

import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

from PiFinder.preprocessed_anchor import (
    PreprocessedAnchor,
    SkySample,
    separation,
    vector,
)
from PiFinder.preprocess_bias import PreprocessBiasTracker


def evaluate(samples, delay, synthetic=False):
    if not samples:
        return {
            "summary": {
                "frames": 0,
                "common_frames": 0,
                "modes": {},
                "reason": "no_samples",
            },
            "rows": [],
        }
    trackers = {
        "anchor_direct": PreprocessedAnchor(alpha=1),
        "anchor_filtered": PreprocessedAnchor(alpha=0.3),
        "anchor_window": PreprocessedAnchor(alpha=0.3, window_reference=True),
    }
    bias = PreprocessBiasTracker()
    pending = []
    latest_pre = None
    rows = []
    rejected = Counter()
    for index, entry in enumerate(samples):
        now = entry["time"]
        for tracker in trackers.values():
            if entry["raw"] is not None:
                tracker.add_raw(SkySample(index, now, *entry["raw"]))
        if entry["pre"] is not None and index % 2 == 0:
            generations = {k: t.generation for k, t in trackers.items()}
            pending.append((now + delay, index, entry, generations))
        while pending and pending[0][0] <= now:
            _, source_index, source, generations = pending.pop(0)
            latest_pre = source
            if source["raw"] is not None:
                a, b = source["raw"], source["pre"]
                if not bias.update(
                    {"RA": a[0], "Dec": a[1]}, {"RA": b[0], "Dec": b[1]}
                ):
                    bias.reset()
            for name, tracker in trackers.items():
                sample = SkySample(source_index, source["time"], *source["pre"])
                accepted = tracker.add_preprocessed(
                    sample,
                    generation=generations[name],
                    window_start_s=samples[max(0, source_index - 4)]["time"],
                    now_s=now,
                )
                if not accepted:
                    rejected[name + ":" + tracker.last_reason] += 1
        estimates = {}
        if entry["raw"] is not None:
            estimates["raw"] = (*entry["raw"], now, "raw")
            corrected = bias.apply({"RA": entry["raw"][0], "Dec": entry["raw"][1]})
            estimates["existing_bias"] = (
                corrected["RA"],
                corrected["Dec"],
                now,
                "raw_bias",
            )
        if latest_pre is not None:
            estimates["preprocessed_hold"] = (
                *latest_pre["pre"],
                latest_pre["time"],
                "old_preprocessed",
            )
        for name, tracker in trackers.items():
            result = tracker.estimate(now)
            if result is not None:
                estimates[name] = (
                    result.ra,
                    result.dec,
                    result.exposure_s,
                    result.source,
                )
        for name, (ra, dec, epoch, source) in estimates.items():
            row = {
                "time": now,
                "mode": name,
                "ra": ra,
                "dec": dec,
                "age_s": now - epoch,
                "source": source,
                "phase": entry.get("phase", "measured"),
            }
            if synthetic:
                row["error_arcsec"] = separation(
                    vector(ra, dec), vector(*entry["truth"])
                )
            rows.append(row)
    modes = ["raw", "existing_bias", "preprocessed_hold", *trackers]
    # A common post-warm-up time set avoids rewarding missing/rejected outputs.
    times = [
        set(
            r["time"]
            for r in rows
            if r["mode"] == m and r["time"] >= samples[0]["time"] + 10
        )
        for m in modes
    ]
    common = set.intersection(*times)
    summary = {
        "delay_s": delay,
        "frames": len(samples),
        "common_frames": len(common),
        "rejections": dict(rejected),
        "modes": {},
    }
    for mode in modes:
        all_part = [r for r in rows if r["mode"] == mode]
        part = [r for r in all_part if r["time"] in common]
        if len(part) < 3:
            summary["modes"][mode] = {
                "available": len(all_part),
                "common_frames": len(part),
                "reason": "insufficient_common_frames_after_warmup",
            }
            continue
        t = np.array([r["time"] for r in part])
        points = np.array([vector(r["ra"], r["dec"]) for r in part])
        design = np.column_stack([np.ones(len(t)), t - t.mean()])
        residual = points - design @ np.linalg.lstsq(design, points, rcond=None)[0]
        radial = np.linalg.norm(residual, axis=1) * 180 / np.pi * 3600
        values = {
            "available": len(all_part),
            "common_frames": len(part),
            "sources": dict(Counter(r["source"] for r in all_part)),
            "age_s_p50": float(np.median([r["age_s"] for r in part])),
            "detrended_arcsec_p50": float(np.median(radial)),
            "detrended_arcsec_p95": float(np.percentile(radial, 95)),
        }
        if synthetic:
            errors = np.array([r["error_arcsec"] for r in part])
            values["truth_error_p50"] = float(np.median(errors))
            values["truth_error_p95"] = float(np.percentile(errors, 95))
            values["truth_error_max"] = float(errors.max())
            values["phase_error_p95"] = {
                phase: float(
                    np.percentile(
                        [r["error_arcsec"] for r in part if r["phase"] == phase], 95
                    )
                )
                for phase in sorted(set(r["phase"] for r in part))
            }
            # First output that reaches within 60 arcsec of the new position.
            step_rows = [
                r for r in all_part if 20 <= r["time"] < 30 and r["error_arcsec"] < 60
            ]
            values["step_response_s"] = step_rows[0]["time"] - 20 if step_rows else None
        summary["modes"][mode] = values
    return {"summary": summary, "rows": rows}


def synthetic_samples():
    rng = np.random.default_rng(921)
    times = np.arange(0, 80, 0.5)
    truth = []
    for t in times:
        shift = 8 * t + (300 if t >= 20 else 0)
        shake = 60 * np.sin(2 * np.pi * (t - 50) / 2.5) if 50 <= t < 60 else 0
        truth.append(np.array([shift + shake, 0.2 * shake]))
    samples = []
    for i, t in enumerate(times):
        # RAW carries fixed optical bias plus independent centroid noise.
        raw = truth[i] + [25, -10] + rng.normal(0, 12, 2)
        if t == 35:
            raw += [600, 0]  # Single bad RAW solution.
        # Deliberately model temporal smear during moving windows. This is a
        # coordinate stress test, not a claim to reproduce the image algorithm.
        pre = np.mean(truth[max(0, i - 4) : i + 1], axis=0) + rng.normal(0, 4, 2)

        def to_sky(p):
            return (10 + p[0] / (3600 * np.cos(np.deg2rad(20))), 20 + p[1] / 3600)

        samples.append(
            {
                "time": float(t),
                "raw": None if 65 <= t < 69 else to_sky(raw),
                "pre": to_sky(pre),
                "truth": to_sky(truth[i]),
                "phase": "step"
                if 20 <= t < 25
                else "outlier"
                if 35 <= t < 37
                else "shake"
                if 50 <= t < 60
                else "raw_loss"
                if 65 <= t < 69
                else "steady",
            }
        )
    return samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--comparison", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--delay", type=float, default=1.2)
    args = parser.parse_args()
    if args.comparison:
        report = json.loads(args.comparison.read_text())
        entries = [json.loads(line) for line in args.manifest.read_text().splitlines()]
        times = {Path(e["file"]).stem: e["elapsed_s"] for e in entries}
        by_file = {}
        for row in report["rows"]:
            if row["mode"] != "mf4p":
                continue
            by_file.setdefault(row["file"], {})[row["arm"]] = row
        samples = []
        for filename, part in sorted(by_file.items()):
            sample = {"time": times[Path(filename).stem]}
            for arm, key in [("raw", "raw"), ("preprocessed", "pre")]:
                row = part[arm]
                sample[key] = (row["ra"], row["dec"]) if row["ra"] is not None else None
            samples.append(sample)
    else:
        samples = synthetic_samples()
    result = evaluate(samples, args.delay, synthetic=not args.comparison)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
