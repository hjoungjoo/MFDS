// SPDX-License-Identifier: LicenseRef-MFDS-FSL-1.1-MIT-5year
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace mf_detect_star {

struct ImageView {
    const std::uint16_t* data = nullptr;
    std::size_t width = 0;
    std::size_t height = 0;
    std::size_t stride = 0;  // uint16 elements, not bytes
    std::uint16_t max_value = 4095;
};

struct DetectorConfig {
    int binning = 1;
    int mesh_size = 32;
    float detection_sigma = 4.5F;
    float pixel_support_sigma = 1.4F;
    float noise_floor = 1.0F;
    float saturation_ratio = 0.985F;
    int saturation_dilate = 6;
    // Sensor-pixel limits: retain compact clipped stellar cores, while
    // connected extended illumination remains masked at every binning.
    std::size_t compact_saturation_pixels = 96;
    std::size_t compact_saturation_span = 16;
    int fit_radius = 4;
    int min_support_pixels = 2;
    int max_support_pixels = 90;
    float min_fwhm = 0.55F;
    float max_fwhm = 7.0F;
    float max_eccentricity = 0.94F;
    float min_separation = 4.0F;
    std::size_t max_stars = 64;
    std::vector<float> psf_sigmas = {0.85F, 1.25F};
    bool collect_diagnostics = false;
    bool refine_original = false;
};

enum StarFlag : std::uint32_t {
    STAR_NONE = 0,
    STAR_THIN_CLOUD_CELL = 1U << 0,
    STAR_NEAR_MASK = 1U << 1,
};

struct Star {
    float x = 0.0F;  // original input image coordinates
    float y = 0.0F;
    float flux = 0.0F;
    float response_sigma = 0.0F;
    float peak_sigma = 0.0F;
    float fwhm = 0.0F;
    float eccentricity = 0.0F;
    float psf_sigma = 0.0F;
    std::uint32_t flags = STAR_NONE;
};

struct QualitySummary {
    float global_background = 0.0F;
    float global_noise = 0.0F;
    float masked_fraction = 0.0F;
    std::size_t mesh_cells = 0;
    std::size_t thin_cloud_cells = 0;
    std::size_t invalid_cells = 0;
};

struct Diagnostics {
    std::size_t width = 0;
    std::size_t height = 0;
    std::vector<float> background;
    std::vector<float> noise;
    std::vector<float> normalized;
    std::vector<float> response;
    std::vector<std::uint8_t> mask;
};

struct DetectionResult {
    std::vector<Star> stars;
    QualitySummary quality;
    Diagnostics diagnostics;
    double elapsed_ms = 0.0;
    std::string error;

    [[nodiscard]] bool ok() const noexcept { return error.empty(); }
};

class Detector {
public:
    explicit Detector(DetectorConfig config = {});

    [[nodiscard]] const DetectorConfig& config() const noexcept { return config_; }
    [[nodiscard]] DetectionResult detect(const ImageView& image) const;
    // Experimental whole-frame coarse search followed by local 2x and optional
    // 1x detections. Returned coordinates always refer to the input sensor.
    [[nodiscard]] DetectionResult detect_pyramid(const ImageView& image,
                                                 bool full_resolution) const;

private:
    DetectorConfig config_;
};

}  // namespace mf_detect_star
