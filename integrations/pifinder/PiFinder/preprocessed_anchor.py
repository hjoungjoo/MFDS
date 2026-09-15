"""Experimental camera-centre fusion; not connected to service publication.

An anchor keeps its original exposure epoch. New RAW motion transports that
anchor on the sphere. This does not correct image blur, Roll or target pixels.
"""

from dataclasses import dataclass
import math
from typing import Optional

import numpy as np

ARCSEC = 180.0 * 3600.0 / math.pi


def vector(ra: float, dec: float) -> np.ndarray:
    ra, dec = np.deg2rad([ra, dec])
    return np.array([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)])


def coordinates(value: np.ndarray) -> tuple[float, float]:
    value = value / np.linalg.norm(value)
    return float(np.rad2deg(np.arctan2(value[1], value[0])) % 360), float(
        np.rad2deg(np.arcsin(np.clip(value[2], -1, 1)))
    )


def separation(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.arctan2(np.linalg.norm(np.cross(a, b)), np.dot(a, b)) * ARCSEC)


def transport(anchor: np.ndarray, source: np.ndarray, target: np.ndarray) -> np.ndarray:
    cross = np.cross(source, target)
    sine = np.linalg.norm(cross)
    if sine < 1e-12:
        return anchor.copy()
    axis = cross / sine
    cosine = float(np.clip(np.dot(source, target), -1, 1))
    return (
        anchor * cosine
        + np.cross(axis, anchor) * sine
        + axis * np.dot(axis, anchor) * (1 - cosine)
    )


@dataclass(frozen=True)
class SkySample:
    frame_id: int
    exposure_s: float
    ra: float
    dec: float

    def valid(self) -> bool:
        return (
            all(math.isfinite(v) for v in (self.exposure_s, self.ra, self.dec))
            and -90 <= self.dec <= 90
        )


@dataclass(frozen=True)
class AnchorEstimate:
    ra: float
    dec: float
    exposure_s: float
    source: str
    anchor_age_s: Optional[float]
    raw_age_s: Optional[float]
    generation: int


