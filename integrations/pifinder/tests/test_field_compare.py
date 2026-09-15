import hashlib
import importlib
import json
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def scripts(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("field_compare")


def test_cache_rejects_changed_source(tmp_path, scripts):
    raw = tmp_path / "raw"
    cache = tmp_path / "cache"
    raw.mkdir()
    cache.mkdir()
    for i in (1, 2):
        (raw / f"raw_{i}.tiff").write_bytes(b"image")
        np.save(cache / f"raw_{i}.npy", np.zeros((2, 2)))
        (cache / f"raw_{i}.json").write_text(
            json.dumps({"source_sha256": hashlib.sha256(b"image").hexdigest()})
        )
    assert len(scripts.validate_pairs(raw, cache, 2)) == 2
    (raw / "raw_1.tiff").write_bytes(b"changed")
    with pytest.raises(ValueError, match="RAW/cache mismatch"):
        scripts.validate_pairs(raw, cache, 2)


def test_target_separation_wraps_ra_and_missing_target_stays_null(tmp_path, scripts):
    row = {
        "file": "raw_1.tiff",
        "observation_after": {"target": {"ra_deg": 359.99, "dec_deg": 0}},
    }
    (tmp_path / "manifest.jsonl").write_text(json.dumps(row) + "\n")
    report = {
        "rows": [
            {"file": "raw_1.npy", "ra": 0.01, "dec": 0},
            {"file": "raw_2.npy", "ra": 0.01, "dec": 0},
        ]
    }
    scripts.attach_observations(report, tmp_path)
    assert report["rows"][0]["camera_to_selected_target_arcsec"] == pytest.approx(72)
    assert report["rows"][1]["camera_to_selected_target_arcsec"] is None


def test_short_or_failed_sequences_are_reported_not_crashed(scripts):
    evaluate = importlib.import_module("evaluate_preprocessed_anchor").evaluate
    assert evaluate([], 1.2)["summary"]["common_frames"] == 0
    samples = [{"time": float(i), "raw": None, "pre": None} for i in range(3)]
    report = evaluate(samples, 1.2)
    assert report["summary"]["common_frames"] == 0
    assert report["summary"]["modes"]["raw"]["available"] == 0


def test_collector_preserves_coordinates_and_deduplicates_pixels(
    tmp_path, scripts, monkeypatch
):
    import io
    from PIL import Image

    module = importlib.import_module("capture_detector_corpus")
    tick = [0]
    target = {"ra_deg": 123.4, "dec_deg": -20.0}
    settings = {
        "processing_enabled": True,
        "stack_enabled": False,
        "input_frame_source": "original_raw",
    }

    def urlopen(url, timeout):
        if "download" in url:
            tick[0] += 1
            out = io.BytesIO()
            Image.fromarray(np.ones((4, 4), dtype=np.uint16)).save(
                out,
                format="TIFF",
                tiffinfo={
                    270: json.dumps(
                        {"observation": {"target": target, "snapshot_unix_s": tick[0]}}
                    )
                },
            )
            return io.BytesIO(out.getvalue())
        if url.endswith("/api/observation"):
            value = {"target": target, "snapshot_unix_s": tick[0]}
        elif "raw-stack/control" in url:
            value = {"settings": settings}
        else:
            value = {}
        return io.BytesIO(json.dumps(value).encode())

    monkeypatch.setattr(module, "urlopen", urlopen)
    output = tmp_path / "corpus"
    monkeypatch.setattr(
        "sys.argv", ["capture", str(output), "--frames", "2", "--interval", "0"]
    )
    module.main()
    rows = [
        json.loads(line)
        for line in (output / "manifest.jsonl").read_text().splitlines()
    ]
    assert rows[0]["sha256"] != rows[1]["sha256"]  # timestamp embedded in TIFF
    assert rows[0]["pixel_sha256"] == rows[1]["pixel_sha256"]
    assert rows[1]["duplicate"] is True
    assert rows[1]["observation_after"]["target"] == target
    assert rows[1]["embedded_metadata"]["observation"]["target"] == target
    assert json.loads((output / "summary.json").read_text())["unique_frames"] == 1
