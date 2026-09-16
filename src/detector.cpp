// SPDX-License-Identifier: LicenseRef-MFDS-FSL-1.1-MIT-5year
#include "mf_detect_star/detector.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <numeric>
#include <optional>
#include <stdexcept>
#include <utility>

namespace mf_detect_star {
namespace {

constexpr float kMadToSigma = 1.4826022185F;

struct WorkingImage {
    std::size_t width = 0;
    std::size_t height = 0;
    int binning = 1;
    std::vector<float> pixels;
    std::vector<std::uint8_t> saturated;
};

struct MeshCell {
    float background = 0.0F;
    float noise = 1.0F;
    float saturation_fraction = 0.0F;
    bool valid = true;
    bool thin_cloud = false;
};

struct MeshModel {
    std::size_t nx = 0;
    std::size_t ny = 0;
    int mesh_size = 32;
    std::vector<MeshCell> cells;
    float global_background = 0.0F;
    float global_noise = 1.0F;
};

float median_in_place(std::vector<float>& values) {
    if (values.empty()) {
        return 0.0F;
    }
    const std::size_t middle = values.size() / 2;
    std::nth_element(values.begin(), values.begin() + static_cast<std::ptrdiff_t>(middle),
                     values.end());
    const float upper = values[middle];
    if ((values.size() & 1U) != 0U) {
        return upper;
    }
    const float lower = *std::max_element(values.begin(),
                                          values.begin() + static_cast<std::ptrdiff_t>(middle));
    return 0.5F * (lower + upper);
}

float vector_median(std::vector<float> values) {
    return median_in_place(values);
}

bool has_clipped_wings(const ImageView& input, std::size_t min_x,
                       std::size_t max_x, std::size_t min_y, std::size_t max_y) {
    // A clipped stellar core retains a PSF outside its plateau. Isolated
    // hot pixels and hard-edged lamp rectangles do not have these wings.
    if (min_x < 5U || min_y < 5U || max_x + 5U >= input.width ||
        max_y + 5U >= input.height) return false;
    const auto border_mean = [&](std::size_t padding) {
        const auto left = min_x - padding, right = max_x + padding;
        const auto top = min_y - padding, bottom = max_y + padding;
        double sum = 0.0;
        std::size_t count = 0;
        for (std::size_t x = left; x <= right; ++x) {
            sum += input.data[top * input.stride + x];
            sum += input.data[bottom * input.stride + x];
            count += 2U;
        }
        for (std::size_t y = top + 1U; y < bottom; ++y) {
            sum += input.data[y * input.stride + left];
            sum += input.data[y * input.stride + right];
            count += 2U;
        }
        return sum / static_cast<double>(count);
    };
    // Average adjacent borders to cancel Bayer-phase background offsets.
    const double background = (border_mean(4U) + border_mean(5U)) * 0.5;
    return (border_mean(1U) + border_mean(2U)) * 0.5 - background >
        std::max(4.0, 0.02 * (static_cast<double>(input.max_value) - background));
}

WorkingImage make_working_image(const ImageView& input, int binning,
                                const DetectorConfig& config) {
    WorkingImage output;
    output.binning = binning;
    output.width = input.width / static_cast<std::size_t>(binning);
    output.height = input.height / static_cast<std::size_t>(binning);
    output.pixels.resize(output.width * output.height);
    output.saturated.assign(output.pixels.size(), 0U);

    const float saturation = static_cast<float>(input.max_value) * config.saturation_ratio;
    std::vector<std::uint8_t> clipped(input.width * input.height, 0U);
    for (std::size_t y = 0; y < input.height; ++y) {
        for (std::size_t x = 0; x < input.width; ++x) {
            clipped[y * input.width + x] =
                static_cast<float>(input.data[y * input.stride + x]) >= saturation ? 1U : 0U;
        }
    }
    // Classify on the sensor grid, before binning changes component area.
    // Eight-connected flood filling also handles clipped CFA pixel clusters.
    std::vector<std::size_t> component;
    for (std::size_t seed = 0; seed < clipped.size(); ++seed) {
        if (clipped[seed] != 1U) continue;
        component.clear();
        component.push_back(seed);
        clipped[seed] = 2U;
        std::size_t min_x = seed % input.width, max_x = min_x;
        std::size_t min_y = seed / input.width, max_y = min_y;
        for (std::size_t cursor = 0; cursor < component.size(); ++cursor) {
            const auto index = component[cursor];
            const auto y = index / input.width, x = index % input.width;
            min_x = std::min(min_x, x); max_x = std::max(max_x, x);
            min_y = std::min(min_y, y); max_y = std::max(max_y, y);
            for (std::size_t yy = y == 0U ? 0U : y - 1U;
                 yy <= std::min(input.height - 1U, y + 1U); ++yy) {
                for (std::size_t xx = x == 0U ? 0U : x - 1U;
                     xx <= std::min(input.width - 1U, x + 1U); ++xx) {
                    const auto neighbour = yy * input.width + xx;
                    if (clipped[neighbour] == 1U) {
                        clipped[neighbour] = 2U;
                        component.push_back(neighbour);
                    }
                }
            }
        }
        if (component.size() <= config.compact_saturation_pixels &&
            max_x - min_x + 1U <= config.compact_saturation_span &&
            max_y - min_y + 1U <= config.compact_saturation_span &&
            has_clipped_wings(input, min_x, max_x, min_y, max_y)) continue;
        for (const auto index : component) {
            const auto by = (index / input.width) / static_cast<std::size_t>(binning);
            const auto bx = (index % input.width) / static_cast<std::size_t>(binning);
            if (by < output.height && bx < output.width) {
                output.saturated[by * output.width + bx] = 1U;
            }
        }
    }
    const float divisor = static_cast<float>(binning * binning);
    for (std::size_t y = 0; y < output.height; ++y) {
        for (std::size_t x = 0; x < output.width; ++x) {
            std::uint64_t sum = 0;
            for (int by = 0; by < binning; ++by) {
                const auto* row = input.data +
                    (y * static_cast<std::size_t>(binning) + static_cast<std::size_t>(by)) *
                        input.stride;
                for (int bx = 0; bx < binning; ++bx) {
                    const auto value = row[x * static_cast<std::size_t>(binning) +
                                           static_cast<std::size_t>(bx)];
                    sum += value;
                }
            }
            const std::size_t index = y * output.width + x;
            output.pixels[index] = static_cast<float>(sum) / divisor;
        }
    }
    return output;
}

std::vector<std::uint8_t> dilate_mask(const std::vector<std::uint8_t>& source,
                                      std::size_t width, std::size_t height,
                                      int radius) {
    if (radius <= 0) {
        return source;
    }
    std::vector<std::uint8_t> horizontal(source.size(), 0U);
    std::vector<std::uint8_t> output(source.size(), 0U);

    for (std::size_t y = 0; y < height; ++y) {
        int last = -radius - 1;
        for (std::size_t x = 0; x < width; ++x) {
            const std::size_t add_x = std::min(width - 1, x + static_cast<std::size_t>(radius));
            if (source[y * width + add_x] != 0U) {
                last = static_cast<int>(add_x);
            }
            if (last >= static_cast<int>(x) - radius) {
                horizontal[y * width + x] = 1U;
            }
        }
        last = static_cast<int>(width) + radius;
        for (std::size_t x = width; x-- > 0;) {
            const std::size_t sub_x = x > static_cast<std::size_t>(radius)
                ? x - static_cast<std::size_t>(radius)
                : 0;
            if (source[y * width + sub_x] != 0U) {
                last = static_cast<int>(sub_x);
            }
            if (last <= static_cast<int>(x) + radius) {
                horizontal[y * width + x] = 1U;
            }
        }
    }

    for (std::size_t x = 0; x < width; ++x) {
        int last = -radius - 1;
        for (std::size_t y = 0; y < height; ++y) {
            const std::size_t add_y = std::min(height - 1, y + static_cast<std::size_t>(radius));
            if (horizontal[add_y * width + x] != 0U) {
                last = static_cast<int>(add_y);
            }
            if (last >= static_cast<int>(y) - radius) {
                output[y * width + x] = 1U;
            }
        }
        last = static_cast<int>(height) + radius;
        for (std::size_t y = height; y-- > 0;) {
            const std::size_t sub_y = y > static_cast<std::size_t>(radius)
                ? y - static_cast<std::size_t>(radius)
                : 0;
            if (horizontal[sub_y * width + x] != 0U) {
                last = static_cast<int>(sub_y);
            }
            if (last <= static_cast<int>(y) + radius) {
                output[y * width + x] = 1U;
            }
        }
    }
    return output;
}

MeshModel estimate_mesh(const WorkingImage& image,
                        const std::vector<std::uint8_t>& mask,
                        int mesh_size, float noise_floor) {
    MeshModel model;
    model.mesh_size = mesh_size;
    model.nx = (image.width + static_cast<std::size_t>(mesh_size) - 1U) /
               static_cast<std::size_t>(mesh_size);
    model.ny = (image.height + static_cast<std::size_t>(mesh_size) - 1U) /
               static_cast<std::size_t>(mesh_size);
    model.cells.resize(model.nx * model.ny);

    std::vector<float> valid_backgrounds;
    std::vector<float> valid_noises;
    std::vector<float> samples;
    std::vector<float> deviations;
    samples.reserve(static_cast<std::size_t>(mesh_size * mesh_size));
    deviations.reserve(samples.capacity());

    for (std::size_t my = 0; my < model.ny; ++my) {
        const std::size_t y0 = my * static_cast<std::size_t>(mesh_size);
        const std::size_t y1 = std::min(image.height, y0 + static_cast<std::size_t>(mesh_size));
        for (std::size_t mx = 0; mx < model.nx; ++mx) {
            const std::size_t x0 = mx * static_cast<std::size_t>(mesh_size);
            const std::size_t x1 = std::min(image.width, x0 + static_cast<std::size_t>(mesh_size));
            samples.clear();
            std::size_t saturated_count = 0;
            const std::size_t total = (x1 - x0) * (y1 - y0);
            for (std::size_t y = y0; y < y1; ++y) {
                for (std::size_t x = x0; x < x1; ++x) {
                    const std::size_t index = y * image.width + x;
                    saturated_count += image.saturated[index] != 0U ? 1U : 0U;
                    if (mask[index] == 0U) {
                        samples.push_back(image.pixels[index]);
                    }
                }
            }

            auto& cell = model.cells[my * model.nx + mx];
            cell.saturation_fraction = total == 0U
                ? 1.0F
                : static_cast<float>(saturated_count) / static_cast<float>(total);
            const std::size_t minimum_samples = std::max<std::size_t>(16U, total / 10U);
            cell.valid = samples.size() >= minimum_samples && cell.saturation_fraction < 0.75F;
            if (!cell.valid) {
                continue;
            }

            cell.background = median_in_place(samples);
            deviations.resize(samples.size());
            std::transform(samples.begin(), samples.end(), deviations.begin(),
                           [center = cell.background](float value) {
                               return std::abs(value - center);
                           });
            cell.noise = std::max(noise_floor, kMadToSigma * median_in_place(deviations));
            valid_backgrounds.push_back(cell.background);
            valid_noises.push_back(cell.noise);
        }
    }

    model.global_background = valid_backgrounds.empty()
        ? 0.0F : vector_median(valid_backgrounds);
    model.global_noise = valid_noises.empty()
        ? noise_floor : std::max(noise_floor, vector_median(valid_noises));

    for (auto& cell : model.cells) {
        if (!cell.valid) {
            cell.background = model.global_background;
            cell.noise = model.global_noise;
            continue;
        }
        const bool raised_background =
            cell.background > model.global_background + 2.5F * model.global_noise;
        const bool raised_noise =
            cell.noise > std::max(1.8F * model.global_noise, 2.0F * noise_floor);
        // Diagnostic only: this flag never suppresses a cell. Bright stars seen
        // through thin cloud must still proceed to local-SNR detection.
        cell.thin_cloud = raised_background || raised_noise;
    }
    return model;
}

struct AxisInterpolation {
    std::size_t lo, hi;
    float fraction;
};
std::vector<AxisInterpolation> interpolation_axis(std::size_t pixels,
                                                 std::size_t cells, int mesh) {
    std::vector<AxisInterpolation> axis(pixels);
    for (std::size_t i = 0; i < pixels; ++i) {
        const float position = std::clamp(
            (static_cast<float>(i) + 0.5F) / static_cast<float>(mesh) - 0.5F,
            0.0F, static_cast<float>(cells - 1U));
        const auto lo = static_cast<std::size_t>(std::floor(position));
        axis[i] = {lo, std::min(cells - 1U, lo + 1U), position-static_cast<float>(lo)};
    }
    return axis;
}

bool cloud_cell_at(const MeshModel& model, float x, float y) {
    const auto mx = std::min(model.nx - 1U,
        static_cast<std::size_t>(std::max(0.0F, x) / static_cast<float>(model.mesh_size)));
    const auto my = std::min(model.ny - 1U,
        static_cast<std::size_t>(std::max(0.0F, y) / static_cast<float>(model.mesh_size)));
    return model.cells[my * model.nx + mx].thin_cloud;
}

std::vector<float> gaussian_kernel(float sigma) {
    const int radius = std::max(1, static_cast<int>(std::ceil(3.0F * sigma)));
    std::vector<float> kernel(static_cast<std::size_t>(2 * radius + 1));
    float sum = 0.0F;
    for (int i = -radius; i <= radius; ++i) {
        const float value = std::exp(-0.5F * static_cast<float>(i * i) / (sigma * sigma));
        kernel[static_cast<std::size_t>(i + radius)] = value;
        sum += value;
    }
    for (auto& value : kernel) {
        value /= sum;
    }
    return kernel;
}

void separable_blur(const std::vector<float>& input, std::size_t width,
                    std::size_t height, const std::vector<float>& kernel,
                    std::vector<float>& output, std::vector<float>& scratch) {
    output.resize(input.size());
    scratch.resize(input.size());
    const int radius = static_cast<int>(kernel.size() / 2U);
    // Accumulate each tap across a contiguous row. This preserves tap order
    // per pixel while allowing compiler SIMD and avoiding per-pixel clamps.
    for (std::size_t y = 0; y < height; ++y) {
        const auto base = y*width;
        std::fill_n(scratch.data()+base, width, 0.0F);
        for (int k = -radius; k <= radius; ++k) {
            const float weight = kernel[static_cast<std::size_t>(k+radius)];
            const int lo = std::clamp(-k, 0, static_cast<int>(width));
            const int hi = std::clamp(static_cast<int>(width)-k, lo, static_cast<int>(width));
            for (int x = 0; x < lo; ++x)
                scratch[base+static_cast<std::size_t>(x)] += input[base]*weight;
            for (int x = lo; x < hi; ++x)
                scratch[base+static_cast<std::size_t>(x)] += input[base+static_cast<std::size_t>(x+k)]*weight;
            for (std::size_t x = static_cast<std::size_t>(hi); x < width; ++x)
                scratch[base+x] += input[base+width-1U]*weight;
        }
    }
    for (std::size_t y = 0; y < height; ++y) {
        auto* dest = output.data()+y*width;
        std::fill_n(dest, width, 0.0F);
        for (int k = -radius; k <= radius; ++k) {
            const auto sy = static_cast<std::size_t>(std::clamp(
                static_cast<int>(y)+k, 0, static_cast<int>(height)-1));
            const auto* source = scratch.data()+sy*width;
            const float weight = kernel[static_cast<std::size_t>(k+radius)];
            for (std::size_t x = 0; x < width; ++x) dest[x] += source[x]*weight;
        }
    }
}

void box_blur(const std::vector<float>& input, std::size_t width,
              std::size_t height, int radius, std::vector<float>& output,
              std::vector<float>& scratch) {
    output.resize(input.size());
    scratch.resize(input.size());
    const float divisor = static_cast<float>(2 * radius + 1);
    for (std::size_t y = 0; y < height; ++y) {
        float sum = 0.0F;
        for (int k = -radius; k <= radius; ++k) {
            const auto x = static_cast<std::size_t>(std::clamp(
                k, 0, static_cast<int>(width) - 1));
            sum += input[y * width + x];
        }
        for (std::size_t x = 0; x < width; ++x) {
            scratch[y * width + x] = sum / divisor;
            const auto remove_x = static_cast<std::size_t>(std::clamp(
                static_cast<int>(x) - radius, 0, static_cast<int>(width) - 1));
            const auto add_x = static_cast<std::size_t>(std::clamp(
                static_cast<int>(x) + radius + 1, 0, static_cast<int>(width) - 1));
            sum += input[y * width + add_x] - input[y * width + remove_x];
        }
    }
    for (std::size_t x = 0; x < width; ++x) {
        float sum = 0.0F;
        for (int k = -radius; k <= radius; ++k) {
            const auto y = static_cast<std::size_t>(std::clamp(
                k, 0, static_cast<int>(height) - 1));
            sum += scratch[y * width + x];
        }
        for (std::size_t y = 0; y < height; ++y) {
            output[y * width + x] = sum / divisor;
            const auto remove_y = static_cast<std::size_t>(std::clamp(
                static_cast<int>(y) - radius, 0, static_cast<int>(height) - 1));
            const auto add_y = static_cast<std::size_t>(std::clamp(
                static_cast<int>(y) + radius + 1, 0, static_cast<int>(height) - 1));
            sum += scratch[add_y * width + x] - scratch[remove_y * width + x];
        }
    }
}

float zero_mean_noise_norm(const std::vector<float>& small, int box_radius) {
    const int small_radius = static_cast<int>(small.size() / 2U);
    const float box_weight = 1.0F /
        static_cast<float>((2 * box_radius + 1) * (2 * box_radius + 1));
    double sum_squares = 0.0;
    for (int y = -box_radius; y <= box_radius; ++y) {
        const float sy = std::abs(y) <= small_radius
            ? small[static_cast<std::size_t>(y + small_radius)] : 0.0F;
        for (int x = -box_radius; x <= box_radius; ++x) {
            const float sx = std::abs(x) <= small_radius
                ? small[static_cast<std::size_t>(x + small_radius)] : 0.0F;
            const double coefficient = static_cast<double>(sx * sy - box_weight);
            sum_squares += coefficient * coefficient;
        }
    }
    return std::max(1.0e-6F, static_cast<float>(std::sqrt(sum_squares)));
}

struct RawCandidate {
    std::size_t x = 0;
    std::size_t y = 0;
    float response = 0.0F;
    float scale = 0.0F;
};

std::optional<Star> fit_candidate(const RawCandidate& candidate,
                                  const WorkingImage& image,
                                  const MeshModel& mesh,
                                  const std::vector<float>& background,
                                  const std::vector<float>& noise,
                                  const std::vector<float>& normalized,
                                  const std::vector<std::uint8_t>& mask,
                                  const DetectorConfig& config) {
    const int radius = config.fit_radius;
    const int cx = static_cast<int>(candidate.x);
    const int cy = static_cast<int>(candidate.y);
    float sum = 0.0F;
    float sum_x = 0.0F;
    float sum_y = 0.0F;
    int support = 0;
    int core_support = 0;
    bool near_mask = false;
    const float candidate_peak = normalized[candidate.y * image.width + candidate.x];
    const float core_support_threshold = std::max(
        config.pixel_support_sigma, 0.10F * candidate_peak);

    for (int dy = -radius; dy <= radius; ++dy) {
        for (int dx = -radius; dx <= radius; ++dx) {
            if (dx * dx + dy * dy > radius * radius) {
                continue;
            }
            const int x = cx + dx;
            const int y = cy + dy;
            if (x < 0 || y < 0 || x >= static_cast<int>(image.width) ||
                y >= static_cast<int>(image.height)) {
                continue;
            }
            const std::size_t index = static_cast<std::size_t>(y) * image.width +
                                      static_cast<std::size_t>(x);
            if (mask[index] != 0U) {
                near_mask = true;
                continue;
            }
            support += normalized[index] >= config.pixel_support_sigma ? 1 : 0;
            if (std::abs(dx) <= 1 && std::abs(dy) <= 1 &&
                normalized[index] >= core_support_threshold) {
                ++core_support;
            }
            const float weight = std::max(0.0F, image.pixels[index] - background[index]);
            sum += weight;
            sum_x += weight * static_cast<float>(x);
            sum_y += weight * static_cast<float>(y);
        }
    }
    if (core_support < config.min_support_pixels ||
        support > config.max_support_pixels || sum <= 0.0F) {
        return std::nullopt;
    }

    const float center_x = sum_x / sum;
    const float center_y = sum_y / sum;
    float xx = 0.0F;
    float yy = 0.0F;
    float xy = 0.0F;
    for (int dy = -radius; dy <= radius; ++dy) {
        for (int dx = -radius; dx <= radius; ++dx) {
            if (dx * dx + dy * dy > radius * radius) {
                continue;
            }
            const int x = cx + dx;
            const int y = cy + dy;
            if (x < 0 || y < 0 || x >= static_cast<int>(image.width) ||
                y >= static_cast<int>(image.height)) {
                continue;
            }
            const std::size_t index = static_cast<std::size_t>(y) * image.width +
                                      static_cast<std::size_t>(x);
            if (mask[index] != 0U) {
                continue;
            }
            const float weight = std::max(0.0F, image.pixels[index] - background[index]);
            const float px = static_cast<float>(x) - center_x;
            const float py = static_cast<float>(y) - center_y;
            xx += weight * px * px;
            yy += weight * py * py;
            xy += weight * px * py;
        }
    }
    xx /= sum;
    yy /= sum;
    xy /= sum;
    const float trace = xx + yy;
    const float discriminant = std::sqrt(std::max(0.0F,
        0.25F * (xx - yy) * (xx - yy) + xy * xy));
    const float lambda_major = std::max(0.0F, 0.5F * trace + discriminant);
    const float lambda_minor = std::max(0.0F, 0.5F * trace - discriminant);
    const float fwhm = 2.354820045F * std::sqrt(std::max(0.0F, 0.5F * trace));
    const float eccentricity = lambda_major <= 1.0e-6F
        ? 1.0F
        : std::sqrt(std::clamp(1.0F - lambda_minor / lambda_major, 0.0F, 1.0F));
    if (fwhm < config.min_fwhm || fwhm > config.max_fwhm ||
        eccentricity > config.max_eccentricity) {
        return std::nullopt;
    }

    const float full_offset = 0.5F * static_cast<float>(image.binning - 1);
    Star star;
    star.x = center_x * static_cast<float>(image.binning) + full_offset;
    star.y = center_y * static_cast<float>(image.binning) + full_offset;
    star.flux = sum * static_cast<float>(image.binning * image.binning);
    star.response_sigma = candidate.response;
    star.peak_sigma = normalized[candidate.y * image.width + candidate.x];
    star.fwhm = fwhm * static_cast<float>(image.binning);
    star.eccentricity = eccentricity;
    star.psf_sigma = candidate.scale * static_cast<float>(image.binning);
    if (cloud_cell_at(mesh, center_x, center_y)) {
        star.flags |= STAR_THIN_CLOUD_CELL;
    }
    if (near_mask) {
        star.flags |= STAR_NEAR_MASK;
    }
    (void)noise;
    return star;
}

// Independent annular-background centroid on the original samples. Detection
// can be binned, while astrometry retains subpixel information from the RAW.
void refine_original_centroid(Star& star, const ImageView& image) {
    const int cx = static_cast<int>(std::lround(star.x));
    const int cy = static_cast<int>(std::lround(star.y));
    if (cx < 7 || cy < 7 || cx + 7 >= static_cast<int>(image.width) ||
        cy + 7 >= static_cast<int>(image.height)) return;
    std::vector<float> annulus;
    for (int dy = -7; dy <= 7; ++dy) {
        for (int dx = -7; dx <= 7; ++dx) {
            const int r2 = dx*dx + dy*dy;
            if (r2 >= 25 && r2 <= 49) {
                annulus.push_back(static_cast<float>(image.data[
                    static_cast<std::size_t>(cy+dy)*image.stride +
                    static_cast<std::size_t>(cx+dx)]));
            }
        }
    }
    const float background = median_in_place(annulus);
    float x = star.x, y = star.y;
    // Iterative Gaussian-windowed photocentre reduces distant positive-noise
    // bias. Signed background-subtracted samples avoid rectification bias.
    constexpr double window_variance = 2.25;
    for (int iteration = 0; iteration < 8; ++iteration) {
        double sum = 0, sx = 0, sy = 0;
        for (int dy = -5; dy <= 5; ++dy) {
            for (int dx = -5; dx <= 5; ++dx) {
                const auto value = image.data[static_cast<std::size_t>(cy+dy)*image.stride +
                                              static_cast<std::size_t>(cx+dx)];
                const double px = cx+dx, py = cy+dy;
                const double distance = (px-x)*(px-x)+(py-y)*(py-y);
                const double weight = (static_cast<double>(value)-background)*
                    std::exp(-distance/(2.0*window_variance));
                sum += weight; sx += weight*px; sy += weight*py;
            }
        }
        if (sum <= 0) return;
        const float next_x = static_cast<float>(sx/sum);
        const float next_y = static_cast<float>(sy/sum);
        if (!std::isfinite(next_x) || !std::isfinite(next_y) ||
            std::hypot(next_x-star.x, next_y-star.y) > 1.5F) return;
        const float step = std::hypot(next_x-x, next_y-y);
        x = next_x; y = next_y;
        if (step < 0.001F) break;
    }
    star.x = x;
    star.y = y;
}

}  // namespace

Detector::Detector(DetectorConfig config) : config_(std::move(config)) {
    if (config_.binning != 1 && config_.binning != 2 &&
        config_.binning != 4 && config_.binning != 8) {
        throw std::invalid_argument("binning must be 1, 2, 4 or 8");
    }
    if (config_.mesh_size < 8 || config_.fit_radius < 2 ||
        config_.detection_sigma <= 0.0F || config_.noise_floor <= 0.0F ||
        config_.psf_sigmas.empty()) {
        throw std::invalid_argument("invalid detector configuration");
    }
    for (const float sigma : config_.psf_sigmas) {
        if (sigma <= 0.0F) {
            throw std::invalid_argument("PSF sigma must be positive");
        }
    }
}

DetectionResult Detector::detect(const ImageView& input) const {
    const auto start = std::chrono::steady_clock::now();
    DetectionResult result;
    if (input.data == nullptr || input.width < 32U || input.height < 32U ||
        input.stride < input.width || input.max_value == 0U) {
        result.error = "invalid input image";
        return result;
    }

    const WorkingImage image = make_working_image(
        input, config_.binning, config_);
    if (image.width < 24U || image.height < 24U) {
        result.error = "working image is too small";
        return result;
    }
    const int work_dilate = std::max(1,
        (config_.saturation_dilate + config_.binning - 1) / config_.binning);
    const auto mask = dilate_mask(image.saturated, image.width, image.height, work_dilate);
    const int work_mesh = std::max(8, config_.mesh_size / config_.binning);
    const float work_noise_floor = config_.noise_floor;
    const auto mesh = estimate_mesh(image, mask, work_mesh, work_noise_floor);

    result.quality.global_background = mesh.global_background;
    result.quality.global_noise = mesh.global_noise;
    result.quality.mesh_cells = mesh.cells.size();
    result.quality.thin_cloud_cells = static_cast<std::size_t>(std::count_if(
        mesh.cells.begin(), mesh.cells.end(), [](const MeshCell& cell) {
            return cell.thin_cloud;
        }));
    result.quality.invalid_cells = static_cast<std::size_t>(std::count_if(
        mesh.cells.begin(), mesh.cells.end(), [](const MeshCell& cell) {
            return !cell.valid;
        }));
    result.quality.masked_fraction = static_cast<float>(std::count(
        mask.begin(), mask.end(), static_cast<std::uint8_t>(1U))) /
        static_cast<float>(mask.size());

    std::vector<float> background(image.pixels.size());
    std::vector<float> noise(image.pixels.size());
    std::vector<float> normalized(image.pixels.size());
    const auto x_axis = interpolation_axis(image.width, mesh.nx, mesh.mesh_size);
    const auto y_axis = interpolation_axis(image.height, mesh.ny, mesh.mesh_size);
    for (std::size_t y = 0; y < image.height; ++y) {
        const auto& ay = y_axis[y];
        for (std::size_t x = 0; x < image.width; ++x) {
            const auto& ax = x_axis[x];
            const auto& a = mesh.cells[ay.lo*mesh.nx+ax.lo];
            const auto& b = mesh.cells[ay.lo*mesh.nx+ax.hi];
            const auto& c = mesh.cells[ay.hi*mesh.nx+ax.lo];
            const auto& d = mesh.cells[ay.hi*mesh.nx+ax.hi];
            const auto index = y*image.width+x;
            background[index] = std::lerp(std::lerp(a.background,b.background,ax.fraction),
                std::lerp(c.background,d.background,ax.fraction),ay.fraction);
            noise[index] = std::max(config_.noise_floor,
                std::lerp(std::lerp(a.noise,b.noise,ax.fraction),
                std::lerp(c.noise,d.noise,ax.fraction),ay.fraction));
            normalized[index] = mask[index] != 0U ? 0.0F :
                (image.pixels[index]-background[index])/noise[index];
        }
    }

    std::vector<float> best_response(image.pixels.size(),
                                     -std::numeric_limits<float>::infinity());
    std::vector<float> best_scale(image.pixels.size(), 0.0F);
    std::vector<float> small_blur;
    std::vector<float> local_mean;
    std::vector<float> scratch;
    for (const float sigma : config_.psf_sigmas) {
        const auto small_kernel = gaussian_kernel(sigma);
        const int box_radius = std::max(
            static_cast<int>(small_kernel.size() / 2U) + 1,
            static_cast<int>(std::ceil(3.5F * sigma)));
        separable_blur(normalized, image.width, image.height,
                       small_kernel, small_blur, scratch);
        box_blur(normalized, image.width, image.height,
                 box_radius, local_mean, scratch);
        const float norm = zero_mean_noise_norm(small_kernel, box_radius);
        for (std::size_t index = 0; index < best_response.size(); ++index) {
            const float response = (small_blur[index] - local_mean[index]) / norm;
            if (response > best_response[index]) {
                best_response[index] = response;
                best_scale[index] = sigma;
            }
        }
    }

    int largest_radius = config_.fit_radius;
    for (const float sigma : config_.psf_sigmas) {
        largest_radius = std::max(largest_radius,
            static_cast<int>(std::ceil(3.5F * sigma)));
    }
    std::vector<RawCandidate> raw_candidates;
    for (std::size_t y = static_cast<std::size_t>(largest_radius);
         y + static_cast<std::size_t>(largest_radius) < image.height; ++y) {
        for (std::size_t x = static_cast<std::size_t>(largest_radius);
             x + static_cast<std::size_t>(largest_radius) < image.width; ++x) {
            const std::size_t index = y * image.width + x;
            const float value = best_response[index];
            if (mask[index] != 0U || value < config_.detection_sigma) {
                continue;
            }
            bool maximum = true;
            for (int dy = -1; dy <= 1 && maximum; ++dy) {
                for (int dx = -1; dx <= 1; ++dx) {
                    if (dx == 0 && dy == 0) {
                        continue;
                    }
                    const std::size_t neighbor =
                        static_cast<std::size_t>(static_cast<int>(y) + dy) * image.width +
                        static_cast<std::size_t>(static_cast<int>(x) + dx);
                    if (best_response[neighbor] > value ||
                        (best_response[neighbor] == value && neighbor < index)) {
                        maximum = false;
                        break;
                    }
                }
            }
            if (maximum) {
                raw_candidates.push_back({x, y, value, best_scale[index]});
            }
        }
    }
    std::sort(raw_candidates.begin(), raw_candidates.end(),
              [](const RawCandidate& left, const RawCandidate& right) {
                  return left.response > right.response;
              });

    std::vector<Star> fitted;
    fitted.reserve(std::min(raw_candidates.size(), config_.max_stars * 4U));
    for (const auto& candidate : raw_candidates) {
        auto star = fit_candidate(candidate, image, mesh, background, noise,
                                  normalized, mask, config_);
        if (!star.has_value()) {
            continue;
        }
        const float minimum_distance = config_.min_separation *
                                       static_cast<float>(config_.binning);
        const bool duplicate = std::any_of(fitted.begin(), fitted.end(),
            [&](const Star& existing) {
                const float dx = existing.x - star->x;
                const float dy = existing.y - star->y;
                return dx * dx + dy * dy < minimum_distance * minimum_distance;
            });
        if (!duplicate) {
            fitted.push_back(*star);
            if (fitted.size() >= config_.max_stars) {
                break;
            }
        }
    }
    if (config_.refine_original && config_.binning == 2) {
        for (auto& star : fitted) refine_original_centroid(star, input);
    }
    result.stars = std::move(fitted);

    if (config_.collect_diagnostics) {
        result.diagnostics.width = image.width;
        result.diagnostics.height = image.height;
        result.diagnostics.background = std::move(background);
        result.diagnostics.noise = std::move(noise);
        result.diagnostics.normalized = std::move(normalized);
        result.diagnostics.response = std::move(best_response);
        result.diagnostics.mask = mask;
    }
    result.elapsed_ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - start).count();
    return result;
}

