# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Changed

- Preserve compact saturated stellar cores with measurable PSF wings while masking extended clipping and wingless hot pixels or lamp plateaus. Classify before binning and avoid duplicate peak-only rejection in the PiFinder adapter; SEP fallback uses the same compact-core policy.

- Native license now follows Cedar Detect's five-year MIT-future terms; retained GPL integration and legacy MIT notices are documented in LICENSING.md.
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
