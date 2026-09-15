"""Run repeatable, local field-data comparisons without switching services."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import PiFinder
from PiFinder.star_detect import native_library_path
from PiFinder.detector_profiles import PROFILES, profile_environment
from PiFinder.preprocessed_anchor import separation, vector


def validate_pairs(corpus, cache, limit):
    paths = sorted(cache.glob("*.npy"))[:limit]
    if len(paths) < 2:
        raise ValueError("At least two cached frames are required")
    for path in paths:
        meta = json.loads(path.with_suffix(".json").read_text())
        raw = corpus / (path.stem + ".tiff")
        if hashlib.sha256(raw.read_bytes()).hexdigest() != meta["source_sha256"]:
            raise ValueError(f"RAW/cache mismatch: {path.stem}")
    return paths


def attach_observations(report, corpus):
    manifest = corpus / "manifest.jsonl"
    entries = (
        {
            Path(row["file"]).stem: row
            for line in manifest.read_text().splitlines()
            if (row := json.loads(line))
        }
        if manifest.exists()
        else {}
    )
    for row in report["rows"]:
        source = entries.get(Path(row["file"]).stem, {})
        # Bracketed state cannot be promoted to exposure ground truth.
        observation = source.get("observation_after")
        row["observation"] = observation
        row["source_sha256"] = source.get("sha256")
        row["capture_elapsed_s"] = source.get("elapsed_s")
        row["camera_to_selected_target_arcsec"] = None
        target = (observation or {}).get("user_declared_target") or (
            observation or {}
        ).get("target")
        if target and row["ra"] is not None:
            ra, dec = target.get("ra_deg"), target.get("dec_deg")
            if ra is not None and dec is not None:
                row["camera_to_selected_target_arcsec"] = separation(
                    vector(row["ra"], row["dec"]), vector(ra, dec)
                )
    report["coordinate_note"] = (
        "Target separation is camera-centre to selected target, not absolute "
        "pointing error. Observation snapshots are not exposure-atomic. "
        "RMSE is matched-star residual in arcseconds. Missing targets stay null."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path, help="New directory; never overwrites")
    parser.add_argument("--cache", type=Path, help="Existing source-hash-checked cache")
    parser.add_argument("--lens", choices=("6mm", "manual"))
    parser.add_argument("--manual-focal", type=float)
    parser.add_argument("--frames", type=int, default=36)
    parser.add_argument("--modes", default="mf4p,mf2,sep,mf4p-pure,mf4o,mf8p")
    parser.add_argument(
        "--wide", action="store_true", help="Enable RAW cloud gate for wide field"
    )
    parser.add_argument(
        "--timing",
        action="store_true",
        help="Run real concurrent auto and anchor pipelines",
    )
    parser.add_argument("--interval", type=float, default=0.4)
    args = parser.parse_args()
    if args.frames < 3 or not 0 <= args.interval < float("inf"):
        parser.error("At least 3 frames and a finite nonnegative interval required")
    modes = args.modes.split(",")
    if "mf4p" not in modes or any(mode not in PROFILES for mode in modes):
        parser.error("Include mf4p and use named detector profiles")
    if args.cache is None and (
        args.lens is None or (args.lens == "manual" and not args.manual_focal)
    ):
        parser.error("New cache requires --lens (and --manual-focal for manual)")
    args.output.mkdir(parents=True, exist_ok=False)
    scripts = Path(__file__).resolve().parent
    environment = dict(os.environ, **profile_environment())
    app_python = Path(PiFinder.__file__).resolve().parent.parent
    environment["PYTHONPATH"] = str(app_python)
    commands = []
    provenance_files = list((app_python / "PiFinder").glob("*detect*.py")) + [
        app_python / "PiFinder/mf_star_only_preprocess.py",
        app_python / "PiFinder/preprocessed_anchor.py",
        native_library_path(),
    ]
    (args.output / "source_hashes.json").write_text(
        json.dumps(
            {
                str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                if path.exists()
                else None
                for path in provenance_files
            },
            indent=2,
        )
    )

    def run(script, *values):
        command = [sys.executable, str(scripts / script), *map(str, values)]
        commands.append(command)
        (args.output / "commands.json").write_text(json.dumps(commands, indent=2))
        with (args.output / (Path(script).stem + ".log")).open("a") as log:
            subprocess.run(
                command,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )
        print(f"completed {script}", flush=True)

    cache = args.cache or args.output / "cache"
    if args.cache is None:
        values = [
            args.corpus,
            "--lens",
            args.lens,
            "--cache-dir",
            cache,
            "--limit",
            args.frames,
            "--preprocess-workers",
            3,
            "--output",
            args.output / "cache_replay.csv",
        ]
        if args.manual_focal is not None:
            values += ["--manual-focal", args.manual_focal]
        run("replay_star_preprocess_ab.py", *values)
    paths = validate_pairs(args.corpus, cache, args.frames)
    comparison = args.output / "paired.json"
    run(
        "compare_raw_preprocessed_detectors.py",
        args.corpus,
        cache,
        comparison,
        "--modes",
        args.modes,
        "--limit",
        args.frames,
        *(["--wide"] if args.wide else []),
    )
    report = json.loads(comparison.read_text())
    attach_observations(report, args.corpus)
    comparison.write_text(json.dumps(report, indent=2))
    manifest = args.corpus / "manifest.jsonl"
    if manifest.exists():
        for delay in (1.2, 2.5):
            run(
                "evaluate_preprocessed_anchor.py",
                args.output / f"anchor_delay_{delay}.json",
                "--comparison",
                comparison,
                "--manifest",
                manifest,
                "--delay",
                delay,
            )
    if args.timing:
        for mode in ("mf4p", "mf2"):
            run(
                "benchmark_auto_detector.py",
                args.corpus,
                cache,
                args.output / f"auto_{mode}.json",
                "--mode",
                mode,
                "--frames",
                args.frames,
                "--interval",
                args.interval,
            )
        run(
            "benchmark_anchor_pipeline.py",
            args.corpus,
            cache,
            args.output / "anchor_pipeline.json",
            "--frames",
            args.frames,
            "--interval",
            args.interval,
        )
    summary = {
        "default": "mf4p + auto (same-frame sync recovery/alignment preserved)",
        "profiles": {mode: profile_environment(mode) for mode in modes},
        "paired": report["summary"],
        "source_frames": len(paths),
        "operating_service_changed": False,
        "timing_harness_excludes": ["camera IPC", "SQM", "UI", "mount"],
        "anchor_delay_evaluations": "coordinate replay with simulated completion delays",
        "anchor_pipeline": "independent real preprocessing/detection/solve worker; no service publication",
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
