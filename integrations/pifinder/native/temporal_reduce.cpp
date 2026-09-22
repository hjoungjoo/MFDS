// SPDX-License-Identifier: GPL-3.0-only
#include "temporal_reduce.h"
#include <cmath>
#include <cstring>
#include <limits>

#if defined(__aarch64__) && defined(__linux__) && !defined(MF_REDUCE_DISABLE_NEON)
#define MF_REDUCE_NEON 1
#include <arm_neon.h>
#include <asm/hwcap.h>
#include <sys/auxv.h>
#else
#define MF_REDUCE_NEON 0
#endif

extern "C" unsigned mf_reduce_abi_version(void) { return 1; }

extern "C" int mf_reduce_neon_available(void) {
#if MF_REDUCE_NEON
    return (getauxval(AT_HWCAP) & HWCAP_ASIMD) != 0;
#else
    return 0;
#endif
}

extern "C" int mf_reduce_neon(
    const float* const* signals, const float* const* evidence,
    const uint8_t* const* masks, size_t frames, size_t pixels, float threshold,
    float* signal_sum, float* evidence_sum, int32_t* persistence,
    uint8_t* single_mask) {
    if (!signals || !evidence || !masks || !signal_sum || !evidence_sum ||
        !persistence || !single_mask || frames == 0 || frames > 64 ||
        pixels == 0 || pixels > std::numeric_limits<size_t>::max() / sizeof(float) ||
        !std::isfinite(threshold)) return -1;
    for (size_t k = 0; k < frames; ++k) {
        if (!signals[k] || !evidence[k] || !masks[k]) return -1;
    }
    if (!mf_reduce_neon_available()) return -2;
#if MF_REDUCE_NEON
    const auto cutoff = vdupq_n_f32(threshold);
    size_t i = 0;
    // Only baseline Armv8-A FP32/ASIMD operations: supported by Pi 4 and Pi 5.
    // Keep sequential additions; reassociation/fast-math would change results.
    for (; i + 4 <= pixels; i += 4) {
        auto signal = vdupq_n_f32(0);
        auto total_evidence = vdupq_n_f32(0);
        auto count = vdupq_n_u32(0);
        uint32_t flags = 0;
        for (size_t k = 0; k < frames; ++k) {
            const auto current = vld1q_f32(evidence[k] + i);
            signal = vaddq_f32(signal, vld1q_f32(signals[k] + i));
            total_evidence = vaddq_f32(total_evidence, current);
            count = vaddq_u32(count, vshrq_n_u32(vcgeq_f32(current, cutoff), 31));
            uint32_t bits;
            std::memcpy(&bits, masks[k] + i, sizeof(bits));
            flags |= bits;
        }
        vst1q_f32(signal_sum + i, signal);
        vst1q_f32(evidence_sum + i, total_evidence);
        vst1q_s32(persistence + i, vreinterpretq_s32_u32(count));
        std::memcpy(single_mask + i, &flags, sizeof(flags));
    }
    for (; i < pixels; ++i) {
        float signal = 0, total_evidence = 0;
        int32_t count = 0;
        uint8_t flags = 0;
        for (size_t k = 0; k < frames; ++k) {
            signal += signals[k][i];
            total_evidence += evidence[k][i];
            count += evidence[k][i] >= threshold;
            flags |= masks[k][i];
        }
        signal_sum[i] = signal;
        evidence_sum[i] = total_evidence;
        persistence[i] = count;
        single_mask[i] = flags;
    }
    return 0;
#else
    return -2;
#endif
}
