# MFDS1 standalone worker protocol

`build/mf_detect_star_server --shm-fd FD --capacity BYTES` runs the detector
independently of PiFinder. Linux, little-endian uint16/IEEE float32 are required.
The worker links only MF native code and the C++/OS runtime. The existing
`build/mf_detect_star image.pgm` CLI remains available for file input.

The caller supplies a readable, mmap-capable inherited descriptor (FD >= 3),
sized to BYTES, 1..64 MiB. The worker maps it read-only and closes the descriptor.
The PiFinder adapter creates a private `memfd`, seals its size, and passes it via
`pass_fds`. No named shared-memory file, socket listener, Python resource tracker,
PiFinder object, pointer, or solver state is involved. Kernel references reclaim
the mapping after both processes exit. The worker exits on stdin EOF and requests
SIGTERM on parent death. It is a persistent child, not a per-image subprocess.

stdout first emits `MFDS1 READY\n`. stderr is reserved for diagnostics.
For each image, write width*height contiguous little-endian uint16 samples to the
mapping, then send this ASCII line on stdin (maximum 512 bytes):

```text
MFDS1 sequence monotonic_ns width height saturation binning sigma mode capacity
```

- `sequence` and `monotonic_ns` are opaque unsigned request identity values. The
  timestamp identifies the submitted request, not the camera exposure time.
- Width/height are 1..16384 and the complete image must fit in the mapping.
- Saturation is 1..65535, binning is 1/2/4/8, sigma is finite and positive.
- Mode 0: standard; 1: original-pixel refinement; 2: coarse→2x ROI;
  3: coarse→2x→1x ROI. These select the same C API algorithms as direct calls.
- Output capacity is 1..4096 stars; PiFinder requests 128 before its own gates.

The response is an ASCII header followed immediately by a binary payload:

```text
MFDS1 sequence monotonic_ns status count algorithm_ms\n
```

Payload: `count * 3` little-endian float32 values, ordered `(y, x, flux)` in full
input-image coordinates. `status=0` is success; negative status has count=0 and
no payload. The next response starts immediately after the binary payload.
Malformed request framing closes the worker; invalid detection parameters return
negative status. A caller must wait for the whole response before reusing the
mapping. Separate simultaneous clients use separate workers and mappings.

The GPL adapter checks both identity values, bounded header/count, finite output,
EOF and deadline. A failed request kills/reaps its worker before buffer reuse.
Its default request timeout is 500 ms (`MF_DETECT_TIMEOUT_MS`); startup allows
at least 2 s. It does not retry the same exposure indefinitely. The existing
PiFinder SEP policy handles failures, and the next call creates a fresh worker.
There is no automatic ctypes fallback. Forked clients discard inherited handles
without killing their parent's worker; new calls create their own workers.

## Minimal independent client (Python standard library only)

```python
import mmap
import os
import subprocess

fd = os.memfd_create("example-image", os.MFD_CLOEXEC)
os.ftruncate(fd, 128 * 128 * 2)
image = mmap.mmap(fd, 128 * 128 * 2)  # initially a zero-filled uint16 image
worker = subprocess.Popen(
    ["build/mf_detect_star_server", "--shm-fd", str(fd), "--capacity", str(len(image))],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, pass_fds=(fd,),
)
os.close(fd)
try:
    assert worker.stdout.readline() == b"MFDS1 READY\n"
    worker.stdin.write(b"MFDS1 1 1 128 128 65535 4 4.5 2 128\n")
    worker.stdin.flush()
    header = worker.stdout.readline().split()
    count = int(header[4])
    payload = worker.stdout.read(count * 12)
finally:
    worker.stdin.close()
    worker.wait()
    worker.stdout.close()
    image.close()
```

This short example assumes a trusted responsive worker. Production clients need
deadlines and validation as implemented in the adapter. The independent protocol
documents a technical boundary; it is not a GPL linking exception or legal ruling.
