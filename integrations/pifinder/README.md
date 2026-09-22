# PiFinder integration — canonical sources

This directory is the single maintained source for the MF detector adapter,
RAW preprocessing, profiles, anchor experiment, SEP/cloud gates, comparison
scripts and their tests. These files retain PiFinder's GPL-3.0 terms; see
[LICENSE](LICENSE) and [SOURCE.json](SOURCE.json).

PiFinder consumes a **pinned Git submodule** at `python/mf_detect_star`.
Its existing `python/PiFinder`, `python/scripts` and `python/tests` paths use
relative symbolic links into this directory, preserving imports and test mocks.
The application-specific solver/camera/service orchestration remains in PiFinder.
These integration modules require PiFinder; the C++ detector still does not.

From a PiFinder checkout:

```bash
bash scripts/setup_mf_detect_star.sh
PYTHONPATH=python python3 -m PiFinder.detector_profiles mf4p
PYTHONPATH=python python3 python/scripts/field_compare.py --help
```

`mf_detect_process.native_server_path()` resolves the worker beside its canonical
source, including when imported through a symlink. `MF_DETECT_SERVER` explicitly
overrides it. `MF_DETECT_TRANSPORT=process` is default; `ctypes` and
`MF_DETECT_LIBRARY` retain the previous direct path for comparison. A process
failure follows the existing SEP policy, never an implicit ctypes fallback.
Each calling thread reuses a separate worker and memfd mapping. No systemd unit
or boot changes are needed. See [protocol/lifetime](../../docs/PROCESS_PROTOCOL.md).

Develop in this repository, commit/push it, then advance PiFinder's submodule
pointer to the intended commit and rebuild. Do not edit independent copies or
track floating branch heads at runtime. No service switch happens during setup.

The experimental defaults and complete field workflow are documented in
[the field guide](../../docs/test_cedar_free_20260915/FIELD_GUIDE_ko.md).

The Moon/city exposure experiment uses `scripts/capture_exposure_sweep.py`
(explicit live camera changes with restoration), `scripts/diagnose_moon_city.py`
(offline image comparison), `scripts/summarize_scene_replays.py` (quality and
continuity summaries), and `scripts/compare_scene_solve_order.py` (search order
on the same saved centroids). See the
[recording and comparison report](../../docs/test_cedar_free_20260915/MOON_LOWER_EXPOSURE_RESULTS_ko.md).
Raw images, coordinates, and device configuration stay in local data storage.

Optional Raspberry Pi V3D preprocessing is built with `make gpu` at the MFDS
root. `MF_PREPROCESS_ACCELERATOR=cpu|auto|gpu` selects the CFA-preserving DoG
backend; CPU remains the default. See [GPU setup and tests](../../docs/GPU_PREPROCESS_ko.md)
for hardware requirements, fallback policy and measured limitations.

Temporal reduction uses `MF_PREPROCESS_REDUCTION=auto|numpy|neon`, independently
of the DoG option. `make all` / `make runtime` build a baseline ARMv8-A NEON helper
for both Pi 4 and Pi 5; `auto` falls back to NumPy if unavailable. See
[CPU reduction setup and tests](../../docs/CPU_PREPROCESS_ko.md).
