# SPDX-License-Identifier: GPL-3.0-only
"""An interrupted recorder must hand the camera back to its original controls."""

import importlib.util
import io
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest


@pytest.mark.parametrize(
    "failure", [subprocess.TimeoutExpired("capture", 1), KeyboardInterrupt()]
)
def test_restore_after_failed_or_interrupted_capture(tmp_path, failure):
    path = Path(__file__).parents[1] / "scripts/capture_exposure_sweep.py"
    spec = importlib.util.spec_from_file_location("sweep", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    requested = {"exposure": "auto_star", "gain": "profile"}
    posts = []
    sequence = 0

    def urlopen(request, timeout):
        nonlocal sequence
        if request.data:
            requested.update(json.loads(request.data))
            posts.append(dict(requested))
        sequence += 1
        automatic = requested["exposure"] == "auto_star"
        payload = {
            "exposure": {
                "mode": "auto_star" if automatic else "manual",
                "requested": requested["exposure"],
                "actual_us": 100000 if automatic else requested["exposure"],
            },
            "gain": {
                "mode": "profile" if requested["gain"] == "profile" else "manual",
                "requested": requested["gain"],
                "actual": 29.512,
            },
            "capture_pipeline": {"frame_sequence": sequence},
        }
        return io.BytesIO(json.dumps(payload).encode())

    output = tmp_path / "capture"
    with (
        patch.object(module, "urlopen", side_effect=urlopen),
        patch.object(module.time, "sleep"),
        patch.object(module.signal, "signal"),
        patch.object(module.subprocess, "run", side_effect=failure),
        patch.object(module.sys, "argv", ["sweep", str(output), "--frames", "2"]),
        pytest.raises(type(failure)),
    ):
        module.main()
    assert posts[0] == {"exposure": 25000, "gain": 30}
    assert posts[-1] == {"exposure": "auto_star", "gain": "profile"}
    assert json.loads((output / "restoration.json").read_text())["verified"] is True
