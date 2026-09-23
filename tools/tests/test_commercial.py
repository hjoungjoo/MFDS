"""Verify the actual commercial artifact, including attempted runtime overrides."""

import json
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from commercial import validate_files  # noqa: E402
from package_release import package  # noqa: E402


@pytest.fixture(scope="module")
def commercial_package(tmp_path_factory):
    output = tmp_path_factory.mktemp("commercial")
    artifact = package(TOOLS.parent, output, commercial=True)
    with tarfile.open(artifact) as tar:
        files = {
            m.name.removeprefix("MFDS/"): tar.extractfile(m).read()
            for m in tar.getmembers()
        }
    for name, data in files.items():
        path = output / "MFDS" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if name.startswith("build/"):
            path.chmod(0o755)
    return output / "MFDS", files


def test_artifact_has_only_worker_and_no_loader(commercial_package):
    root, files = commercial_package
    validate_files(files)
    assert [n for n in files if n.startswith("build/")] == [
        "build/mf_detect_star_server"
    ]
    manifest = json.loads(files["PACKAGE.json"])
    assert manifest["profile"] == "commercial-process-only"
    assert "source_dirty" in manifest
    assert not any("/tests/" in n or "/scripts/" in n for n in files)


@pytest.mark.parametrize("transport", ["ctypes", "bad-value"])
def test_native_transport_override_rejected(commercial_package, transport):
    root, _ = commercial_package
    code = """
import os, numpy as np
from PiFinder import star_detect
os.environ["MF_DETECT_LIBRARY"] = "/does/not/matter.so"
os.environ["MF_DETECT_TRANSPORT"] = TRANSPORT
try:
    star_detect.detect_stars(np.zeros((32, 32), dtype=np.uint16))
except ValueError as exc:
    assert "must be process" in str(exc)
else:
    raise AssertionError("native transport accepted")
assert not hasattr(star_detect, "_detect_ctypes")
assert not hasattr(star_detect, "_native_library")
""".replace("TRANSPORT\n", repr(transport) + "\n")
    run_package(root, code)


def run_package(root, code):
    subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            f"import sys; sys.path.insert(0, {str(TOOLS.parent.parent / 'PiFinder/python')!r}); import PiFinder; PiFinder.__path__.insert(0, {str(root / 'integrations/pifinder/PiFinder')!r})\n"
            + code,
        ],
        check=True,
        timeout=30,
    )


def test_real_worker_and_cpu_preprocess(commercial_package):
    root, _ = commercial_package
    run_package(
        root,
        """
import os, numpy as np
from PiFinder import star_detect, mf_detect_process as ipc, mf_star_only_preprocess as pre
os.environ["MF_DETECT_TRANSPORT"] = "process"
os.environ["MF_DETECT_SEP_FALLBACK"] = "0"
y, x = np.indices((128, 128))
frame = (500 + 2000 * np.exp(-((y - 60.2)**2 + (x - 65.3)**2)/8)).astype(np.uint16)
try:
    result = star_detect.detect_stars(frame)
    assert len(result.centroids) >= 1
    assert result.backend == "mf"
    assert ipc._local.worker.process.pid != os.getpid()
finally:
    ipc.close_workers()
for cls, error in [(pre._NativeGPU, pre.GPUUnavailable), (pre._NativeTemporalReduction, pre.ReductionUnavailable)]:
    try:
        cls()
    except error as exc:
        assert "excluded" in str(exc)
    else:
        raise AssertionError("native helper loaded")
acc = pre.MFStarOnlyAccumulator()
try:
    for _ in range(3):
        acc.add(frame, saturation_level=4095, fingerprint="sales")
finally:
    acc.close()
""",
    )


def test_rejects_new_loader_or_shared_library():
    with pytest.raises(ValueError):
        validate_files({"build/libextra.so": b""})
    with pytest.raises(ValueError):
        validate_files({"extra.py": b"from ctypes import CDLL\n"})
