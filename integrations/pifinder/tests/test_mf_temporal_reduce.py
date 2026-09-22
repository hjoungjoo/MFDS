# SPDX-License-Identifier: GPL-3.0-only
"""Policy tests are portable; MF_TEST_NEON=1 requires the actual native helper."""

import ctypes
import logging
import os
from unittest.mock import Mock

import numpy as np
import pytest

from PiFinder import mf_star_only_preprocess as pre


def window(shape=(3, 7), frames=5):
    rng = np.random.default_rng(47)
    signals = [rng.normal(0, 100, shape).astype(np.float32) for _ in range(frames)]
    evidence = [rng.uniform(0, 12, shape).astype(np.float32) for _ in range(frames)]
    masks = [rng.random(shape) > 0.5 for _ in range(frames)]
    evidence[0].flat[0] = 2.5  # Inclusive persistence threshold, including scalar tail.
    return signals, evidence, masks


def reference(signals, evidence, masks, config, capped):
    outputs = [
        np.zeros(signals[0].shape, dtype=dtype)
        for dtype in (np.float32, np.float32, np.int32, bool)
    ]
    for s, e, m in zip(signals, evidence, masks):
        outputs[0] += s
        outputs[1] += e if capped else np.clip(e, 0, config.evidence_cap_sigma)
        outputs[2] += e >= config.weak_evidence_sigma
        outputs[3] |= m
    return outputs


def run(backend, arrays, config=pre.MFStarOnlyConfig(), capped=True):
    actual = backend(*arrays, config, np.empty_like(arrays[0][0]), capped)
    for expected, result in zip(reference(*arrays, config, capped), actual):
        # Byte equality catches rounding/order differences and signed zero changes.
        assert expected.dtype == result.dtype
        assert expected.tobytes() == result.tobytes()


def test_environment_and_numpy_override(monkeypatch):
    monkeypatch.delenv("MF_PREPROCESS_REDUCTION", raising=False)
    assert pre.TemporalReductionBackend(None).mode == "auto"
    monkeypatch.setenv("MF_PREPROCESS_REDUCTION", "typo")
    with pytest.raises(ValueError, match="auto, numpy or neon"):
        pre.MFStarOnlyAccumulator()
    monkeypatch.setattr(pre, "_NativeTemporalReduction", lambda: pytest.fail("loaded"))
    run(pre.TemporalReductionBackend("numpy"), window())
    monkeypatch.setenv("MF_PREPROCESS_REDUCTION", "numpy")
    acc = pre.MFStarOnlyAccumulator()
    try:
        assert acc.reduction_backend.active_backend == "numpy"
    finally:
        acc.close()


@pytest.mark.parametrize("failure", [OSError("missing library"), AttributeError("ABI")])
def test_auto_load_failure_once_and_strict_error(monkeypatch, caplog, failure):
    factory = Mock(side_effect=failure)
    monkeypatch.setattr(pre, "_NativeTemporalReduction", factory)
    backend = pre.TemporalReductionBackend("auto")
    with caplog.at_level(logging.INFO, logger=pre.__name__):
        run(backend, window())
        run(backend, window())
    assert factory.call_count == 1
    assert backend.active_backend == "numpy"
    assert backend.fallback_reason == str(failure)
    assert len(caplog.records) == 1
    with pytest.raises(pre.ReductionUnavailable):
        run(pre.TemporalReductionBackend("neon"), window())


def test_execution_failure_falls_back(monkeypatch):
    native = Mock()
    native.reduce.side_effect = pre.ReductionUnavailable("dispatch failure")
    monkeypatch.setattr(pre, "_NativeTemporalReduction", lambda: native)
    backend = pre.TemporalReductionBackend("auto")
    run(backend, window())
    run(backend, window())
    assert native.reduce.call_count == 1
    assert backend._native is None
    assert backend.fallback_reason == "dispatch failure"


@pytest.mark.parametrize(
    "machine,bits,system",
    [
        ("armv7l", 4, "Linux"),
        ("aarch64", 4, "Linux"),
        ("x86_64", 8, "Linux"),
        ("arm64", 8, "Darwin"),
    ],
)
def test_unsupported_host_never_loads_library(monkeypatch, machine, bits, system):
    monkeypatch.setattr(pre.platform, "machine", lambda: machine)
    monkeypatch.setattr(pre.platform, "system", lambda: system)
    monkeypatch.setattr(pre.ctypes, "sizeof", lambda _: bits)
    monkeypatch.setattr(
        pre.ctypes, "CDLL", lambda _: pytest.fail("foreign code loaded")
    )
    with pytest.raises(pre.ReductionUnavailable, match="64-bit ARM Linux"):
        pre._NativeTemporalReduction()


