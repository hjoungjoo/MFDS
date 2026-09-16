"""MF star-preserving RAW preprocessor for wide central/full-frame solving.

The module is intentionally independent of the solver process.  It removes
large illumination structure in intensity space while accumulating weak,
point-like evidence across a short stationary burst.  No geometric resample
is performed, so output centroids remain in the input RAW coordinate system.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Hashable

import numpy as np
from scipy import ndimage


def preprocess_geometry_fingerprint(
    *,
    camera_type: str,
    pixel_format: str,
    frame_shape: tuple[int, ...],
    rotation_deg: int,
    lens_key: str = "",
    manual_focal: float | None = None,
    calibration_key: Hashable = (),
) -> tuple[Hashable, ...]:
    """Return the stable geometry identity for a temporal RAW window.

    Exposure and gain are deliberately excluded.  Every frame is normalized
    against its own local background and noise, so framewise auto-exposure
    changes do not invalidate the temporal coordinate system.  Including
    those controls here repeatedly reintroduced the initial warm-up delay.
    """

    return (
        str(camera_type),
        str(pixel_format),
        str(lens_key or ""),
        manual_focal,
        tuple(int(value) for value in frame_shape),
        int(rotation_deg),
        calibration_key,
    )


@dataclass(frozen=True)
class MFStarOnlyConfig:
    local_cell_px: int = 10
    medium_cell_px: int = 32
    coarse_cell_px: int = 96
    temporal_frames: int = 5
    saturation_fraction: float = 0.98
    extended_saturated_pixels: int = 16
    compact_saturated_max_pixels: int = 96
    compact_saturated_max_span_px: int = 16
    saturated_dilation_px: int = 6
    weak_evidence_sigma: float = 2.5
    evidence_cap_sigma: float = 12.0
    point_response_gain: float = 2.0
    minimum_soft_weight: float = 0.15
    cfa_period_px: int = 2
    minimum_psf_pixels: int = 3
    maximum_psf_pixels: int = 30
    psf_dilation_px: int = 3
    single_frame_evidence_sigma: float = 3.5
    single_frame_permission: float = 0.20
    output_pedestal_adu: int = 64
    output_dither_adu: int = 3
    # The three background scales are independent and their NumPy/SciPy
    # kernels release the GIL. One preserves the historical serial path;
    # larger values allow a pixel-identical multi-core field A/B test.
    parallel_scale_workers: int = 1


@dataclass(frozen=True)
class MFStarOnlyDiagnostics:
    frame_count: int
    hard_mask_fraction: float
    saturation_fraction: float
    background_median: float
    local_rms_median: float
    local_rms_p90: float
    evidence_pixels: int
    persistent_pixels: int
    reset_reason: str | None = None


@dataclass(frozen=True)
class MFStarOnlyResult:
    frame: np.ndarray
    evidence: np.ndarray
    diagnostics: MFStarOnlyDiagnostics


def _resize_grid(grid: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Linearly interpolate a cell grid to a frame-sized map."""

    zoom = (shape[0] / grid.shape[0], shape[1] / grid.shape[1])
    result = ndimage.zoom(grid, zoom, order=1, mode="nearest", prefilter=False)
    # scipy's rounding can differ by one pixel for unusual sensor sizes.
    if result.shape[0] < shape[0] or result.shape[1] < shape[1]:
        result = np.pad(
            result,
            (
                (0, max(0, shape[0] - result.shape[0])),
                (0, max(0, shape[1] - result.shape[1])),
            ),
            mode="edge",
        )
    return np.asarray(result[: shape[0], : shape[1]], dtype=np.float32)


