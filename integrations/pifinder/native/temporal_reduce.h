// SPDX-License-Identifier: GPL-3.0-only
#pragma once
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

unsigned mf_reduce_abi_version(void);
// True only for a Linux AArch64 build with runtime ASIMD support.
int mf_reduce_neon_available(void);
// ABI 1: 1..64 equally sized, contiguous frames. All input/output buffers are
// distinct; masks contain bool bytes. Evidence is already capped by the caller.
// Outputs preserve input-frame addition order. No FP16 arithmetic is performed.
// Returns 0 on success, -1 for invalid arguments, -2 if NEON is unavailable.
int mf_reduce_neon(const float* const* signals, const float* const* evidence,
                  const uint8_t* const* masks, size_t frames, size_t pixels,
                  float threshold, float* signal_sum, float* evidence_sum,
                  int32_t* persistence, uint8_t* single_mask);

#ifdef __cplusplus
}
#endif
