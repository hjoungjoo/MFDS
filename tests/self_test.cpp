// SPDX-License-Identifier: LicenseRef-MFDS-FSL-1.1-MIT-5year
#include "mf_detect_star/detector.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>
#include <iomanip>
#include <iostream>
#include <random>
#include <string>
#include <utility>
#include <vector>

namespace {

constexpr std::uint16_t kMaximum = 4095;

struct SyntheticImage {
    std::size_t width;
    std::size_t height;
    std::vector<float> values;
    std::vector<std::uint16_t> pixels;

    void quantize() {
        pixels.resize(values.size());
        std::transform(values.begin(), values.end(), pixels.begin(), [](float value) {
            return static_cast<std::uint16_t>(std::lround(
                std::clamp(value, 0.0F, static_cast<float>(kMaximum))));
        });
    }
};

SyntheticImage make_sky(std::size_t width, std::size_t height,
                        const std::function<float(float, float)>& background,
                        const std::function<float(float, float)>& noise,
                        std::uint32_t seed) {
    SyntheticImage image{width, height, std::vector<float>(width * height), {}};
    std::mt19937 random(seed);
    std::normal_distribution<float> normal(0.0F, 1.0F);
    for (std::size_t y = 0; y < height; ++y) {
        for (std::size_t x = 0; x < width; ++x) {
            image.values[y * width + x] = background(static_cast<float>(x),
                                                     static_cast<float>(y)) +
                noise(static_cast<float>(x), static_cast<float>(y)) * normal(random);
        }
    }
    return image;
}

void add_star(SyntheticImage& image, float center_x, float center_y,
              float amplitude, float sigma) {
    const int radius = static_cast<int>(std::ceil(4.0F * sigma));
    for (int dy = -radius; dy <= radius; ++dy) {
        for (int dx = -radius; dx <= radius; ++dx) {
            const int x = static_cast<int>(std::floor(center_x)) + dx;
            const int y = static_cast<int>(std::floor(center_y)) + dy;
            if (x < 0 || y < 0 || x >= static_cast<int>(image.width) ||
                y >= static_cast<int>(image.height)) {
                continue;
            }
            const float px = static_cast<float>(x) - center_x;
            const float py = static_cast<float>(y) - center_y;
            image.values[static_cast<std::size_t>(y) * image.width +
                         static_cast<std::size_t>(x)] +=
                amplitude * std::exp(-0.5F * (px * px + py * py) / (sigma * sigma));
        }
    }
}

void add_lamp(SyntheticImage& image, float center_x, float center_y,
              float core_radius, float halo_amplitude, float halo_sigma) {
    for (std::size_t y = 0; y < image.height; ++y) {
        for (std::size_t x = 0; x < image.width; ++x) {
            const float dx = static_cast<float>(x) - center_x;
            const float dy = static_cast<float>(y) - center_y;
            const float radius_squared = dx * dx + dy * dy;
            if (radius_squared <= core_radius * core_radius) {
                image.values[y * image.width + x] = static_cast<float>(kMaximum);
            } else {
                image.values[y * image.width + x] += halo_amplitude *
                    std::exp(-0.5F * radius_squared / (halo_sigma * halo_sigma));
            }
        }
    }
}

mf_detect_star::DetectionResult detect(SyntheticImage& image, int binning = 1) {
    image.quantize();
    mf_detect_star::DetectorConfig config;
    config.binning = binning;
    config.mesh_size = 32;
    config.detection_sigma = 4.3F;
    config.noise_floor = 2.0F;
    config.saturation_dilate = 8;
    config.max_stars = 80;
    const mf_detect_star::Detector detector(config);
    return detector.detect({image.pixels.data(), image.width, image.height,
                            image.width, kMaximum});
}

bool has_star_near(const mf_detect_star::DetectionResult& result,
                   float x, float y, float radius) {
    return std::any_of(result.stars.begin(), result.stars.end(), [&](const auto& star) {
        const float dx = star.x - x;
        const float dy = star.y - y;
        return dx * dx + dy * dy <= radius * radius;
    });
}

std::size_t count_stars_near(const mf_detect_star::DetectionResult& result,
                             float x, float y, float radius) {
    return static_cast<std::size_t>(std::count_if(
        result.stars.begin(), result.stars.end(), [&](const auto& star) {
            const float dx = star.x - x;
            const float dy = star.y - y;
            return dx * dx + dy * dy <= radius * radius;
        }));
}

bool test_gradient_sky() {
    auto image = make_sky(320, 240,
        [](float x, float y) { return 280.0F + 0.35F * x + 0.12F * y; },
        [](float, float) { return 5.0F; }, 11U);
    const std::vector<std::pair<float, float>> expected = {
        {55.3F, 51.7F}, {138.8F, 88.4F}, {241.2F, 65.6F},
        {82.1F, 183.5F}, {214.4F, 171.2F},
    };
    for (std::size_t index = 0; index < expected.size(); ++index) {
        add_star(image, expected[index].first, expected[index].second,
                 180.0F + static_cast<float>(index) * 25.0F, 1.15F);
    }
    const auto result = detect(image);
    if (!result.ok()) return false;
    return std::all_of(expected.begin(), expected.end(), [&](const auto& point) {
        return has_star_near(result, point.first, point.second, 2.0F);
    });
}

bool test_thin_cloud_preserves_bright_stars() {
    const auto cloud = [](float x, float y) {
        const float dx = (x - 168.0F) / 82.0F;
        const float dy = (y - 112.0F) / 58.0F;
        return std::exp(-0.5F * (dx * dx + dy * dy));
    };
    auto image = make_sky(336, 240,
        [&](float x, float y) {
            return 360.0F + 0.18F * x + 260.0F * cloud(x, y) +
                   18.0F * std::sin(x / 31.0F);
        },
        [&](float x, float y) { return 5.0F + 10.0F * cloud(x, y); }, 22U);

    // Both stars are inside the raised-background/noise cloud. The simulated
    // cloud attenuates them, but a bright observable core remains.
    add_star(image, 151.4F, 105.6F, 310.0F, 1.2F);
    add_star(image, 204.7F, 131.3F, 240.0F, 1.25F);
    // A faint source may legitimately fall below the local SNR threshold.
    add_star(image, 179.2F, 82.1F, 42.0F, 1.1F);
    const auto result = detect(image);
    if (!result.ok()) return false;
    return has_star_near(result, 151.4F, 105.6F, 2.2F) &&
           has_star_near(result, 204.7F, 131.3F, 2.2F);
}

bool test_saturated_center_keeps_edge_stars() {
    auto image = make_sky(360, 260,
        [](float x, float y) { return 310.0F + 0.08F * x + 0.04F * y; },
        [](float, float) { return 5.0F; }, 33U);
    add_lamp(image, 180.0F, 130.0F, 13.0F, 720.0F, 31.0F);
    const std::vector<std::pair<float, float>> edge_stars = {
        {29.4F, 42.2F}, {327.1F, 49.8F}, {42.6F, 215.1F}, {319.2F, 219.4F},
    };
    for (const auto& point : edge_stars) {
        add_star(image, point.first, point.second, 260.0F, 1.2F);
    }
    const auto result = detect(image);
    if (!result.ok()) return false;
    const bool all_edges = std::all_of(edge_stars.begin(), edge_stars.end(),
        [&](const auto& point) {
            return has_star_near(result, point.first, point.second, 2.3F);
        });
    return all_edges && count_stars_near(result, 180.0F, 130.0F, 24.0F) == 0U;
}

bool test_hot_pixel_rejected() {
    auto image = make_sky(256, 192,
        [](float x, float y) { return 290.0F + 0.1F * x + 0.05F * y; },
        [](float, float) { return 4.0F; }, 44U);
    add_star(image, 72.4F, 88.3F, 220.0F, 1.15F);
    image.values[101U * image.width + 171U] = 3500.0F;  // not saturated, one pixel
    const auto result = detect(image);
    if (!result.ok()) return false;
    return has_star_near(result, 72.4F, 88.3F, 2.0F) &&
           !has_star_near(result, 171.0F, 101.0F, 2.0F);
}

bool test_binning_two_coordinates() {
    auto image = make_sky(384, 256,
        [](float x, float y) { return 330.0F + 0.15F * x + 0.08F * y; },
        [](float, float) { return 5.0F; }, 55U);
    add_star(image, 291.3F, 178.7F, 210.0F, 1.45F);
    const auto result = detect(image, 2);
    return result.ok() && has_star_near(result, 291.3F, 178.7F, 2.5F);
}

bool test_compact_clipped_star_and_lamp() {
    for (const int binning : {1, 2, 4}) {
        auto image = make_sky(512, 384,
            [](float x, float) { return 1100.0F + 0.2F * x; },
            [](float, float) { return 5.0F; }, 83U);
        add_star(image, 150.3F, 170.7F, 7000.0F, 1.8F);
        add_lamp(image, 350.0F, 210.0F, 20.0F, 700.0F, 30.0F);
        image.values[90U * image.width + 270U] = kMaximum;
        for (std::size_t y = 85; y < 92; ++y) {
            for (std::size_t x = 365; x < 372; ++x) {
                image.values[y * image.width + x] = kMaximum;
            }
        }
        const auto result = detect(image, binning);
        if (!result.ok() || !has_star_near(result, 150.3F, 170.7F, 2.5F) ||
            has_star_near(result, 350.0F, 210.0F, 26.0F) ||
            has_star_near(result, 270.0F, 90.0F, 4.0F) ||
            has_star_near(result, 368.0F, 88.0F, 6.0F)) return false;
    }
    return true;
}

bool test_pyramid_coordinates_and_stride() {
    auto image = make_sky(513, 385,
        [](float x, float y) { return 330.0F + 0.15F*x + 0.08F*y; },
        [](float, float) { return 4.0F; }, 72U);
    const std::vector<std::pair<float, float>> expected = {
        {43.3F, 45.7F}, {231.4F, 176.8F}, {463.2F, 339.1F}};
    for (const auto& point : expected) {
        add_star(image, point.first, point.second,
                 point.first > 200.0F && point.first < 300.0F ? 7000.0F : 450.0F, 1.5F);
    }
    image.values[280U*image.width+100U] = 3500.0F;
    image.quantize();
    const auto stride = image.width+17U;
    std::vector<std::uint16_t> padded(stride*image.height, kMaximum);
    for (std::size_t y=0; y<image.height; ++y) {
        std::copy_n(image.pixels.data()+y*image.width, image.width, padded.data()+y*stride);
    }
    mf_detect_star::DetectorConfig config;
    config.binning = 4;
    config.mesh_size = 64;
    config.noise_floor = 2.0F;
    config.max_stars = 128;
    const mf_detect_star::Detector detector(config);
    for (const bool full : {false, true}) {
        const auto result = detector.detect_pyramid(
            {padded.data(), image.width, image.height, stride, kMaximum}, full);
        if (!result.ok() || result.stars.size() != expected.size()) return false;
        for (const auto& point : expected) {
            if (!has_star_near(result, point.first, point.second, 0.7F)) return false;
        }
    }
    const auto invalid = detector.detect_pyramid({nullptr, 513, 385, 530, kMaximum}, false);
    return !invalid.ok();
}

bool test_pyramid_compact_stars_at_coarse_pixel_phases() {
    // Bright, well-sampled sensor PSFs can become a single coarse pixel.
    // Sweep their location within a 4x cell without changing their width/SNR.
    for (float phase : {0.0F, 0.5F, 1.0F, 1.5F, 2.0F, 2.5F, 3.0F, 3.5F}) {
        auto image = make_sky(256, 256,
            [](float, float) { return 500.0F; },
            [](float, float) { return 0.0F; }, 84U);
        const float x = 121.5F + phase;
        const float y = 121.5F;
        add_star(image, x, y, 1500.0F, 0.85F);
        // Unsaturated hot pixels must still fail the unchanged fine-stage gate.
        image.values[60U * image.width + 60U] = 3500.0F;
        image.quantize();
        mf_detect_star::DetectorConfig config;
        config.binning = 4;
        config.mesh_size = 64;
        config.noise_floor = 2.0F;
        for (bool full : {false, true}) {
            const auto result = mf_detect_star::Detector(config).detect_pyramid(
                {image.pixels.data(), image.width, image.height, image.width, kMaximum},
                full);
            if (!result.ok() || result.stars.size() != 1U ||
                !has_star_near(result, x, y, 0.7F)) return false;
        }
    }
    return true;
}

}  // namespace

int main() {
    const std::vector<std::pair<std::string, std::function<bool()>>> tests = {
        {"gradient_sky", test_gradient_sky},
        {"thin_cloud_preserves_bright_stars", test_thin_cloud_preserves_bright_stars},
        {"saturated_center_keeps_edge_stars", test_saturated_center_keeps_edge_stars},
        {"hot_pixel_rejected", test_hot_pixel_rejected},
        {"binning_two_coordinates", test_binning_two_coordinates},
        {"compact_clipped_star_and_lamp", test_compact_clipped_star_and_lamp},
        {"pyramid_coordinates_and_stride", test_pyramid_coordinates_and_stride},
        {"pyramid_compact_stars_at_coarse_pixel_phases", test_pyramid_compact_stars_at_coarse_pixel_phases},
    };
    std::size_t passed = 0;
    for (const auto& [name, test] : tests) {
        const bool success = test();
        std::cout << (success ? "PASS " : "FAIL ") << name << '\n';
        passed += success ? 1U : 0U;
    }
    std::cout << passed << '/' << tests.size() << " tests passed\n";
    return passed == tests.size() ? 0 : 1;
}
