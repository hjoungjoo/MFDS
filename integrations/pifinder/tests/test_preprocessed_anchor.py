import pytest
import numpy as np

from PiFinder.preprocessed_anchor import (
    PreprocessedAnchor,
    SkySample,
    vector,
    transport,
    separation,
)

pytestmark = pytest.mark.unit


def sample(i, ra=10.0, dec=20.0):
    return SkySample(i, float(i), ra, dec)


def test_raw_until_three_stable_delayed_anchors_then_compensates_motion():
    tracker = PreprocessedAnchor(alpha=1)
    for i in range(5):
        tracker.add_raw(sample(i, ra=10.0 + i * 0.005))
    assert tracker.estimate(4).source == "raw"
    for i in range(3):
        accepted = tracker.add_preprocessed(
            sample(i, ra=10.01 + i * 0.005), generation=0, window_start_s=0, now_s=4
        )
        assert accepted == (i == 2)
    result = tracker.estimate(4)
    assert result.source == "preprocessed_plus_raw_motion"
    assert separation(vector(result.ra, result.dec), vector(10.03, 20)) < 0.01
    assert result.exposure_s == 4


def test_single_raw_outlier_does_not_move_output_and_confirmed_jump_resets_anchor():
    tracker = PreprocessedAnchor(alpha=1, stable_samples=1)
    tracker.add_raw(sample(0))
    tracker.add_preprocessed(sample(0), generation=0, window_start_s=0, now_s=0)
    assert not tracker.add_raw(sample(1, 11))
    assert tracker.estimate(1).ra == pytest.approx(10)
    assert tracker.add_raw(sample(2, 11.001))
    assert tracker.generation == 1
    assert tracker.estimate(2).source == "raw"
    assert not tracker.add_preprocessed(
        sample(1), generation=0, window_start_s=0, now_s=2
    )


def test_raw_loss_does_not_falsify_timestamp_and_anchor_expires():
    tracker = PreprocessedAnchor(stable_samples=1)
    tracker.add_raw(sample(0))
    tracker.add_preprocessed(sample(0), generation=0, window_start_s=0, now_s=0)
    result = tracker.estimate(3)
    assert result.exposure_s == 0
    assert result.source == "preprocessed_at_original_epoch"
    assert tracker.estimate(9) is None


def test_preprocessing_can_acquire_without_raw_but_cannot_claim_current_motion():
    tracker = PreprocessedAnchor()
    for i in range(3):
        tracker.add_preprocessed(sample(i), generation=0, window_start_s=0, now_s=i + 1)
    result = tracker.estimate(4)
    assert result.source == "preprocessed_at_original_epoch"
    assert result.exposure_s == 2
    assert result.raw_age_s is None


def test_matching_frame_id_does_not_allow_a_different_exposure_epoch():
    tracker = PreprocessedAnchor(stable_samples=1)
    tracker.add_raw(sample(1))
    wrong = SkySample(1, 1.5, 10, 20)
    assert not tracker.add_preprocessed(wrong, generation=0, window_start_s=0, now_s=2)
    assert tracker.last_reason == "frame_epoch_mismatch"
    assert tracker.add_preprocessed(sample(1), generation=0, window_start_s=0, now_s=2)


def test_known_uniform_temporal_average_can_use_window_motion_reference():
    tracker = PreprocessedAnchor(alpha=1, stable_samples=1, window_reference=True)
    for i in range(6):
        tracker.add_raw(sample(i, 10 + i * 0.002, 0))
    # Five equally weighted exposures 0..4 have their centroid at exposure 2.
    averaged = sample(4, 10 + 2 * 0.002, 0)
    assert tracker.add_preprocessed(averaged, generation=0, window_start_s=0, now_s=5)
    result = tracker.estimate(5)
    assert separation(vector(result.ra, result.dec), vector(10 + 5 * 0.002, 0)) < 0.001


def test_old_future_nan_and_reordered_results_are_rejected():
    tracker = PreprocessedAnchor(stable_samples=1)
    assert not tracker.add_raw(sample(0, np.nan))
    assert tracker.add_raw(sample(1))
    assert not tracker.add_raw(sample(0))
    assert not tracker.add_preprocessed(
        sample(3), generation=0, window_start_s=0, now_s=2
    )
    assert tracker.add_preprocessed(sample(1), generation=0, window_start_s=0, now_s=2)
    assert not tracker.add_preprocessed(
        sample(0), generation=0, window_start_s=0, now_s=2
    )


def test_shaking_window_is_not_a_trusted_anchor():
    tracker = PreprocessedAnchor(stable_samples=1, jump_arcsec=1000, shake_arcsec=30)
    for i, shift in enumerate([0, 60, -60, 60, -60]):
        tracker.add_raw(sample(i, 10 + shift / 3600))
    assert not tracker.add_preprocessed(
        sample(4), generation=0, window_start_s=0, now_s=4
    )
    assert tracker.last_reason == "shaking_window"


@pytest.mark.parametrize(
    "ra,dec,new_ra,new_dec", [(359.99, 20, 0.01, 20), (10, 89.99, 30, 89.99)]
)
def test_spherical_motion_handles_wrap_and_pole(ra, dec, new_ra, new_dec):
    a, b = vector(ra, dec), vector(new_ra, new_dec)
    result = transport(a, a, b)
    assert separation(result, b) < 1e-6