def robust_cell_maps(frame: np.ndarray, cell_px: int) -> tuple[np.ndarray, np.ndarray]:
    """Return interpolated block-median background and MAD RMS maps."""

    arr = np.asarray(frame, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError("star-only preprocessing requires a 2D RAW frame")
    cell = max(2, int(cell_px))
    height, width = arr.shape
    grid_h = (height + cell - 1) // cell
    grid_w = (width + cell - 1) // cell
    padded = np.pad(
        arr,
        ((0, grid_h * cell - height), (0, grid_w * cell - width)),
        mode="reflect",
    )
    blocks = (
        padded.reshape(grid_h, cell, grid_w, cell)
        .transpose(0, 2, 1, 3)
        .reshape(grid_h, grid_w, cell * cell)
    )
    median = np.median(blocks, axis=2)
    mad = np.median(np.abs(blocks - median[:, :, None]), axis=2)
    rms = np.maximum(mad * 1.4826, 1.0)
    frame_shape = (int(arr.shape[0]), int(arr.shape[1]))
    return _resize_grid(median, frame_shape), _resize_grid(rms, frame_shape)


def _robust_cell_background(frame: np.ndarray, cell_px: int) -> np.ndarray:
    """Return only a block-median map when a noise map is not needed."""

    arr = np.asarray(frame, dtype=np.float32)
    cell = max(2, int(cell_px))
    height, width = arr.shape
    grid_h = (height + cell - 1) // cell
    grid_w = (width + cell - 1) // cell
    padded = np.pad(
        arr,
        ((0, grid_h * cell - height), (0, grid_w * cell - width)),
        mode="reflect",
    )
    blocks = (
        padded.reshape(grid_h, cell, grid_w, cell)
        .transpose(0, 2, 1, 3)
        .reshape(grid_h, grid_w, cell * cell)
    )
    median = np.median(blocks, axis=2)
    return _resize_grid(median, (int(height), int(width)))


def _cfa_cell_maps(
    frame: np.ndarray, cell_px: int, cfa_period_px: int
) -> tuple[np.ndarray, np.ndarray]:
    """Estimate background/noise without mixing Bayer colour planes."""

    period = max(1, int(cfa_period_px))
    if period == 1:
        return robust_cell_maps(frame, cell_px)
    background = np.empty(frame.shape, dtype=np.float32)
    rms = np.empty(frame.shape, dtype=np.float32)
    phase_cell = max(2, int(round(cell_px / period)))
    for row in range(period):
        for column in range(period):
            phase = frame[row::period, column::period]
            phase_background, phase_rms = robust_cell_maps(phase, phase_cell)
            background[row::period, column::period] = phase_background
            rms[row::period, column::period] = phase_rms
    return background, rms


def _cfa_background_map(
    frame: np.ndarray, cell_px: int, cfa_period_px: int
) -> np.ndarray:
    """Estimate only the Bayer-aware background for medium/coarse scales."""

    period = max(1, int(cfa_period_px))
    if period == 1:
        return _robust_cell_background(frame, cell_px)
    background = np.empty(frame.shape, dtype=np.float32)
    phase_cell = max(2, int(round(cell_px / period)))
    for row in range(period):
        for column in range(period):
            phase = frame[row::period, column::period]
            background[row::period, column::period] = _robust_cell_background(
                phase, phase_cell
            )
    return background


def _cfa_point_response(residual: np.ndarray, cfa_period_px: int) -> np.ndarray:
    """Apply the point-source filter independently to each Bayer phase."""

    period = max(1, int(cfa_period_px))
    response = np.empty(residual.shape, dtype=np.float32)
    narrow_sigma = max(0.5, 0.8 / period)
    broad_sigma = max(1.0, 2.5 / period)
    for row in range(period):
        for column in range(period):
            phase = residual[row::period, column::period]
            response[row::period, column::period] = np.maximum(
                ndimage.gaussian_filter(phase, narrow_sigma)
                - ndimage.gaussian_filter(phase, broad_sigma),
                0.0,
            )
    return response


def _point_component_mask(core: np.ndarray, config: MFStarOnlyConfig) -> np.ndarray:
    """Keep compact multi-pixel components and reject hot pixels/large texture."""

    labels, count = ndimage.label(
        np.asarray(core, dtype=bool), structure=np.ones((3, 3), dtype=np.uint8)
    )
    if count == 0:
        return np.zeros(core.shape, dtype=bool)
    sizes = np.bincount(labels.ravel())
    accepted = (sizes >= config.minimum_psf_pixels) & (
        sizes <= config.maximum_psf_pixels
    )
    accepted[0] = False
    return accepted[labels]


def _single_frame_component_mask(
    evidences: np.ndarray, config: MFStarOnlyConfig
) -> np.ndarray:
    """Keep compact evidence formed inside one frame, never across frames.

    Combining all pixels whose temporal persistence is exactly one can join
    unrelated weak noise from different exposures into a fake multi-pixel
    PSF.  Each exposure must therefore form its own compact component before
    the accepted masks are combined.
    """

    accepted = np.zeros(evidences.shape[1:], dtype=bool)
    for evidence in evidences:
        accepted |= _point_component_mask(
            evidence >= config.single_frame_evidence_sigma, config
        )
    return accepted


def _output_dither(shape: tuple[int, int], amplitude: int) -> np.ndarray:
    """Return deterministic low-level dither for zero-RMS detector safety."""

    if amplitude <= 0:
        return np.zeros(shape, dtype=np.float32)
    yy = np.arange(shape[0], dtype=np.int32)[:, None]
    xx = np.arange(shape[1], dtype=np.int32)[None, :]
    modulus = 2 * int(amplitude) + 1
    return ((xx * 17 + yy * 31) % modulus - amplitude).astype(np.float32)


def _extended_saturation_mask(
    frame: np.ndarray,
    saturation_level: float,
    config: MFStarOnlyConfig,
) -> tuple[np.ndarray, np.ndarray]:
    saturated = np.asarray(frame) >= saturation_level * config.saturation_fraction
    labels, count = ndimage.label(saturated, structure=np.ones((3, 3), dtype=np.uint8))
    if count == 0:
        return saturated, np.zeros(saturated.shape, dtype=bool)
    sizes = np.bincount(labels.ravel())
    extended_labels = np.flatnonzero(sizes >= config.extended_saturated_pixels)
    extended_labels = extended_labels[extended_labels != 0]
    # A well-focused bright star can contain tens of clipped sensor pixels.
    # Area alone therefore cannot distinguish it from an urban light.  Keep
    # compact clipped components and let the point-response plus temporal PSF
    # gates decide whether they are stellar; only spatially extended clipped
    # structures become the destructive hard mask.
    if len(extended_labels):
        objects = ndimage.find_objects(labels)
        truly_extended = []
        max_pixels = max(0, int(config.compact_saturated_max_pixels))
        max_span = max(0, int(config.compact_saturated_max_span_px))
        for label in extended_labels:
            bounds = objects[int(label) - 1]
            if bounds is None:
                continue
            height = int(bounds[0].stop - bounds[0].start)
            width = int(bounds[1].stop - bounds[1].start)
            compact = (
                int(sizes[label]) <= max_pixels
                and height <= max_span
                and width <= max_span
            )
            if not compact:
                truly_extended.append(int(label))
        extended_labels = np.asarray(truly_extended, dtype=np.int64)
    hard = np.isin(labels, extended_labels)
    if hard.any() and config.saturated_dilation_px > 0:
        hard = ndimage.binary_dilation(
            hard, iterations=int(config.saturated_dilation_px)
        )
    return saturated, hard


def preprocess_star_evidence(
    raw_frame: np.ndarray,
    *,
    saturation_level: float,
    config: MFStarOnlyConfig = MFStarOnlyConfig(),
    scale_executor: ThreadPoolExecutor | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, MFStarOnlyDiagnostics]:
    """Return signal, PSF evidence, hard mask and diagnostics for one RAW."""

    arr = np.asarray(raw_frame, dtype=np.float32)
    if arr.ndim != 2 or min(arr.shape) < config.coarse_cell_px:
        raise ValueError("invalid RAW shape for star-only preprocessing")

    if scale_executor is None:
        background_local, rms_local = _cfa_cell_maps(
            arr, config.local_cell_px, config.cfa_period_px
        )
        background_medium = _cfa_background_map(
            arr, config.medium_cell_px, config.cfa_period_px
        )
        background_coarse = _cfa_background_map(
            arr, config.coarse_cell_px, config.cfa_period_px
        )
    else:
        local_future = scale_executor.submit(
            _cfa_cell_maps,
            arr,
            config.local_cell_px,
            config.cfa_period_px,
        )
        medium_future = scale_executor.submit(
            _cfa_background_map,
            arr,
            config.medium_cell_px,
            config.cfa_period_px,
        )
        coarse_future = scale_executor.submit(
            _cfa_background_map,
            arr,
            config.coarse_cell_px,
            config.cfa_period_px,
        )
        background_local, rms_local = local_future.result()
        background_medium = medium_future.result()
        background_coarse = coarse_future.result()
    # The median of exactly three maps needs only comparisons. Avoid stacking
    # and partitioning three full sensor frames; preserve NaN propagation.
    background = np.minimum(background_local, background_medium)
    np.maximum(background_local, background_medium, out=background_local)
    np.minimum(background_local, background_coarse, out=background_local)
    np.maximum(background, background_local, out=background)
    # These maps belong to this call. Release futures too: they retain their
    # result arrays even after the local names are deleted.
    del background_local, background_medium, background_coarse
    if scale_executor is not None:
        del local_future, medium_future, coarse_future

    saturated, hard_mask = _extended_saturation_mask(
        arr, float(saturation_level), config
    )
    finite_background = background[np.isfinite(background)]
    finite_rms = rms_local[np.isfinite(rms_local)]
    if finite_background.size == 0 or finite_rms.size == 0:
        raise ValueError("non-finite star-only background model")

    # Boolean indexing above already made private copies; partition in place.
    bg20, bg90 = np.percentile(finite_background, (20.0, 90.0), overwrite_input=True)
    rms50, rms90 = np.percentile(finite_rms, (50.0, 90.0), overwrite_input=True)
    bg_load = background - bg20
    bg_load /= max(float(bg90 - bg20), 1.0)
    np.clip(bg_load, 0, 2, out=bg_load)
    noise_load = rms_local - rms50
    noise_load /= max(float(rms90 - rms50), 1.0)
    np.clip(noise_load, 0, 2, out=noise_load)
    bg_load *= 1.5
    bg_load += 1.0
    bg_load += noise_load
    np.reciprocal(bg_load, out=bg_load)
    np.clip(bg_load, config.minimum_soft_weight, 1.0, out=bg_load)
    soft_weight = bg_load
    del noise_load

    residual = arr - background
    np.maximum(residual, 0.0, out=residual)
    del background
    # Difference-of-Gaussians rejects broad cloud/halo texture while retaining
    # the camera's compact stellar PSF.  It changes strength, never geometry.
    point_response = _cfa_point_response(residual, config.cfa_period_px)
    # The DoG kernel attenuates a one-pixel-to-few-pixel PSF while also
    # reducing the white-noise variance.  Calibrate that attenuation before
    # comparing the response with the RAW-domain robust RMS.
    evidence = point_response
    evidence *= config.point_response_gain
    np.maximum(rms_local, 1.0, out=rms_local)
    evidence /= rms_local
    # ``rms_local`` already expresses the response in local SNR units.  A
    # second background/noise weight here suppressed genuine stars twice in
    # the light-polluted lower field (the 2026-09-04 frame reduced a valid
    # 5.3-sigma clipped PSF to 1.5 sigma).  Keep soft weighting on output
    # amplitude, but make temporal admission depend on local PSF SNR alone.
    residual *= soft_weight
    evidence[hard_mask] = 0.0
    residual[hard_mask] = 0.0

    diagnostics = MFStarOnlyDiagnostics(
        frame_count=1,
        hard_mask_fraction=float(np.mean(hard_mask)),
        saturation_fraction=float(np.mean(saturated)),
        background_median=float(np.median(finite_background, overwrite_input=True)),
        local_rms_median=float(np.median(finite_rms, overwrite_input=True)),
        local_rms_p90=float(rms90),
        evidence_pixels=int(np.count_nonzero(evidence >= config.weak_evidence_sigma)),
        persistent_pixels=0,
    )
    return residual, evidence, hard_mask, diagnostics


class MFStarOnlyAccumulator:
    """Fixed-memory temporal evidence accumulator with fingerprint resets."""

    def __init__(self, config: MFStarOnlyConfig = MFStarOnlyConfig()):
        self.config = config
        self._fingerprint: Hashable | None = None
        self._signals: list[np.ndarray] = []
        self._evidence: list[np.ndarray] = []
        self._single_masks: list[np.ndarray] = []
        self._scratch: np.ndarray | None = None
        self._detector_floor: np.ndarray | None = None
        self._last_diagnostics: MFStarOnlyDiagnostics | None = None
        workers = max(1, min(4, int(config.parallel_scale_workers)))
        self._scale_executor = (
            ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="star-preprocess-scale",
            )
            if workers > 1
            else None
        )

    @property
    def frame_count(self) -> int:
        return len(self._signals)

    def reset(self) -> None:
        self._signals.clear()
        self._evidence.clear()
        self._single_masks.clear()
        self._scratch = None
        self._detector_floor = None

    def add(
        self,
        raw_frame: np.ndarray,
        *,
        saturation_level: float,
        fingerprint: Hashable,
    ) -> MFStarOnlyResult:
        reset_reason = None
        if self._fingerprint is not None and fingerprint != self._fingerprint:
            self.reset()
            reset_reason = "fingerprint_changed"
        self._fingerprint = fingerprint

        if self._scratch is None or self._scratch.shape != raw_frame.shape:
            self._scratch = np.empty(raw_frame.shape, dtype=np.float32)
            self._detector_floor = float(
                self.config.output_pedestal_adu
            ) + _output_dither(tuple(raw_frame.shape), self.config.output_dither_adu)
        scratch = self._scratch

        signal, evidence, _hard_mask, diagnostics = preprocess_star_evidence(
            raw_frame,
            saturation_level=saturation_level,
            config=self.config,
            scale_executor=self._scale_executor,
        )
        # Preserve the reference float16 quantization, but promote only once
        # when a frame enters the window. This trades ~40 MiB retained memory
        # for avoiding repeated half->float conversion on every later solve.
        signal = signal.astype(np.float16).astype(np.float32)
        evidence = evidence.astype(np.float16).astype(np.float32)
        # Support depends only on this quantized evidence and frozen config.
        # Store the weighted signal in the same allocation: no extra history.
        np.divide(evidence, max(self.config.weak_evidence_sigma, 1e-6), out=scratch)
        np.clip(scratch, 0.0, 1.0, out=scratch)
        signal *= scratch
        self._signals.append(signal)
        self._evidence.append(evidence)
        # Classification depends only on this quantized frame and frozen config.
        # Keep one bool map per frame instead of relabelling the whole window.
        self._single_masks.append(
            _point_component_mask(
                self._evidence[-1] >= self.config.single_frame_evidence_sigma,
                self.config,
            )
        )
        # Admission masks and signal weights have already used the uncapped
        # evidence. When the cap is above the persistence threshold, storing
        # capped evidence preserves that comparison and avoids clipping every
        # retained frame on every later reduction (five full image passes).
        cache_capped_evidence = (
            0 < self.config.weak_evidence_sigma <= self.config.evidence_cap_sigma
        )
        if cache_capped_evidence:
            np.clip(evidence, 0.0, self.config.evidence_cap_sigma, out=evidence)
        del self._signals[: -self.config.temporal_frames]
        del self._evidence[: -self.config.temporal_frames]
        del self._single_masks[: -self.config.temporal_frames]

        # Stream the temporal reduction: do not materialize three float32
        # windows (evidence, capped evidence, support). Keep exactly the same
        # temporal addition order and each frame's component classification.
        combined_signal = np.zeros(raw_frame.shape, dtype=np.float32)
        evidence_sum = np.zeros(raw_frame.shape, dtype=np.float32)
        persistence = np.zeros(raw_frame.shape, dtype=np.int32)
        single_core = np.zeros(raw_frame.shape, dtype=bool)
        for signal_frame, evidence_frame, single_mask in zip(
            self._signals, self._evidence, self._single_masks
        ):
            evidence = evidence_frame
            combined_signal += signal_frame
            if cache_capped_evidence:
                evidence_sum += evidence
            else:
                np.clip(evidence, 0.0, self.config.evidence_cap_sigma, out=scratch)
                evidence_sum += scratch
            persistence += evidence >= self.config.weak_evidence_sigma
            single_core |= single_mask
        repeated_core = _point_component_mask(persistence >= 2, self.config)
        repeated_keep = ndimage.binary_dilation(
            repeated_core, iterations=self.config.psf_dilation_px
        )
        single_core &= ~repeated_keep
        single_keep = ndimage.binary_dilation(
            single_core, iterations=self.config.psf_dilation_px
        )
        # Repeated compact PSFs receive full permission.  A compact source
        # visible through only one cloud gap remains in the frame, but is
        # attenuated so a transient glint cannot dominate the solve.
        scratch.fill(0.0)
        scratch[single_keep] = self.config.single_frame_permission
        scratch[repeated_keep] = 1.0
        combined_signal *= scratch
        combined_signal += self._detector_floor
        np.rint(combined_signal, out=combined_signal)
        np.clip(combined_signal, 0, saturation_level, out=combined_signal)
        output = combined_signal.astype(np.uint16)

        evidence_sum /= np.sqrt(len(self._evidence))
        combined_evidence = evidence_sum
        final_diagnostics = MFStarOnlyDiagnostics(
            frame_count=len(self._evidence),
            hard_mask_fraction=diagnostics.hard_mask_fraction,
            saturation_fraction=diagnostics.saturation_fraction,
            background_median=diagnostics.background_median,
            local_rms_median=diagnostics.local_rms_median,
            local_rms_p90=diagnostics.local_rms_p90,
            evidence_pixels=int(
                np.count_nonzero(combined_evidence >= self.config.weak_evidence_sigma)
            ),
            persistent_pixels=int(np.count_nonzero(repeated_core)),
            reset_reason=reset_reason,
        )
        self._last_diagnostics = final_diagnostics
        return MFStarOnlyResult(output, combined_evidence, final_diagnostics)

    def close(self) -> None:
        if self._scale_executor is not None:
            self._scale_executor.shutdown(wait=True, cancel_futures=True)
            self._scale_executor = None
