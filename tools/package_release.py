#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-MFDS-FSL-1.1-MIT-5year
"""Package compiled MFDS and its GPL Python integration; never native sources."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import tarfile


def package(root, output):
    root = Path(root).resolve()
    version = (root / "VERSION").read_text().strip()
    arch = platform.machine()
    if arch not in ("aarch64", "x86_64") or platform.system() != "Linux":
        raise RuntimeError("Supported release platforms: Linux aarch64 and x86_64")
    subprocess.run(
        [
            "python3",
            str(root / "tools/version.py"),
            "--check-build",
            str(root / "build"),
        ],
        check=True,
    )
    revision = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    tracked = subprocess.check_output(
        ["git", "-C", str(root), "ls-files"], text=True
    ).splitlines()
    names = [
        n
        for n in tracked
        if n.startswith(
            ("integrations/pifinder/", "LICENSES/", "docs/test_cedar_free_20260915/")
        )
        or n
        in (
            "VERSION",
            "LICENSE",
            "LICENSING.md",
            "COMMERCIAL_USE.md",
            "docs/GPU_PREPROCESS_ko.md",
            "docs/GPU_PREPROCESS_RESULTS_20260923_ko.md",
            "docs/CPU_PREPROCESS_ko.md",
        )
    ]
    names += [
        "build/" + n
        for n in ("mf_detect_star_server", "libmf_detect_star.so", "mf_detect_star")
    ]
    # Older/minimal builds remain valid: Python falls back if helpers are absent.
    for helper in ("libmf_preprocess_gpu.so", "libmf_temporal_reduce.so"):
        if (root / "build" / helper).is_file():
            names.append("build/" + helper)
    files = {
        n: (root / n).read_bytes()
        for n in sorted(names)
        if not n.startswith("integrations/pifinder/native/")
    }
    manifest = {
        "schema": 1,
        "version": version,
        "source_commit": revision,
        "repository": "https://github.com/hjoungjoo/MFDS",
        "platform": f"linux-{arch}",
        "glibc_min": "2.36",
        "abi": 1,
        "files": {n: hashlib.sha256(b).hexdigest() for n, b in files.items()},
    }
    files["PACKAGE.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    output.mkdir(parents=True, exist_ok=True)
    artifact = output / f"MFDS-{version}-linux-{arch}.tar.gz"
    with artifact.open("wb") as raw, gzip.GzipFile(
        filename="", fileobj=raw, mode="wb", mtime=0
    ) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            for name, data in files.items():
                entry = tarfile.TarInfo("MFDS/" + name)
                entry.size = len(data)
                entry.mode = 0o755 if name.startswith("build/") else 0o644
                tar.addfile(entry, io.BytesIO(data))
    checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
    artifact.with_suffix(artifact.suffix + ".sha256").write_text(
        f"{checksum}  {artifact.name}\n"
    )
    print(artifact)
    return artifact


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()
    package(Path(__file__).resolve().parents[1], args.output)
