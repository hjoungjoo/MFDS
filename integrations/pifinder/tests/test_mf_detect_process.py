# SPDX-License-Identifier: GPL-3.0-only
"""Exercise the real native process boundary, isolation and fault recovery."""

from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import os
import signal
import subprocess
import sys
import threading
import time

import numpy as np
import pytest

from PiFinder import mf_detect_process as ipc, star_detect

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolated_workers(monkeypatch):
    if not ipc.native_server_path().exists():
        pytest.skip("build the standalone MF server first")
    ipc.close_workers()
    monkeypatch.setenv("PIFINDER_DETECTOR", "mf")
    monkeypatch.setenv("MF_DETECT_TRANSPORT", "process")
    monkeypatch.setenv("MF_DETECT_SEP_FALLBACK", "0")
    monkeypatch.delenv("MF_DETECT_TIMEOUT_MS", raising=False)
    yield
    ipc.close_workers()


def frame(seed=42, shape=(400, 500)):
    yy, xx = np.indices(shape)
    image = 500 + 0.1 * xx + np.random.default_rng(seed).normal(0, 3, shape)
    for y, x in [(100.3, 120.7), (240.8, 310.2), (130.2, 400.5)]:
        image += 450 * np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / (2 * 1.4**2))
    return image.astype(np.uint16)


@pytest.mark.parametrize("mode", [0, 1, 2, 3])
@pytest.mark.parametrize("binning", [1, 2, 4, 8])
def test_real_worker_exactly_matches_c_abi(mode, binning):
    image = frame()
    expected, _ = star_detect._detect_ctypes(image, 4095, binning, 4.5, mode)
    actual, elapsed = ipc.detect(image, 4095, binning, 4.5, mode)
    np.testing.assert_array_equal(actual, expected)
    assert elapsed >= 0


def test_default_never_loads_library_and_reuses_worker(monkeypatch):
    def forbidden():
        raise AssertionError("default path loaded MF in the GPL process")

    monkeypatch.delenv("MF_DETECT_TRANSPORT")
    monkeypatch.setattr(star_detect, "_native_library", forbidden)
    image = frame()
    first = star_detect.detect_stars(image)
    worker = ipc._local.worker
    pid = worker.process.pid
    second = star_detect.detect_stars(image)
    np.testing.assert_array_equal(first.centroids, second.centroids)
    assert pid != os.getpid() and worker.process.pid == pid
    assert worker.sequence == 2
    worker.close()
    assert worker.memory is None and worker.process is None


def test_parallel_threads_have_isolated_buffers_and_workers():
    images = [frame(1), frame(2)]
    expected = [star_detect._detect_ctypes(im, 4095, 4, 4.5, 2)[0] for im in images]
    barrier = threading.Barrier(2)

    def run(index):
        ipc.detect(images[index], 4095, 4, 4.5, 2)
        worker = ipc._local.worker
        barrier.wait(timeout=5)
        for _ in range(8):
            result, _ = ipc.detect(images[index], 4095, 4, 4.5, 2)
            np.testing.assert_array_equal(result, expected[index])
        return worker.process.pid

    with ThreadPoolExecutor(max_workers=2) as pool:
        pids = list(pool.map(run, range(2)))
    assert len(set(pids)) == 2


def test_resize_killed_worker_and_next_frame_restart():
    small = frame()
    ipc.detect(small, 4095, 4, 4.5, 2)
    original = ipc._local.worker.process
    large = frame(shape=(900, 1000))
    actual, _ = ipc.detect(large, 4095, 4, 4.5, 2)
    assert original.poll() is not None
    expected, _ = star_detect._detect_ctypes(large, 4095, 4, 4.5, 2)
    np.testing.assert_array_equal(actual, expected)
    killed = ipc._local.worker.process
    killed.kill()
    killed.wait()
    ipc.detect(small, 4095, 4, 4.5, 2)
    assert ipc._local.worker.process.pid != killed.pid


def test_timeout_is_bounded_cleans_up_and_recovers(monkeypatch):
    monkeypatch.setenv("MF_DETECT_TIMEOUT_MS", "50")
    image = frame()
    ipc.detect(image, 4095, 4, 4.5, 2)
    worker = ipc._local.worker
    process = worker.process
    os.kill(process.pid, signal.SIGSTOP)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        ipc.detect(image, 4095, 4, 4.5, 2)
    assert time.monotonic() - started < 1
    assert process.poll() is not None and worker.memory is None
    with pytest.raises(RuntimeError, match="cooldown"):
        ipc.detect(image, 4095, 4, 4.5, 2)
    ipc._local.retry_at = time.monotonic() - 1
    ipc.detect(image, 4095, 4, 4.5, 2)
    assert ipc._local.worker.process.pid != process.pid


def test_worker_failure_uses_sep_not_ctypes(monkeypatch, tmp_path):
    from unittest.mock import Mock

    monkeypatch.setenv("MF_DETECT_SEP_FALLBACK", "1")
    monkeypatch.setenv("MF_DETECT_SERVER", str(tmp_path / "missing"))
    library = Mock(side_effect=AssertionError("unexpected library fallback"))
    sep = Mock(return_value=None)
    monkeypatch.setattr(star_detect, "_native_library", library)
    monkeypatch.setattr(star_detect.sep_detect, "detect_stars", sep)
    assert star_detect.detect_stars(frame()) is None
    sep.assert_called_once()
    library.assert_not_called()


