// SPDX-License-Identifier: GPL-3.0-only
#include "temporal_reduce.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

static void require(bool ok) {
    if (!ok) { std::fputs("temporal reduction check failed\n", stderr); std::exit(1); }
}

int main() {
    require(mf_reduce_abi_version() == 1);
    const bool available = mf_reduce_neon_available() == 1;
    size_t checked = 0;
    for (size_t pixels : {1u, 3u, 4u, 7u, 260u}) {
        for (size_t frames : {1u, 2u, 3u, 4u, 5u, 16u, 64u}) {
            std::vector<std::vector<float>> signals(frames), evidence(frames);
            std::vector<std::vector<uint8_t>> masks(frames);
            std::vector<const float*> sp(frames), ep(frames);
            std::vector<const uint8_t*> mp(frames);
            std::vector<float> expected_s(pixels, 0), expected_e(pixels, 0);
            std::vector<int32_t> expected_p(pixels, 0);
            std::vector<uint8_t> expected_m(pixels, 0);
            std::vector<float> actual_s(pixels, -1), actual_e(pixels, -1);
            std::vector<int32_t> actual_p(pixels, -1);
            std::vector<uint8_t> actual_m(pixels, 2);
            for (size_t k = 0; k < frames; ++k) {
                signals[k].resize(pixels); evidence[k].resize(pixels); masks[k].resize(pixels);
                for (size_t i = 0; i < pixels; ++i) {
                    signals[k][i] = static_cast<float>(static_cast<int>((k * 47 + i * 37) % 197) - 99) / 13.0f;
                    evidence[k][i] = (k + i) % 3 == 0 ? 2.5f : static_cast<float>((k * 7 + i * 3) % 83) / 17.0f;
                    masks[k][i] = ((k * 3 + i) % 11) == 0;
                    expected_s[i] += signals[k][i]; expected_e[i] += evidence[k][i];
                    expected_p[i] += evidence[k][i] >= 2.5f; expected_m[i] |= masks[k][i];
                }
                sp[k] = signals[k].data(); ep[k] = evidence[k].data(); mp[k] = masks[k].data();
            }
            int status = mf_reduce_neon(sp.data(), ep.data(), mp.data(), frames, pixels, 2.5f,
                actual_s.data(), actual_e.data(), actual_p.data(), actual_m.data());
            if (available) {
                require(status == 0);
                require(std::memcmp(actual_s.data(), expected_s.data(), pixels * sizeof(float)) == 0);
                require(std::memcmp(actual_e.data(), expected_e.data(), pixels * sizeof(float)) == 0);
                require(actual_p == expected_p && actual_m == expected_m);
            } else {
                require(status == -2 && actual_s[0] == -1 && actual_e[0] == -1 && actual_p[0] == -1 && actual_m[0] == 2);
            }
            // Invalid frame count and null frame pointers are rejected before output writes.
            require(mf_reduce_neon(sp.data(), ep.data(), mp.data(), 65, pixels, 2.5f,
                actual_s.data(), actual_e.data(), actual_p.data(), actual_m.data()) == -1);
            sp[0] = nullptr;
            require(mf_reduce_neon(sp.data(), ep.data(), mp.data(), frames, pixels, 2.5f,
                actual_s.data(), actual_e.data(), actual_p.data(), actual_m.data()) == -1);
            ++checked;
        }
    }
    std::printf("temporal reduction: %zu windows passed; NEON available=%d\n", checked, available);
}
