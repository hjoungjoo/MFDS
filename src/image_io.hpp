// SPDX-License-Identifier: LicenseRef-MFDS-FSL-1.1-MIT-5year
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace mf_detect_star {

struct OwnedImage {
    std::size_t width = 0;
    std::size_t height = 0;
    std::uint16_t max_value = 0;
    std::vector<std::uint16_t> pixels;
};

struct RawInputOptions {
    std::size_t width = 0;
    std::size_t height = 0;
    std::size_t stride = 0;
    std::uint16_t max_value = 4095;
};

bool load_image(const std::string& path,
                const RawInputOptions& raw_options,
                OwnedImage& image,
                std::string& error);

bool write_float_pgm(const std::string& path,
                     const std::vector<float>& values,
                     std::size_t width,
                     std::size_t height,
                     float low_quantile,
                     float high_quantile,
                     std::string& error);

bool write_mask_pgm(const std::string& path,
                    const std::vector<std::uint8_t>& values,
                    std::size_t width,
                    std::size_t height,
                    std::string& error);

}  // namespace mf_detect_star

