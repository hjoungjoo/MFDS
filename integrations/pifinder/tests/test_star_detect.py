"""Detector contract and native ABI regressions on independently defined stars."""

import ctypes

import numpy as np
import pytest

from PiFinder import star_detect

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def strict_native_measurements(monkeypatch):
    monkeypatch.setenv("MF_DETECT_SEP_FALLBACK", "0")
    monkeypatch.setenv("MF_DETECT_BINNING", "2")
    monkeypatch.setenv("MF_DETECT_PYRAMID", "0")


def star_field():
    yy, xx = np.indices((400, 500))
    rng = np.random.default_rng(42)
    frame = 500 + 0.1 * xx + rng.normal(0, 3, xx.shape)
    stars = [(100.3, 120.7), (240.8, 310.2), (130.2, 400.5)]
    for y, x in stars:
        frame += 450 * np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / (2 * 1.4**2))
    frame[300, 100] = 4095
    return frame.astype(np.uint16), np.asarray(stars)


@pytest.mark.parametrize("backend", ["sep", "mf"])
@pytest.mark.parametrize("refine", ["0", "1"])
@pytest.mark.parametrize("ranking", ["response", "flux"])
def test_real_centroids_and_hot_pixel_rejection(monkeypatch, backend, refine, ranking):
    monkeypatch.setenv("MF_DETECT_REFINE", refine)
    monkeypatch.setenv("MF_DETECT_RANKING", ranking)
    if backend == "mf" and not star_detect.native_library_path().exists():
        pytest.skip("build native test library first")
    monkeypatch.setenv("PIFINDER_DETECTOR", backend)
    frame, truth = star_field()
    result = star_detect.detect_stars(frame, sigma=4.0, saturation_level=4095)
    for point in truth:
        assert np.linalg.norm(result.centroids - point, axis=1).min() < 0.6
    assert np.linalg.norm(result.centroids - [300, 100], axis=1).min() > 4
    if backend == "sep" or ranking == "flux":
        assert np.all(np.diff(result.fluxes) <= 0)


def test_unknown_backend_fails_explicitly(monkeypatch):
    monkeypatch.setenv("PIFINDER_DETECTOR", "invalid")
    with pytest.raises(ValueError, match="unknown detector"):
        star_detect.detect_stars(np.zeros((128, 128), dtype=np.uint16))


def test_native_abi_rejects_null_input():
    if not star_detect.native_library_path().exists():
        pytest.skip("build native test library first")
    lib = star_detect._native_library()
    data = (ctypes.c_float * 3)()
    elapsed = ctypes.c_double()
    assert (
        lib.mfds_detect_u16(None, 2, 2, 2, 4095, 2, 4.5, data, 1, ctypes.byref(elapsed))
        < 0
    )


@pytest.mark.parametrize("stage", ["2", "1"])
def test_pyramid_preserves_sensor_coordinates(monkeypatch, stage):
    if not star_detect.native_library_path().exists():
        pytest.skip("build native test library first")
    monkeypatch.setenv("PIFINDER_DETECTOR", "mf")
    monkeypatch.setenv("MF_DETECT_PYRAMID", stage)
    monkeypatch.setenv("MF_DETECT_BINNING", "4")
    frame, truth = star_field()
    result = star_detect.detect_stars(frame, saturation_level=4095)
    assert len(result.centroids) == len(truth)
    for point in truth:
        assert np.linalg.norm(result.centroids - point, axis=1).min() < 0.7


@pytest.mark.parametrize("count", [0, 4, 5, 48])
def test_default_mf_calls_sep_only_below_solver_candidate_minimum(monkeypatch, count):
    from unittest.mock import Mock

    monkeypatch.delenv("PIFINDER_DETECTOR", raising=False)
    monkeypatch.setenv("MF_DETECT_SEP_FALLBACK", "1")
    primary = star_detect.sep_detect.SepDetection(
        np.zeros((count, 2)), np.ones(count), 0, 0, 1, backend="mf"
    )
    auxiliary = star_detect.sep_detect.SepDetection(
        np.zeros((6, 2)), np.ones(6), 0, 0, 1
    )
    native = Mock(return_value=primary)
    sep = Mock(return_value=auxiliary)
    monkeypatch.setattr(star_detect, "_detect_native", native)
    monkeypatch.setattr(star_detect.sep_detect, "detect_stars", sep)
    frame = np.zeros((64, 64), dtype=np.uint16)
    result = star_detect.detect_stars(frame)
    native.assert_called_once()
    if count < 5:
        sep.assert_called_once()
        assert result.backend == "sep"
        assert result.primary_candidates == count
        assert result.fallback_reason == f"insufficient_candidates:{count}<5"
    else:
        sep.assert_not_called()
        assert result is primary


def test_native_unavailable_uses_sep_without_hiding_invalid_configuration(monkeypatch):
    from unittest.mock import Mock

    monkeypatch.setenv("PIFINDER_DETECTOR", "mf")
    monkeypatch.setenv("MF_DETECT_SEP_FALLBACK", "1")
    native = Mock(side_effect=OSError("missing library"))
    sep = Mock(return_value=None)
    monkeypatch.setattr(star_detect, "_detect_native", native)
    monkeypatch.setattr(star_detect.sep_detect, "detect_stars", sep)
    frame = np.zeros((64, 64), dtype=np.uint16)
    assert star_detect.detect_stars(frame) is None
    sep.assert_called_once()
    native.side_effect = ValueError("invalid config")
    with pytest.raises(ValueError):
        star_detect.detect_stars(frame)
    sep.assert_called_once()
