// SPDX-License-Identifier: LicenseRef-Cedar-FSL-1.1-MIT-5year
#include "mf_detect_star/detector.hpp"
#include "mf_detect_star/c_api.h"
#include "mfds_version.hpp"
#include <algorithm>
#include <exception>

// Version 1: caller owns all buffers; no state or exceptions cross the ABI.
extern "C" int mfds_abi_version() { return 1; }
extern "C" const char* mfds_version() { return MFDS_VERSION; }

static int detect_impl(const std::uint16_t* pixels, std::size_t width,
    std::size_t height, std::size_t stride, unsigned max_value, int binning,
    float sigma, float* yxf, std::size_t capacity, double* elapsed_ms, bool refine,
    int pyramid = 0) {
    if (!pixels || !yxf || !elapsed_ms || capacity == 0 || capacity > 4096 ||
        max_value == 0 || max_value > 65535) return -1;
    try {
        mf_detect_star::DetectorConfig config;
        config.binning = binning;
        config.refine_original = refine;
        config.mesh_size = 64;
        config.detection_sigma = sigma;
        config.noise_floor = 2.0F;
        config.max_stars = capacity;
        const mf_detect_star::Detector detector(config);
        const mf_detect_star::ImageView view{pixels, width, height, stride,
            static_cast<std::uint16_t>(max_value)};
        const auto result = pyramid ? detector.detect_pyramid(view, pyramid == 2)
                                    : detector.detect(view);
        if (!result.ok()) return -2;
        *elapsed_ms = result.elapsed_ms;
        for (std::size_t i = 0; i < result.stars.size(); ++i) {
            yxf[3*i] = result.stars[i].y;
            yxf[3*i+1] = result.stars[i].x;
            yxf[3*i+2] = result.stars[i].flux;
        }
        return static_cast<int>(result.stars.size());
    } catch (const std::exception&) {
        return -3;
    }
}

extern "C" int mfds_detect_u16(const std::uint16_t* pixels, std::size_t width,
    std::size_t height, std::size_t stride, unsigned max_value, int binning,
    float sigma, float* yxf, std::size_t capacity, double* elapsed_ms) {
    return detect_impl(pixels, width, height, stride, max_value, binning, sigma,
                       yxf, capacity, elapsed_ms, false);
}
extern "C" int mfds_detect_u16_refined(const std::uint16_t* pixels, std::size_t width,
    std::size_t height, std::size_t stride, unsigned max_value, int binning,
    float sigma, float* yxf, std::size_t capacity, double* elapsed_ms) {
    return detect_impl(pixels, width, height, stride, max_value, binning, sigma,
                       yxf, capacity, elapsed_ms, true);
}

extern "C" int mfds_detect_u16_pyramid(const std::uint16_t* pixels, std::size_t width,
    std::size_t height, std::size_t stride, unsigned max_value, int binning,
    float sigma, float* yxf, std::size_t capacity, double* elapsed_ms) {
    return detect_impl(pixels, width, height, stride, max_value, binning, sigma,
                       yxf, capacity, elapsed_ms, false, 1);
}
extern "C" int mfds_detect_u16_pyramid_full(const std::uint16_t* pixels, std::size_t width,
    std::size_t height, std::size_t stride, unsigned max_value, int binning,
    float sigma, float* yxf, std::size_t capacity, double* elapsed_ms) {
    return detect_impl(pixels, width, height, stride, max_value, binning, sigma,
                       yxf, capacity, elapsed_ms, false, 2);
}
