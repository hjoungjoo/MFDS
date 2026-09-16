# Changelog

All notable changes to this project will be documented in this file.

## [0.3.1] - 2026-09-17

- Reduce RAW preprocessing temporary allocations with private in-place arrays,
  reusable clip/output-floor buffers and capped evidence history. Preserve
  output pixels, temporal addition order and detection thresholds; reset
  releases the new buffers. Native detector and ABI are unchanged.

## [0.3.0] - 2026-09-16

- Publish versioned Linux ARM64/x86_64 binary packages with GPL Python integration, license notices and file checksums.
- Native detector algorithm and process ABI are unchanged.

## [0.2.1] - 2026-09-16

### Changed

- Describe the native license as MFDS's own five-year MIT-future FSL policy.
- Use `LicenseRef-MFDS-FSL-1.1-MIT-5year` consistently in source notices,
  license files, documentation and checks. Operative terms and prior grants
  are unchanged; detection, preprocessing, ABI and protocol are unchanged.

## [0.2.0] - 2026-09-16

### Added

- Single-source release version from `VERSION`, native CLI/server `--version`,
  and additive C API `mfds_version()`; ABI 1 and MFDS1 protocol remain compatible.
- CI checks for release version, tags, changelog and built artifacts.
- Independent immutable `vMAJOR.MINOR.PATCH` release policy and release notes.

### Changed

- Preserve compact saturated stellar cores with measurable PSF wings while masking extended clipping and wingless hot pixels or lamp plateaus. Classify before binning and avoid duplicate peak-only rejection in the PiFinder adapter; SEP fallback uses the same compact-core policy.

- Native license uses MFDS's FSL policy with a five-year MIT future grant; retained GPL integration and legacy MIT notices are documented in LICENSING.md.
- Canonical PiFinder integration modules, comparison tools, tests and field records now live here and are consumed through a pinned submodule.

- Moved detector architecture, fast sky preprocessing, and AI research
  documents into the standalone repository under `docs/`.
- Added a document index and converted PiFinder implementation references to
  links to the separate `MF_PiFinder` repository.

## [0.1.0] - 2026-08-25

### Added

- Standalone C++20 detector core with no required third-party dependencies.
- Robust mesh background and MAD-based local noise estimation.
- Saturation and halo masking.
- Multi-scale zero-sum Gaussian/box PSF response.
- Raw-patch centroid, FWHM, eccentricity, support, and hot-pixel validation.
- PNG, PGM, and little-endian RAW16 CLI inputs with JSON/CSV output.
- Background, noise, normalized residual, response, and mask diagnostics.
- Synthetic regression tests including observable bright stars through thin
  clouds and edge stars around a saturated central light source.
