"""Record existing LiveCam RAW output without changing camera or services."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import time
from urllib.request import urlopen
from urllib.error import HTTPError

from PiFinder.observation import finite

import numpy as np
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--frames", type=int, default=180)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--url", default="http://127.0.0.1")
    parser.add_argument(
        "--conditions",
        default="Conditions not supplied; consult scene.json and telemetry",
        help="Actual observing/mount conditions, saved with the corpus",
    )
    parser.add_argument(
        "--target-ra", type=float, help="Explicit selected target J2000 RA in degrees"
    )
    parser.add_argument(
        "--target-dec", type=float, help="Explicit selected target J2000 Dec in degrees"
    )
    parser.add_argument("--target-name", default="user_supplied")
    args = parser.parse_args()
    if args.frames < 1 or not 0 <= args.interval < float("inf"):
        parser.error("frames must be positive and interval finite/nonnegative")
    if (args.target_ra is None) != (args.target_dec is None):
        parser.error("target RA and Dec must be supplied together")
    if args.target_ra is not None and (
        finite(args.target_ra) is None
        or finite(args.target_dec) is None
        or not -90 <= args.target_dec <= 90
    ):
        parser.error("target coordinates must be finite, Dec in [-90, 90]")
    args.output.mkdir(parents=True, exist_ok=False)

    def get(path):
        with urlopen(args.url + path, timeout=15) as response:
            return response.read()

    def optional_json(path):
        try:
            return json.loads(get(path))
        except HTTPError as error:
            if error.code not in (404, 503):
                raise
            return {"available": False, "http_status": error.code}

    def observation():
        value = optional_json("/api/observation")
        if value.get("available") is False:
            value = {
                "snapshot_unix_s": time.time(),
                "coordinate_frame": "J2000",
                "angle_unit": "degree",
                "target": None,
                "source": "legacy_solution_api",
                "legacy_solution": optional_json("/api/solution"),
                "binding": "API_snapshot_not_atomic_with_TIFF",
            }
        if args.target_ra is not None:
            value["user_declared_target"] = {
                "ra_deg": args.target_ra % 360,
                "dec_deg": args.target_dec,
                "name": args.target_name,
                "source": "capture_command",
            }
        return value

    def state():
        return json.loads(get("/api/camera/raw-stack/control"))

    before = state()
    settings = before["settings"]
    if not settings["processing_enabled"]:
        raise RuntimeError("LiveCam RAW output is disabled; no camera settings changed")
    if settings["stack_enabled"] or settings["input_frame_source"] != "original_raw":
        raise RuntimeError("LiveCam must already expose unstacked original RAW")
    (args.output / "before.json").write_text(json.dumps(before, indent=2))
    seen = set()
    rows = []
    started = time.monotonic()
    try:
        for index in range(args.frames):
            start = time.monotonic()
            observation_before = observation()
            controls_before = json.loads(get("/api/camera/controls"))
            raw = get("/api/camera/raw-stack/download?format=tiff")
            if not raw:
                raise RuntimeError(
                    "RAW frame unavailable (empty/204 response); no camera settings changed"
                )
            with Image.open(io.BytesIO(raw)) as image:
                frame = np.asarray(image)
                description = image.tag_v2.get(270)
            embedded = json.loads(description) if description else None
            controls_after = json.loads(get("/api/camera/controls"))
            snapshot = state()
            observation_after = observation()
            solution = optional_json("/api/solution")
            suffix = f"{index + 1:03d}"
            digest = hashlib.sha256(raw).hexdigest()
            pixel_digest = hashlib.sha256(frame.tobytes()).hexdigest()
            (args.output / f"raw_{suffix}.tiff").write_bytes(raw)
            for name, payload in [
                ("controls", controls_after),
                ("status", solution),
                (
                    "observation",
                    {
                        "before": observation_before,
                        "after": observation_after,
                        "embedded": embedded,
                    },
                ),
            ]:
                (args.output / f"{name}_{suffix}.json").write_text(json.dumps(payload))
            row = {
                "file": f"raw_{suffix}.tiff",
                "sha256": digest,
                "pixel_sha256": pixel_digest,
                "duplicate": pixel_digest in seen,
                "observation_file": f"observation_{suffix}.json",
                "observation_before": observation_before,
                "observation_after": observation_after,
                "embedded_metadata": embedded,
                "wall_timestamp": time.time(),
                "elapsed_s": time.monotonic() - started,
                "shape": list(frame.shape),
                "dtype": str(frame.dtype),
                "min": int(frame.min()),
                "max": int(frame.max()),
                "p50": float(np.median(frame)),
                "controls_before": controls_before,
                "controls_after": controls_after,
                "raw_status_after": snapshot,
                "metadata_note": "API snapshots bracket download; not atomically tied to TIFF exposure",
            }
            seen.add(pixel_digest)
            rows.append(row)
            with (args.output / "manifest.jsonl").open("a") as stream:
                stream.write(json.dumps(row) + "\n")
            if (index + 1) % 15 == 0:
                print(f"captured {index + 1}, unique {len(seen)}", flush=True)
            time.sleep(max(0.0, args.interval - (time.monotonic() - start)))
    finally:
        after = state()
        (args.output / "after.json").write_text(json.dumps(after, indent=2))
        summary = {
            "frames": len(rows),
            "unique_frames": len(seen),
            "elapsed_s": time.monotonic() - started,
            "settings_unchanged": before["settings"] == after["settings"],
            "conditions": args.conditions,
            "capture": "Read-only HTTP GET; no camera controls or service writes",
        }
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