class PreprocessedAnchor:
    def __init__(
        self,
        *,
        alpha: float = 0.3,
        stable_samples: int = 3,
        stable_arcsec: float = 60,
        shake_arcsec: float = 60,
        jump_arcsec: float = 120,
        max_anchor_age_s: float = 8,
        max_raw_age_s: float = 1.5,
        window_reference: bool = False,
    ):
        if not 0 < alpha <= 1 or stable_samples < 1:
            raise ValueError("invalid anchor configuration")
        self.alpha = alpha
        self.stable_samples = stable_samples
        self.stable_arcsec = stable_arcsec
        self.shake_arcsec = shake_arcsec
        self.jump_arcsec = jump_arcsec
        self.max_anchor_age_s = max_anchor_age_s
        self.max_raw_age_s = max_raw_age_s
        self.window_reference = window_reference
        self.generation = 0
        self.history: dict[int, tuple[SkySample, np.ndarray]] = {}
        self.anchor: Optional[SkySample] = None
        self.candidate: Optional[SkySample] = None
        self.anchor_reference: Optional[np.ndarray] = None
        self.candidate_reference: Optional[np.ndarray] = None
        self.pending_jump: Optional[SkySample] = None
        self.stable_count = 0
        self.last_anchor_epoch = -math.inf
        self.last_input_epoch = -math.inf
        self.last_reason = "warming"
        self.last_window_shake_arcsec = 0.0

    def reset(self, reason: str = "context_changed") -> None:
        self.generation += 1
        self.history.clear()
        self.anchor = self.candidate = self.pending_jump = None
        self.anchor_reference = self.candidate_reference = None
        self.stable_count = 0
        self.last_anchor_epoch = -math.inf
        self.last_reason = reason

    def add_raw(self, sample: SkySample) -> bool:
        if not sample.valid() or sample.exposure_s <= self.last_input_epoch:
            self.last_reason = "invalid_or_old_raw"
            return False
        self.last_input_epoch = sample.exposure_s
        point = vector(sample.ra, sample.dec)
        if self.history:
            previous, filtered = next(reversed(self.history.values()))
            delta = separation(vector(previous.ra, previous.dec), point)
            if delta > self.jump_arcsec:
                if (
                    self.pending_jump is None
                    or separation(
                        vector(self.pending_jump.ra, self.pending_jump.dec), point
                    )
                    > self.stable_arcsec
                ):
                    self.pending_jump = sample
                    self.last_reason = "unconfirmed_raw_jump"
                    return False
                self.reset("confirmed_motion")
                filtered = point
            else:
                self.pending_jump = None
                filtered = (1 - self.alpha) * filtered + self.alpha * point
                filtered /= np.linalg.norm(filtered)
        else:
            filtered = point
        self.history[sample.frame_id] = (sample, filtered)
        while (
            self.history
            and sample.exposure_s - next(iter(self.history.values()))[0].exposure_s > 30
        ):
            del self.history[next(iter(self.history))]
        return True

    def window_shake(self, start_s: float, end_s: float) -> float:
        values = [
            (s, f) for s, f in self.history.values() if start_s <= s.exposure_s <= end_s
        ]
        if len(values) < 3:
            return 0.0
        times = np.array([s.exposure_s for s, _ in values])
        points = np.array([vector(s.ra, s.dec) for s, _ in values])
        design = np.column_stack([np.ones(len(times)), times - times.mean()])
        residual = points - design @ np.linalg.lstsq(design, points, rcond=None)[0]
        return float(np.percentile(np.linalg.norm(residual, axis=1) * ARCSEC, 95))

    def add_preprocessed(
        self, sample: SkySample, *, generation: int, window_start_s: float, now_s: float
    ) -> bool:
        if (
            not sample.valid()
            or generation != self.generation
            or not math.isfinite(window_start_s)
            or window_start_s > sample.exposure_s
        ):
            self.last_reason = "invalid_or_old_generation"
            return False
        if (
            sample.exposure_s <= self.last_anchor_epoch
            or not 0 <= now_s - sample.exposure_s <= self.max_anchor_age_s
        ):
            self.last_reason = "old_or_expired_anchor"
            return False
        source = self.history.get(sample.frame_id)
        if source is not None and abs(source[0].exposure_s - sample.exposure_s) > 1e-6:
            self.last_reason = "frame_epoch_mismatch"
            return False
        self.last_anchor_epoch = sample.exposure_s
        self.last_window_shake_arcsec = self.window_shake(
            window_start_s, sample.exposure_s
        )
        if self.last_window_shake_arcsec > self.shake_arcsec:
            self.anchor = self.candidate = None
            self.anchor_reference = self.candidate_reference = None
            self.stable_count = 0
            self.last_reason = "shaking_window"
            return False
        # A rejected RAW jump must not be relabelled as a stable anchor without
        # an independent agreeing preprocessed sequence.
        if (
            source is not None
            and separation(
                vector(sample.ra, sample.dec), vector(source[0].ra, source[0].dec)
            )
            > 432
        ):
            self.last_reason = "raw_preprocessed_disagreement"
            self.anchor = self.candidate = None
            self.anchor_reference = self.candidate_reference = None
            self.stable_count = 0
            return False
        reference = source[1] if source is not None else None
        if self.window_reference:
            window = [
                f
                for s, f in self.history.values()
                if window_start_s <= s.exposure_s <= sample.exposure_s
            ]
            if source is not None and len(window) >= 3:
                window_mean = np.asarray(np.mean(window, axis=0), dtype=np.float64)
                reference = window_mean / np.linalg.norm(window_mean)
        agreeing = self.candidate is not None
        if self.candidate is not None:
            predicted = vector(self.candidate.ra, self.candidate.dec)
            if self.candidate_reference is not None and reference is not None:
                predicted = transport(predicted, self.candidate_reference, reference)
            agreeing = (
                separation(predicted, vector(sample.ra, sample.dec))
                <= self.stable_arcsec
            )
        self.stable_count = self.stable_count + 1 if agreeing else 1
        self.candidate = sample
        self.candidate_reference = reference
        if self.stable_count >= self.stable_samples:
            self.anchor = sample
            self.anchor_reference = reference
            self.last_reason = "preprocessed_stable"
            return True
        self.last_reason = "confirming_preprocessed"
        return False

    def estimate(self, now_s: float) -> Optional[AnchorEstimate]:
        raw = next(reversed(self.history.values())) if self.history else None
        raw_age = now_s - raw[0].exposure_s if raw else None
        raw_fresh = raw_age is not None and 0 <= raw_age <= self.max_raw_age_s
        anchor_age = now_s - self.anchor.exposure_s if self.anchor else None
        if (
            self.anchor is not None
            and anchor_age is not None
            and 0 <= anchor_age <= self.max_anchor_age_s
        ):
            point = vector(self.anchor.ra, self.anchor.dec)
            if raw_fresh and raw is not None and self.anchor_reference is not None:
                point = transport(point, self.anchor_reference, raw[1])
                epoch, mode = raw[0].exposure_s, "preprocessed_plus_raw_motion"
            else:
                epoch, mode = self.anchor.exposure_s, "preprocessed_at_original_epoch"
            ra, dec = coordinates(point)
            return AnchorEstimate(
                ra, dec, epoch, mode, anchor_age, raw_age, self.generation
            )
        if raw_fresh and raw is not None:
            sample = raw[0]
            return AnchorEstimate(
                sample.ra,
                sample.dec,
                sample.exposure_s,
                "raw",
                anchor_age,
                raw_age,
                self.generation,
            )
        return None