@pytest.mark.parametrize(
    "abi,available,accepted", [(1, 1, True), (2, 1, False), (1, 0, False)]
)
def test_abi_and_runtime_capability_check(monkeypatch, abi, available, accepted):
    monkeypatch.setattr(pre.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(pre.platform, "system", lambda: "Linux")
    monkeypatch.setattr(pre.ctypes, "sizeof", lambda _: 8)
    lib = Mock()
    lib.mf_reduce_abi_version.return_value = abi
    lib.mf_reduce_neon_available.return_value = available
    monkeypatch.setattr(pre.ctypes, "CDLL", lambda _: lib)
    if accepted:
        assert pre._NativeTemporalReduction().library is lib
    else:
        with pytest.raises(pre.ReductionUnavailable):
            pre._NativeTemporalReduction()
        lib.mf_reduce_neon.assert_not_called()


@pytest.mark.parametrize("threshold,cap", [(3, 2), (0, 12), (-1, 12)])
def test_uncapped_config_uses_reference(monkeypatch, threshold, cap):
    monkeypatch.setattr(pre, "_NativeTemporalReduction", lambda: pytest.fail("loaded"))
    cfg = pre.MFStarOnlyConfig(weak_evidence_sigma=threshold, evidence_cap_sigma=cap)
    backend = pre.TemporalReductionBackend("auto")
    run(backend, window(), cfg, capped=False)
    assert backend.active_backend == "numpy"
    with pytest.raises(pre.ReductionUnavailable, match="per-frame clipping"):
        run(pre.TemporalReductionBackend("neon"), window(), cfg, capped=False)


neon = pytest.mark.skipif(
    os.environ.get("MF_TEST_NEON") != "1", reason="Set MF_TEST_NEON=1"
)


@neon
@pytest.mark.parametrize("shape", [(1, 1), (1, 3), (1, 4), (3, 7), (16, 16)])
@pytest.mark.parametrize("frames", [1, 2, 3, 4, 5, 16, 64])
def test_native_exact_order_tails_threshold_and_no_mutation(shape, frames):
    arrays = window(shape, frames)
    before = [[frame.tobytes() for frame in frames] for frames in arrays]
    backend = pre.TemporalReductionBackend("neon")
    run(backend, arrays)
    assert backend.active_backend == "neon"
    assert before == [[frame.tobytes() for frame in frames] for frames in arrays]


@neon
@pytest.mark.parametrize("layout", ["slice", "float64", "unaligned", "long_window"])
def test_native_rejects_unsupported_layout_and_auto_preserves_numpy(layout):
    arrays = window(frames=65 if layout == "long_window" else 5)
    if layout == "slice":
        arrays = tuple([[a[:, ::2] for a in frames] for frames in arrays])
    elif layout == "float64":
        arrays[0][0] = arrays[0][0].astype(np.float64)
    elif layout == "unaligned":
        source = arrays[0][0]
        array = np.ndarray(
            source.shape, np.float32, bytearray(source.nbytes + 1), offset=1
        )
        array[:] = source
        arrays[0][0] = array
    backend = pre.TemporalReductionBackend("auto")
    run(backend, arrays)
    assert backend.active_backend == "numpy"
    with pytest.raises(pre.ReductionUnavailable):
        run(pre.TemporalReductionBackend("neon"), arrays)


@neon
def test_native_argument_error_preserves_outputs():
    native = pre._NativeTemporalReduction()
    data = np.zeros((1, 4), np.float32)
    pointers = (ctypes.c_void_p * 1)(data.ctypes.data)
    output = np.full(4, 123, np.float32)
    for count, pixels, threshold in [
        (0, 4, 2.5),
        (65, 4, 2.5),
        (1, 0, 2.5),
        (1, 4, float("nan")),
    ]:
        status = native.library.mf_reduce_neon(
            pointers,
            pointers,
            pointers,
            count,
            pixels,
            threshold,
            *([output.ctypes.data] * 4),
        )
        assert status == -1
        np.testing.assert_array_equal(output, np.full(4, 123, np.float32))


@neon
@pytest.mark.parametrize("temporal_frames", [1, 5, 8])
def test_full_accumulator_exact_with_resets(temporal_frames):
    rng = np.random.default_rng(39)
    cfg = dict(accelerator="cpu", temporal_frames=temporal_frames)
    base = pre.MFStarOnlyAccumulator(
        pre.MFStarOnlyConfig(**cfg, reduction_backend="numpy")
    )
    fast = pre.MFStarOnlyAccumulator(
        pre.MFStarOnlyConfig(**cfg, reduction_backend="auto")
    )
    try:
        for index in range(11):
            frame = rng.integers(0, 4096, (97, 101), dtype=np.uint16)
            a = base.add(frame, saturation_level=4095, fingerprint=index // 9)
            b = fast.add(frame, saturation_level=4095, fingerprint=index // 9)
            assert a.frame.tobytes() == b.frame.tobytes()
            assert a.evidence.tobytes() == b.evidence.tobytes()
            assert a.diagnostics == b.diagnostics
        assert fast.reduction_backend.active_backend == "neon"
    finally:
        base.close()
        fast.close()