@pytest.mark.parametrize(
    "header", ["MFDS1 0 0 0 0 0", "WRONG 1", "MFDS1 1 1 0 99999 0"]
)
def test_bad_or_stale_response_is_rejected(tmp_path, header):
    server = tmp_path / "fake_worker"
    server.write_text(
        "#!/usr/bin/python3\nimport sys\n"
        "print('MFDS1 READY', flush=True)\n"
        "sys.stdin.readline()\n"
        f"print({header!r}, flush=True)\n"
    )
    server.chmod(0o755)
    image = frame()
    worker = ipc.NativeWorker(image.nbytes, server)
    with pytest.raises(RuntimeError):
        worker.detect(image, 4095, 4, 4.5, 2)
    assert worker.process is None and worker.memory is None


def test_native_server_rejects_invalid_requests_without_reading_outside_mapping():
    image = frame()
    for saturation, binning, sigma, mode in [
        (0, 4, 4.5, 2),
        (4095, 3, 4.5, 2),
        (4095, 4, -1, 2),
        (4095, 4, 4.5, 9),
    ]:
        worker = ipc.NativeWorker(image.nbytes)
        with pytest.raises(RuntimeError):
            worker.detect(image, saturation, binning, sigma, mode)
        assert worker.process is None


def test_native_server_rejects_image_larger_than_mapping_and_exits_on_eof():
    worker = ipc.NativeWorker(1024 * 1024)
    process = worker.process
    try:
        os.write(process.stdin.fileno(), b"MFDS1 1 2 16384 16384 4095 4 4.5 2 128\n")
        header = worker._read_line(time.monotonic() + 2).split()
        assert header[:3] == [b"MFDS1", b"1", b"2"]
        assert int(header[3]) < 0 and header[4] == b"0"
        process.stdin.close()
        assert process.wait(timeout=2) == 0
    finally:
        worker.close()


def test_abrupt_parent_death_terminates_native_worker():
    code = (
        "from PiFinder.mf_detect_process import NativeWorker\n"
        "import time\n"
        "worker = NativeWorker(1024 * 1024)\n"
        "print(worker.process.pid, flush=True)\n"
        "time.sleep(30)\n"
    )
    parent = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE)
    worker_pid = None
    try:
        import select

        assert select.select([parent.stdout], [], [], 5)[0]
        worker_pid = int(parent.stdout.readline())
        parent.kill()
        parent.wait(timeout=2)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                with open(f"/proc/{worker_pid}/stat") as handle:
                    # A zombie has already exited and released its mapping.
                    if handle.read().rsplit(")", 1)[1].split()[0] == "Z":
                        worker_pid = None
                        return
            except FileNotFoundError:
                worker_pid = None
                return
            time.sleep(0.01)
        pytest.fail("native worker survived parent death")
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=2)
        parent.stdout.close()
        if worker_pid is not None:
            try:
                os.kill(worker_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _fork_detection(connection):
    try:
        ipc.detect(frame(), 4095, 4, 4.5, 2)
        connection.send(ipc._local.worker.process.pid)
        ipc.close_workers()
    finally:
        connection.close()


def test_forked_child_cannot_reuse_or_kill_parent_worker():
    ipc.detect(frame(), 4095, 4, 4.5, 2)
    parent_worker = ipc._local.worker.process
    context = multiprocessing.get_context("fork")
    read, write = context.Pipe(duplex=False)
    child = context.Process(target=_fork_detection, args=(write,))
    child.start()
    write.close()
    try:
        assert read.poll(5)
        assert read.recv() != parent_worker.pid
        child.join(5)
        assert child.exitcode == 0 and parent_worker.poll() is None
        ipc.detect(frame(), 4095, 4, 4.5, 2)
    finally:
        if child.is_alive():
            child.kill()
            child.join()
        read.close()


def test_repeated_startup_failure_backs_off_and_success_resets(monkeypatch):
    from unittest.mock import Mock

    real_worker = ipc.NativeWorker
    constructor = Mock(side_effect=OSError("offline"))
    monkeypatch.setattr(ipc, "NativeWorker", constructor)
    image = frame()
    for _ in range(3):
        with pytest.raises((OSError, RuntimeError)):
            ipc.detect(image, 4095, 4, 4.5, 2)
    assert constructor.call_count == 1
    assert ipc._local.failures == 1
    ipc._local.retry_at = 0
    with pytest.raises(OSError):
        ipc.detect(image, 4095, 4, 4.5, 2)
    assert constructor.call_count == 2
    assert ipc._local.failures == 2
    monkeypatch.setattr(ipc, "NativeWorker", real_worker)
    ipc._local.retry_at = 0
    ipc.detect(image, 4095, 4, 4.5, 2)
    assert ipc._local.failures == 0
    assert ipc._local.retry_at == 0
