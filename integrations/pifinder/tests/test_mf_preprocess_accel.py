# SPDX-License-Identifier: GPL-3.0-only
"""Policy tests always run; MF_TEST_GPU=1 requires real V3D, never skips."""

import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from PiFinder import mf_star_only_preprocess as accel
from PiFinder.mf_star_only_preprocess import (
    MFStarOnlyAccumulator,
    MFStarOnlyConfig,
    _cfa_point_response,
)


def test_default_cpu_never_loads_gpu(monkeypatch):
    monkeypatch.delenv("MF_PREPROCESS_ACCELERATOR", raising=False)
    monkeypatch.setattr(accel, "_NativeGPU", lambda: pytest.fail("CPU loaded GPU"))
    backend = accel.PointResponseBackend(None, _cfa_point_response)
    frame = np.arange(120, dtype=np.float32).reshape(10, 12)
    try:
        np.testing.assert_array_equal(backend(frame, 2), _cfa_point_response(frame, 2))
        assert backend.active_backend == "cpu"
    finally:
        backend.close()


def test_auto_falls_back_once_and_strict_gpu_raises(monkeypatch, caplog):
    calls = []

    def missing():
        calls.append(1)
        raise OSError("missing EGL")

    monkeypatch.setattr(accel, "_NativeGPU", missing)
    frame = np.ones((10, 12), np.float32)
    backend = accel.PointResponseBackend("auto", _cfa_point_response)
    try:
        for _ in range(2):
            np.testing.assert_array_equal(
                backend(frame, 2), _cfa_point_response(frame, 2)
            )
        assert len(calls) == 1
        assert backend.active_backend == "cpu"
        assert "missing EGL" in backend.fallback_reason
        assert len(caplog.records) == 1
    finally:
        backend.close()
    strict = accel.PointResponseBackend("gpu", _cfa_point_response)
    try:
        with pytest.raises(accel.GPUUnavailable, match="missing EGL"):
            strict(frame, 2)
        assert strict.active_backend == "unavailable"
    finally:
        strict.close()


def test_runtime_failure_discards_gpu_output_and_releases_context(monkeypatch):
    closed = []

    class Broken:
        renderer = "V3D test double"

        def dog(self, frame, period):
            raise accel.GPUUnavailable("readback failure")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(accel, "_NativeGPU", Broken)
    backend = accel.PointResponseBackend("auto", _cfa_point_response)
    frame = np.arange(120, dtype=np.float32).reshape(10, 12)
    try:
        np.testing.assert_array_equal(backend(frame, 2), _cfa_point_response(frame, 2))
        assert closed == [True]
        assert backend._executor is None
    finally:
        backend.close()


def test_environment_override_validation_and_lifecycle(monkeypatch):
    monkeypatch.setenv("MF_PREPROCESS_ACCELERATOR", "typo")
    with pytest.raises(ValueError, match="cpu, auto or gpu"):
        MFStarOnlyAccumulator()
    backend = accel.PointResponseBackend("cpu", _cfa_point_response)
    with pytest.raises(ValueError, match="finite"):
        backend(np.full((10, 12), np.nan), 2)
    backend._pid = -1
    # CPU and unused backends remain safe when an app constructs before fork.
    backend(np.ones((10, 12)), 2)
    backend._pid = -1
    backend._executor = object()
    with pytest.raises(RuntimeError, match="fork"):
        backend(np.ones((10, 12)), 2)
    backend._executor = None
    backend._pid = os.getpid()
    backend.close()
    backend.close()
    with pytest.raises(RuntimeError, match="closed"):
        backend(np.ones((10, 12)), 2)


gpu = pytest.mark.skipif(
    os.environ.get("MF_TEST_GPU") != "1", reason="Set MF_TEST_GPU=1 on real V3D"
)


@gpu
@pytest.mark.parametrize(
    "shape,period",
    [((1, 1), 1), ((7, 9), 3), ((97, 101), 1), ((97, 101), 2), ((1080, 1920), 2)],
)
def test_gpu_matches_scipy_reflection_cfa_and_reallocation(shape, period):
    backend = accel.PointResponseBackend("gpu", _cfa_point_response)
    rng = np.random.default_rng(44)
    try:
        for current_shape in [(16, 20), shape, (16, 20)]:
            frame = rng.uniform(0, 65535, current_shape).astype(np.float32)
            before = frame.copy()
            actual = backend(frame, period)
            np.testing.assert_allclose(
                actual, _cfa_point_response(frame, period), atol=0.025, rtol=2e-5
            )
            np.testing.assert_array_equal(frame, before)
        assert backend.active_backend == "gpu"
        assert "V3D" in backend.renderer
    finally:
        backend.close()


@gpu
def test_gpu_phase_offsets_and_edge_stars():
    frame = np.zeros((97, 101), np.float32)
    for y in range(2):
        for x in range(2):
            frame[y::2, x::2] = 1000 * (1 + y * 2 + x)
    backend = accel.PointResponseBackend("gpu", _cfa_point_response)
    try:
        assert np.max(backend(frame, 2)) < 0.002
        frame[0, 0] += 5000
        frame[-1, -1] += 5000
        np.testing.assert_allclose(
            backend(frame, 2), _cfa_point_response(frame, 2), atol=0.003, rtol=2e-5
        )
    finally:
        backend.close()


@gpu
def test_gpu_temporal_stars_hot_pixels_saturation_and_reset():
    cpu = MFStarOnlyAccumulator(MFStarOnlyConfig(accelerator="cpu"))
    gpu_acc = MFStarOnlyAccumulator(MFStarOnlyConfig(accelerator="gpu"))
    rng = np.random.default_rng(20)
    yy, xx = np.indices((128, 160))
    try:
        for index in range(8):
            raw = 500 + rng.normal(0, 3, yy.shape) + 0.3 * xx
            raw += 500 * np.exp(-((yy - 64.3) ** 2 + (xx - 80.6) ** 2) / 3)
            raw += 20 * np.exp(-((yy - 35.4) ** 2 + (xx - 50.8) ** 2) / 3)
            raw[12:28, 12:28] = 4095
            raw[100, 100] = 3000
            raw = raw.astype(np.uint16)
            a = cpu.add(raw, saturation_level=4095, fingerprint=index // 6)
            b = gpu_acc.add(raw, saturation_level=4095, fingerprint=index // 6)
            np.testing.assert_allclose(a.evidence, b.evidence, atol=0.01, rtol=0.002)
            np.testing.assert_allclose(a.frame, b.frame, atol=1, rtol=0)
            assert a.diagnostics.persistent_pixels == b.diagnostics.persistent_pixels
            assert a.diagnostics.reset_reason == b.diagnostics.reset_reason
    finally:
        cpu.close()
        gpu_acc.close()


@gpu
def test_multiple_contexts_and_caller_threads():
    a = accel.PointResponseBackend("gpu", _cfa_point_response)
    b = accel.PointResponseBackend("gpu", _cfa_point_response)
    frame = np.arange(96 * 100, dtype=np.float32).reshape(96, 100)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(backend, frame, 2) for backend in (a, b)]
            for future in futures:
                np.testing.assert_allclose(
                    future.result(),
                    _cfa_point_response(frame, 2),
                    atol=0.003,
                    rtol=2e-5,
                )
        a.close()
        # Destroying one EGL context must not terminate the other display user.
        np.testing.assert_allclose(
            b(frame, 2), _cfa_point_response(frame, 2), atol=0.003, rtol=2e-5
        )
    finally:
        a.close()
        b.close()
