# SPDX-License-Identifier: GPL-3.0-only
"""Explicitly requested live exposure experiment; always restore camera modes.

Run with the PiFinder environment and PYTHONPATH. No service or mount commands.
All output, including observation coordinates, must remain local.
"""

import argparse
import json
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--frames", type=int, default=32)
    parser.add_argument("--url", default="http://127.0.0.1")
    args = parser.parse_args()
    if args.frames < 2:
        parser.error("At least two frames per arm required")
    args.output.mkdir(parents=True, exist_ok=False)

    def api(payload=None):
        req = Request(
            args.url + "/api/camera/controls",
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=15) as response:
            return json.load(response)

    def save(name, value):
        (args.output / name).write_text(json.dumps(value, indent=2))

    before = api()
    save("controls_before.json", before)
    exp = before["exposure"]
    gain = before["gain"]
    restore = {
        "exposure": exp["mode"]
        if exp["mode"] in ("auto", "auto_star")
        else exp["requested"],
        "gain": "profile" if gain["mode"] == "profile" else gain["requested"],
    }
    save("restore_request.json", restore)
    arms = [
        ("e025_g30", 25000, 30),
        ("e050_g30", 50000, 30),
        ("e100_g30", 100000, 30),
        ("e200_g30", 200000, 30),
        ("e400_g30", 400000, 30),
        ("e200_g15", 200000, 15),
        ("e400_g08", 400000, 8),
        ("e100_g30_repeat", 100000, 30),
    ]
    save("plan.json", {"arms": arms, "frames_per_arm": args.frames})

    def interrupt(signum, frame):
        raise KeyboardInterrupt(f"signal {signum}; restoring camera")

    signal.signal(signal.SIGTERM, interrupt)
    recorder = Path(__file__).with_name("capture_detector_corpus.py")
    try:
        for name, exposure, requested_gain in arms:
            request = {"exposure": exposure, "gain": requested_gain}
            started = time.time()
            response = api(request)
            settled = []
            last_sequence = None
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                state = api()
                actual = state["exposure"]["actual_us"]
                actual_gain = state["gain"]["actual"]
                sequence = state.get("capture_pipeline", {}).get("frame_sequence")
                match = (
                    actual is not None
                    and actual_gain is not None
                    and abs(actual / exposure - 1) < 0.05
                    and abs(actual_gain / requested_gain - 1) < 0.08
                )
                if match and sequence is not None and sequence != last_sequence:
                    settled.append(state)
                elif not match:
                    settled.clear()
                last_sequence = sequence
                if len(settled) >= 3:
                    break
                time.sleep(0.5)
            else:
                save(name + "_unsettled.json", state)
                raise RuntimeError(f"Camera did not settle for {name}")
            # Drain the live preview queue after three matching sensor observations.
            time.sleep(3)
            print(f"ARM {name}: {actual} us, gain {actual_gain}", flush=True)
            save(
                name + "_arm.json",
                {
                    "request": request,
                    "requested_unix_s": started,
                    "response": response,
                    "settled": settled,
                    "capture_start_unix_s": time.time(),
                    "metadata_binding": "API bracketing, not atomic with TIFF",
                },
            )
            subprocess.run(
                [
                    sys.executable,
                    str(recorder),
                    str(args.output / name),
                    "--frames",
                    str(args.frames),
                    "--interval",
                    "1",
                    "--url",
                    args.url,
                ],
                check=True,
                timeout=args.frames * 20 + 60,
            )
    finally:
        # A transient HTTP error must not prevent a second restoration attempt.
        restored = False
        for attempt in range(3):
            try:
                api(restore)
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    state = api()
                    save("controls_after.json", state)
                    exp_ok = state["exposure"]["requested"] == restore["exposure"]
                    gain_ok = (
                        state["gain"]["mode"] == "profile"
                        if restore["gain"] == "profile"
                        else state["gain"]["requested"] == restore["gain"]
                    )
                    if exp_ok and gain_ok:
                        restored = True
                        break
                    time.sleep(0.5)
                if restored:
                    break
            except Exception as error:
                print(f"restore attempt {attempt + 1}: {error}", flush=True)
        save(
            "restoration.json",
            {"verified": restored, "request": restore, "unix_s": time.time()},
        )
        if not restored:
            raise RuntimeError(
                "Camera restoration was NOT verified; inspect immediately"
            )
        print("Original camera modes restored and verified", flush=True)


if __name__ == "__main__":
    main()
