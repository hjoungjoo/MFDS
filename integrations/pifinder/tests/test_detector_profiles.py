import pytest

from PiFinder.detector_profiles import (
    configure_profile,
    profile_environment,
    runtime_environment,
)

pytestmark = pytest.mark.unit


def test_profile_resets_prior_arm_environment(monkeypatch):
    for key in profile_environment():
        monkeypatch.setenv(key, "stale")
    configure_profile("sep")
    configure_profile("mf4p")
    import os

    assert {
        key: os.environ[key] for key in profile_environment()
    } == profile_environment()
    assert profile_environment()["MF_DETECT_PYRAMID"] == "2"
    assert profile_environment()["MF_DETECT_SEP_FALLBACK"] == "1"


def test_invalid_profile_fails_before_switch():
    with pytest.raises(KeyError):
        profile_environment("unknown")


def test_detector_comparison_preserves_transport_and_search_overrides(monkeypatch):
    import os

    monkeypatch.setenv("MF_DETECT_TRANSPORT", "ctypes")
    monkeypatch.setenv("TETRA3_SEARCH_OPTIMIZED", "0")
    configure_profile("mf2")
    assert os.environ["MF_DETECT_TRANSPORT"] == "ctypes"
    assert os.environ["TETRA3_SEARCH_OPTIMIZED"] == "0"


def test_runtime_defaults_explicitly_restore_validated_search_and_transport(
    monkeypatch,
):
    import os

    values = runtime_environment()
    for key in values:
        monkeypatch.setenv(key, "stale")
    os.environ.update(values)
    assert os.environ["PIFINDER_TEST_PROFILE"] == "mf4p"
    assert os.environ["PIFINDER_PREPROCESS_MODE"] == "auto"
    assert os.environ["MF_DETECT_TRANSPORT"] == "process"
    assert os.environ["TETRA3_SEARCH_OPTIMIZED"] == "1"
    comparison = runtime_environment("mf2", mode="sync", transport="ctypes")
    assert comparison["MF_DETECT_BINNING"] == "2"
    assert comparison["PIFINDER_PREPROCESS_MODE"] == "sync"
    assert comparison["MF_DETECT_TRANSPORT"] == "ctypes"


@pytest.mark.parametrize("override", [{"mode": "invalid"}, {"transport": "invalid"}])
def test_invalid_runtime_options_fail_before_switch(override):
    with pytest.raises(ValueError):
        runtime_environment(**override)
