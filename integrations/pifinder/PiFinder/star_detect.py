"""MF-first detection, with SEP only when native extraction is unavailable.

The standalone shared-memory worker is the default (PIFINDER_DETECTOR=mf).
MF_DETECT_TRANSPORT=ctypes selects the former in-process path for comparison.
Default search: full-frame 4x binning followed by 2x candidate ROIs.
MF_DETECT_SEP_FALLBACK=0 allows strict native-only benchmark runs.
Both backends return full sensor (y, x). SEP ranks by flux; native defaults
to detection response (MF_DETECT_RANKING=flux restores flux ranking). Native morphology
is followed by PiFinder's geometric/saturation gates. No network listener or
camera access is needed.
"""

import ctypes
import logging
import os
from pathlib import Path
import time

import numpy as np

from PiFinder import mf_detect_process, sep_detect

_library = None
logger = logging.getLogger("Solver.StarDetect")


def native_library_path():
    """Resolve the .so beside this canonical source tree, or an explicit override."""
    return Path(
        os.environ.get(
            "MF_DETECT_LIBRARY",
            str(Path(__file__).resolve().parents[3] / "build/libmf_detect_star.so"),
        )
    )


def _native_library():
    global _library
    if _library is None:
        path = native_library_path()
        lib = ctypes.CDLL(str(path))
        if lib.mfds_abi_version() != 1:
            raise RuntimeError("unsupported mf_detect_star ABI")
        lib.mfds_detect_u16.argtypes = [
            ctypes.POINTER(ctypes.c_uint16),
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_float,
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_double),
        ]
        lib.mfds_detect_u16.restype = ctypes.c_int
        if hasattr(lib, "mfds_detect_u16_refined"):
            lib.mfds_detect_u16_refined.argtypes = lib.mfds_detect_u16.argtypes
            lib.mfds_detect_u16_refined.restype = ctypes.c_int
        for name in ("mfds_detect_u16_pyramid", "mfds_detect_u16_pyramid_full"):
            if hasattr(lib, name):
                getattr(lib, name).argtypes = lib.mfds_detect_u16.argtypes
                getattr(lib, name).restype = ctypes.c_int
        _library = lib
    return _library


def detect_stars(raw_frame, **kwargs):
    backend = os.environ.get("PIFINDER_DETECTOR", "mf")
    if backend == "sep":
        return sep_detect.detect_stars(raw_frame, **kwargs)
    if backend != "mf":
        raise ValueError(f"unknown detector: {backend}")
    started = time.perf_counter()
    primary = None
    fallback_enabled = os.environ.get("MF_DETECT_SEP_FALLBACK", "1") == "1"
    try:
        primary = _detect_native(raw_frame, **kwargs)
    except (OSError, RuntimeError, AttributeError) as exc:
        if not fallback_enabled:
            raise
        reason = f"native_error:{type(exc).__name__}"
        logger.warning("MF detection unavailable; trying SEP: %s", exc)
    else:
        if len(primary.centroids) >= 5 or not fallback_enabled:
            return primary
        reason = f"insufficient_candidates:{len(primary.centroids)}<5"
    auxiliary = sep_detect.detect_stars(raw_frame, **kwargs)
    result = auxiliary if auxiliary is not None else primary
    if result is not None:
        result.primary_candidates = len(primary.centroids) if primary is not None else 0
        result.fallback_reason = reason
        result.elapsed_ms = (time.perf_counter() - started) * 1000.0
    return result


def _detect_native(raw_frame, **kwargs):
    started = time.perf_counter()
    arr = np.ascontiguousarray(raw_frame, dtype=np.uint16)
    if arr.ndim != 2:
        raise ValueError("native detector requires a 2D RAW frame")
    mode = 1 if os.environ.get("MF_DETECT_REFINE", "0") == "1" else 0
    pyramid = os.environ.get("MF_DETECT_PYRAMID", "2")
    if pyramid == "2":
        mode = 2
    elif pyramid == "1":
        mode = 3
    elif pyramid != "0":
        raise ValueError("MF_DETECT_PYRAMID must be 0, 1 or 2")
    saturation = int(kwargs.get("saturation_level") or 65535)
    binning = int(os.environ.get("MF_DETECT_BINNING", "4"))
    sigma = float(np.float32(os.environ.get("MF_DETECT_SIGMA", "4.5")))
    transport = os.environ.get("MF_DETECT_TRANSPORT", "process")
    if transport == "process":
        output, _ = mf_detect_process.detect(arr, saturation, binning, sigma, mode)
    elif transport == "ctypes":
        output, _ = _detect_ctypes(arr, saturation, binning, sigma, mode)
    else:
        raise ValueError("MF_DETECT_TRANSPORT must be process or ctypes")
    points = output[:, :2].astype(np.float64)
    flux = output[:, 2].astype(np.float64)
    order = (
        np.arange(len(flux))
        if os.environ.get("MF_DETECT_RANKING", "response") == "response"
        else np.argsort(-flux, kind="stable")
    )
    points, flux = points[order], flux[order]
    # Reuse project-owned point-source/warm/saturation/cluster gates.
    filtered = sep_detect.filter_plain_centroids(
        points,
        arr,
        saturation_level=kwargs.get("saturation_level"),
        warm_pixel_map=kwargs.get("warm_pixel_map"),
    )
    filtered = np.asarray(filtered, dtype=np.float64).reshape(-1, 2)
    keep = np.asarray(
        [np.any(np.all(filtered == point, axis=1)) for point in points], dtype=bool
    )
    points, flux = points[keep], flux[keep]
    if kwargs.get("cloud_window_gate", False) and len(points):
        from PiFinder.mf_cloud_gate import select_clear_window_candidates
        from PiFinder.mf_star_only_preprocess import _robust_cell_background

        background = _robust_cell_background(sep_detect.bin2x2(arr), 32)
        selection = select_clear_window_candidates(
            background, (points - 0.5) / 2, enabled=True
        )
        points, flux = points[selection.keep], flux[selection.keep]
    max_stars = int(os.environ.get("MF_DETECT_MAX_STARS", kwargs.get("max_stars", 48)))
    return sep_detect.SepDetection(
        centroids=points[:max_stars],
        fluxes=flux[:max_stars],
        background_median=0.0,
        background_rms=0.0,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
        backend="mf",
        primary_candidates=len(points[:max_stars]),
    )


def _detect_ctypes(arr, saturation, binning, sigma, mode, capacity=128):
    """Explicit comparison path; never used as an automatic worker fallback."""
    output = np.empty((capacity, 3), dtype=np.float32)
    elapsed = ctypes.c_double()
    lib = _native_library()
    name = (
        "mfds_detect_u16",
        "mfds_detect_u16_refined",
        "mfds_detect_u16_pyramid",
        "mfds_detect_u16_pyramid_full",
    )[mode]
    count = getattr(lib, name)(
        arr.ctypes.data_as(ctypes.POINTER(ctypes.c_uint16)),
        arr.shape[1],
        arr.shape[0],
        arr.shape[1],
        saturation,
        binning,
        sigma,
        output.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        capacity,
        ctypes.byref(elapsed),
    )
    if count < 0:
        raise RuntimeError(f"native detector failed: {count}")
    return output[:count], elapsed.value
