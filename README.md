# MFDS — MF Detect Star

Standalone C++20 star-candidate detector for light-polluted and partially
cloudy wide-field sky images.

The detector estimates a robust local background and noise map, masks
saturated light sources, applies a zero-sum PSF filter, and validates
candidates on the input image. Raised background or noise caused by thin
clouds does not automatically invalidate a region: bright stars that remain
observable are still detected using their local SNR.

The native detector is independent of PiFinder. The core uses only the C++
standard library; libpng is an optional CLI input dependency. The standalone
worker additionally uses Linux shared memory and process APIs.

## Public source repository

MFDS is the public home of the final MF Detect Star sources, PiFinder adapters,
preprocessing tools and aggregate experiment records. It starts from the final
snapshot recorded in [PUBLICATION.json](PUBLICATION.json); private repository
history and raw observing data are not included. Existing native binaries and
ABI identifiers retain the `mf_detect_star` name for compatibility.

```bash
git clone https://github.com/hjoungjoo/MFDS.git
cd MFDS
```

Public source access does not remove the license's commercial restrictions.
See [commercial use and permission requests](COMMERCIAL_USE.md),
[license scopes](LICENSING.md), and [publication details](docs/PUBLIC_MFDS_ko.md).

## Releases

The current version is tracked in [VERSION](VERSION). See the [release procedure](docs/VERSIONING_ko.md) and [changelog](CHANGELOG.md). Native CLI/server `--version` and C API `mfds_version()` report that version. ABI and protocol versions are independent.

## Build and test

Build tools: a C++20 compiler, Make and Python 3 (version-header generation).
Python is not required by the native detector at runtime.

```bash
make -j2
make test
```

```bash
build/mf_detect_star \
  --bin 1 \
  --sigma 4.5 \
  --diag-prefix /tmp/mfds_test \
  image.png
```

See [README_ko.md](README_ko.md) for the full Korean design, input formats,
diagnostic outputs, and tuning guidance.

Architecture decisions and research are maintained in the
[docs index](docs/README.md).

## Current main defaults

The field-tested configuration is adopted on main. See the
[finalization decision](docs/MAIN_FINALIZATION_ko.md).

The validated default is full-frame 4x search followed by 2x candidate ROIs,
response ranking, up to 48 stars. C ABI version 1 and the shared library are
retained for explicit comparisons. The default PiFinder path uses the persistent
`build/mf_detect_star_server` with private memfd image memory and pipe control.
See [the independent protocol](docs/PROCESS_PROTOCOL.md).
`MF_DETECT_TRANSPORT=ctypes` selects the former direct path; `process` is default.
PiFinder preprocessing, detection adapters, paired field replay,
anchor experiments and their tests are maintained in
[integrations/pifinder](integrations/pifinder/README.md).
PiFinder consumes a pinned submodule; it does not maintain source copies.
See the [field guide](docs/test_cedar_free_20260915/FIELD_GUIDE_ko.md) for measured
accuracy, timing, fallback policy and operating-service isolation.

## License

Native detector: **MFDS Functional Source License with a five-year MIT future grant**,
`LicenseRef-MFDS-FSL-1.1-MIT-5year`. This is not standard two-year FSL-1.1-MIT.
PiFinder integration retains GPL-3.0. Previous MIT notices are preserved.
See [LICENSE](LICENSE) and [licensing scope/provenance](LICENSING.md).
Optional libpng retains its own license.

### Runtime and comparison builds

`make -j2 runtime` builds the persistent process server and copies license
notices. This is sufficient for PiFinder's default process transport.
`make -j2 all && make test` additionally builds the CLI, ctypes library and
native tests for development and recorded-image comparisons. The runtime
build does not remove previously built comparison tools.

## Binary distribution

Release assets `MFDS-VERSION-linux-aarch64.tar.gz` and `MFDS-VERSION-linux-x86_64.tar.gz` contain compiled native binaries and the GPL Python integration. Consumers install these packages without cloning or compiling MFDS. Source changes and binary builds are maintained here. See [binary release guide](docs/BINARY_RELEASES_ko.md).