DetectionResult Detector::detect_pyramid(const ImageView& input,
                                         bool full_resolution) const {
    const auto start = std::chrono::steady_clock::now();
    DetectorConfig coarse = config_;
    coarse.refine_original = false;
    coarse.collect_diagnostics = false;
    coarse.min_support_pixels = 1; // A real star may occupy one coarse pixel.
    coarse.fit_radius = 3;
    coarse.min_separation = 2.0F;
    auto result = Detector(coarse).detect(input);
    if (!result.ok()) return result;

    DetectorConfig fine = config_;
    fine.binning = 2;
    fine.max_stars = 8;
    fine.refine_original = false;
    fine.collect_diagnostics = false;
    const Detector half_detector(fine);
    fine.binning = 1;
    const Detector full_detector(fine);

    const auto local = [&](const Star& seed, const Detector& detector,
                           int side, float search_radius) -> std::optional<Star> {
        if (input.width < static_cast<std::size_t>(side) ||
            input.height < static_cast<std::size_t>(side)) return std::nullopt;
        // Even ROI origins retain the full-frame 2x2 bin phase. ImageView
        // preserves the original stride; no full-resolution image is copied.
        const int left = std::clamp(static_cast<int>(std::lround(seed.x)) - side/2,
            0, static_cast<int>(input.width) - side) / 2 * 2;
        const int top = std::clamp(static_cast<int>(std::lround(seed.y)) - side/2,
            0, static_cast<int>(input.height) - side) / 2 * 2;
        const auto patch = detector.detect({input.data +
            static_cast<std::size_t>(top)*input.stride + static_cast<std::size_t>(left),
            static_cast<std::size_t>(side), static_cast<std::size_t>(side),
            input.stride, input.max_value});
        std::optional<Star> best;
        float distance = search_radius;
        for (auto star : patch.stars) {
            star.x += static_cast<float>(left);
            star.y += static_cast<float>(top);
            const float current = std::hypot(star.x-seed.x, star.y-seed.y);
            if (current < distance) { best = star; distance = current; }
        }
        return best;
    };
    std::vector<Star> refined;
    for (const auto& seed : result.stars) {
        auto star = local(seed, half_detector, 64, 8.0F);
        if (!star) continue;
        if (full_resolution) {
            auto original = local(*star, full_detector, 32, 4.0F);
            if (!original) continue;
            // Change only coordinates at the last step to isolate astrometry
            // from the candidate ranking obtained at the 2x stage.
            star->x = original->x;
            star->y = original->y;
        }
        const bool duplicate = std::any_of(refined.begin(), refined.end(),
            [&](const Star& previous) {
                return std::hypot(previous.x-star->x, previous.y-star->y) <
                    2.0F*config_.min_separation;
            });
        if (!duplicate) refined.push_back(*star);
    }
    std::stable_sort(refined.begin(), refined.end(), [](const Star& a, const Star& b) {
        return a.response_sigma > b.response_sigma;
    });
    result.stars = std::move(refined);
    result.elapsed_ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now()-start).count();
    return result;
}

}  // namespace mf_detect_star
