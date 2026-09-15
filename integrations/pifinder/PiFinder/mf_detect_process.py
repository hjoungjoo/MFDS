# SPDX-License-Identifier: GPL-3.0-only
"""MFDS1 adapter: private memfd images and persistent standalone native workers.

Each calling thread owns its worker. Only pixels and generic detection parameters
cross the boundary; PiFinder preprocessing, filtering and solving stay here.
"""

import atexit
import fcntl
import math
import mmap
import os
from pathlib import Path
import select
import subprocess
import threading
import time
import weakref

import numpy as np

_local = threading.local()
_workers: weakref.WeakSet["NativeWorker"] = weakref.WeakSet()
MAX_BYTES = 64 * 1024 * 1024


def native_server_path():
    return Path(
        os.environ.get(
            "MF_DETECT_SERVER",
            str(Path(__file__).resolve().parents[3] / "build/mf_detect_star_server"),
        )
    )


class NativeWorker:
    def __init__(self, size, server=None, timeout=0.5):
        self.owner_pid = os.getpid()
        self.process = None
        self.memory = None
        if size <= 0 or size > MAX_BYTES or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("invalid MF worker capacity or timeout")
        self.server = str(server or native_server_path())
        self.timeout = timeout
        self.capacity = max(1024 * 1024, 1 << (size - 1).bit_length())
        self.sequence = 0
        self.buffer = bytearray()
        fd = os.memfd_create("mf-detect-image", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
        try:
            os.ftruncate(fd, self.capacity)
            fcntl.fcntl(fd, fcntl.F_ADD_SEALS, fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW)
            self.memory = mmap.mmap(fd, self.capacity)
            self.process = subprocess.Popen(
                [self.server, "--shm-fd", str(fd), "--capacity", str(self.capacity)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                bufsize=0,
                pass_fds=(fd,),
            )
            os.set_blocking(self.process.stdin.fileno(), False)
            os.set_blocking(self.process.stdout.fileno(), False)
            # Startup has a separate allowance; each detection is bounded below.
            if self._read_line(time.monotonic() + max(2.0, timeout)) != b"MFDS1 READY":
                raise RuntimeError("unsupported MF worker protocol")
            _workers.add(self)
        except BaseException:
            self.close()
            raise
        finally:
            os.close(fd)

    def _read_more(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("MF worker response timeout")
        fd = self.process.stdout.fileno()
        if not select.select([fd], [], [], remaining)[0]:
            raise TimeoutError("MF worker response timeout")
        block = os.read(fd, 65536)
        if not block:
            raise RuntimeError("MF worker closed its response pipe")
        self.buffer.extend(block)

    def _read_line(self, deadline):
        while b"\n" not in self.buffer:
            if len(self.buffer) > 512:
                raise RuntimeError("MF worker header too long")
            self._read_more(deadline)
        end = self.buffer.index(b"\n")
        if end > 512:
            raise RuntimeError("MF worker header too long")
        line = bytes(self.buffer[:end])
        del self.buffer[: end + 1]
        return line

    def detect(self, image, saturation, binning, sigma, mode, capacity=128):
        if self.owner_pid != os.getpid():
            raise RuntimeError("MF worker belongs to another process")
        if image.dtype != np.uint16 or image.ndim != 2 or not image.flags.c_contiguous:
            raise ValueError("MF worker requires contiguous uint16 image")
        if image.nbytes > self.capacity or image.size == 0:
            raise ValueError("image exceeds MF shared memory capacity")
        if not 1 <= capacity <= 4096:
            raise ValueError("invalid MF output capacity")
        try:
            if self.process is None or self.process.poll() is not None:
                raise RuntimeError("MF worker is not running")
            deadline = time.monotonic() + self.timeout
            np.ndarray(image.shape, dtype=np.uint16, buffer=self.memory)[:] = image
            self.sequence += 1
            stamp = time.monotonic_ns()
            request = (
                f"MFDS1 {self.sequence} {stamp} {image.shape[1]} {image.shape[0]} "
                f"{saturation} {binning} {sigma:.9g} {mode} {capacity}\n"
            ).encode("ascii")
            while request:
                remaining = deadline - time.monotonic()
                fd = self.process.stdin.fileno()
                if remaining <= 0 or not select.select([], [fd], [], remaining)[1]:
                    raise TimeoutError("MF worker request timeout")
                request = request[os.write(fd, request) :]
            parts = self._read_line(deadline).split()
            if len(parts) != 6 or parts[0] != b"MFDS1":
                raise RuntimeError("malformed MF worker response")
            _, sequence, echoed_stamp, status, count, elapsed = parts
            sequence, echoed_stamp, status, count = map(
                int, (sequence, echoed_stamp, status, count)
            )
            elapsed = float(elapsed)
            if sequence != self.sequence or echoed_stamp != stamp:
                raise RuntimeError("MF worker returned a stale frame")
            if status != 0 or not 0 <= count <= capacity:
                raise RuntimeError(f"MF worker detection failed: {status}")
            if not math.isfinite(elapsed) or elapsed < 0:
                raise RuntimeError("invalid MF worker timing")
            needed = count * 3 * 4
            while len(self.buffer) < needed:
                self._read_more(deadline)
            output = np.frombuffer(bytes(self.buffer[:needed]), dtype="<f4").reshape(
                -1, 3
            )
            del self.buffer[:needed]
            if not np.isfinite(output).all():
                raise RuntimeError("invalid MF worker coordinates")
            return output, elapsed
        except (ValueError, UnicodeError) as exc:
            self.close()
            raise RuntimeError("malformed MF worker data") from exc
        except BaseException:
            self.close()
            raise

    def close(self):
        process, self.process = self.process, None
        if process is not None:
            # A forked child must never kill its parent's worker.
            if self.owner_pid == os.getpid():
                if process.poll() is None:
                    process.kill()
                process.wait()
            for pipe in (process.stdin, process.stdout):
                if pipe is not None:
                    pipe.close()
        if self.memory is not None:
            self.memory.close()
            self.memory = None

    def __del__(self):
        self.close()


def detect(image, saturation, binning, sigma, mode, capacity=128):
    server = str(native_server_path())
    timeout = float(os.environ.get("MF_DETECT_TIMEOUT_MS", "500")) / 1000
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("MF_DETECT_TIMEOUT_MS must be positive and finite")
    key = (os.getpid(), server, timeout)
    if getattr(_local, "failure_key", None) != key:
        _local.failure_key = key
        _local.failures = 0
        _local.retry_at = 0.0
    if time.monotonic() < _local.retry_at:
        raise RuntimeError("MF worker recovery cooldown; use fallback detection")
    worker = getattr(_local, "worker", None)
    try:
        if (
            worker is None
            or worker.owner_pid != os.getpid()
            or worker.server != server
            or worker.timeout != timeout
            or worker.capacity < image.nbytes
            or worker.process is None
            or worker.process.poll() is not None
        ):
            if worker is not None:
                worker.close()
            worker = NativeWorker(image.nbytes, server, timeout)
            _local.worker = worker
        result = worker.detect(image, saturation, binning, sigma, mode, capacity)
    except (OSError, RuntimeError):
        if worker is not None:
            worker.close()
        _local.failures = min(_local.failures + 1, 5)
        _local.retry_at = time.monotonic() + min(8.0, 0.5 * 2 ** (_local.failures - 1))
        raise
    _local.failures = 0
    _local.retry_at = 0.0
    return result


def close_workers():
    """Call after detection threads have stopped; also registered for normal exit."""
    global _local
    for worker in list(_workers):
        worker.close()
    _local = threading.local()


def _after_fork():
    global _local
    close_workers()
    _local = threading.local()


atexit.register(close_workers)
os.register_at_fork(after_in_child=_after_fork)
