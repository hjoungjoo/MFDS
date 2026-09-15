#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Cedar-FSL-1.1-MIT-5year
"""Generate the native version header and check release/build consistency."""

import argparse
import ctypes
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--header", type=Path)
    parser.add_argument("--check-build", type=Path)
    parser.add_argument("--tag")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = (root / "VERSION").read_text().strip()
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        parser.error("VERSION must contain one stable MAJOR.MINOR.PATCH version")
    if args.header:
        args.header.parent.mkdir(parents=True, exist_ok=True)
        args.header.write_text(
            "// Generated from VERSION; do not edit.\n#pragma once\n"
            f'#define MFDS_VERSION "{version}"\n'
        )
        return
    if args.tag and args.tag != f"v{version}":
        parser.error(f"tag {args.tag!r} differs from VERSION v{version}")
    if f"## [{version}] - " not in (root / "CHANGELOG.md").read_text():
        parser.error("missing version entry in CHANGELOG.md")
    if not (root / f"release_notes/v{version}.md").is_file():
        parser.error("missing versioned release notes")
    if args.check_build:
        directory = args.check_build.resolve()
        for name in ("mf_detect_star", "mf_detect_star_server"):
            actual = subprocess.check_output(
                [str(directory / name), "--version"], text=True, timeout=5
            ).strip()
            if actual != f"MFDS {version}":
                parser.error(f"{name} reports {actual!r}, expected MFDS {version}")
        library = ctypes.CDLL(str(directory / "libmf_detect_star.so"))
        library.mfds_version.restype = ctypes.c_char_p
        if library.mfds_version().decode("ascii") != version:
            parser.error("shared library version differs from VERSION")
        if library.mfds_abi_version() != 1:
            parser.error("unexpected C ABI version")
    print(f"MFDS {version}: version, changelog and release notes verified")


if __name__ == "__main__":
    main()
