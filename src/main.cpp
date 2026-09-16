// SPDX-License-Identifier: LicenseRef-MFDS-FSL-1.1-MIT-5year
#include "image_io.hpp"
#include "mfds_version.hpp"
#include "mf_detect_star/detector.hpp"

#include <cstdlib>
#include <exception>
#include <iomanip>
#include <iostream>
#include <string>

namespace {

struct CliOptions {
    mf_detect_star::DetectorConfig detector;
    mf_detect_star::RawInputOptions raw;
    std::string input;
    std::string diagnostic_prefix;
    bool csv = false;
};

void print_usage(std::ostream& output) {
    output <<
        "Usage: mf_detect_star [options] IMAGE\n"
        "\n"
        "Standalone light-pollution/cloud-aware star candidate detector.\n"
        "Input: PNG (when libpng is available), P5 PGM, or little-endian RAW16.\n"
        "\n"
        "Options:\n"
        "  --bin 1|2             Detection binning (default: 1)\n"
        "  --mesh PIXELS         Background mesh in input pixels (default: 32)\n"
        "  --sigma VALUE         Zero-sum PSF response threshold (default: 4.5)\n"
        "  --noise-floor VALUE   Minimum local noise in input ADU (default: 1.0)\n"
        "  --max-stars N         Maximum returned candidates (default: 64)\n"
        "  --diag-prefix PATH    Write *_background/noise/z/response/mask.pgm\n"
        "  --csv                 Emit CSV instead of JSON\n"
        "  --width N             RAW16 active width\n"
        "  --height N            RAW16 height\n"
        "  --stride N            RAW16 row stride in uint16 samples\n"
        "  --max-value N         RAW16 sensor full scale (default: 4095)\n"
        "  --version             Show MFDS release version\n"
        "  -h, --help            Show this help\n";
}

bool take_value(int& index, int argc, char** argv, std::string& value,
                std::string& error) {
    if (index + 1 >= argc) {
        error = std::string("missing value after ") + argv[index];
        return false;
    }
    value = argv[++index];
    return true;
}

bool parse_cli(int argc, char** argv, CliOptions& options, std::string& error) {
    try {
        for (int index = 1; index < argc; ++index) {
            const std::string argument = argv[index];
            std::string value;
            if (argument == "-h" || argument == "--help") {
                print_usage(std::cout);
                std::exit(0);
            } else if (argument == "--version") {
                std::cout << "MFDS " << MFDS_VERSION << "\n";
                std::exit(0);
            } else if (argument == "--csv") {
                options.csv = true;
            } else if (argument == "--bin") {
                if (!take_value(index, argc, argv, value, error)) return false;
                options.detector.binning = std::stoi(value);
            } else if (argument == "--mesh") {
                if (!take_value(index, argc, argv, value, error)) return false;
                options.detector.mesh_size = std::stoi(value);
            } else if (argument == "--sigma") {
                if (!take_value(index, argc, argv, value, error)) return false;
                options.detector.detection_sigma = std::stof(value);
            } else if (argument == "--noise-floor") {
                if (!take_value(index, argc, argv, value, error)) return false;
                options.detector.noise_floor = std::stof(value);
            } else if (argument == "--max-stars") {
                if (!take_value(index, argc, argv, value, error)) return false;
                options.detector.max_stars = static_cast<std::size_t>(std::stoull(value));
            } else if (argument == "--diag-prefix") {
                if (!take_value(index, argc, argv, value, error)) return false;
                options.diagnostic_prefix = value;
            } else if (argument == "--width") {
                if (!take_value(index, argc, argv, value, error)) return false;
                options.raw.width = static_cast<std::size_t>(std::stoull(value));
            } else if (argument == "--height") {
                if (!take_value(index, argc, argv, value, error)) return false;
                options.raw.height = static_cast<std::size_t>(std::stoull(value));
            } else if (argument == "--stride") {
                if (!take_value(index, argc, argv, value, error)) return false;
                options.raw.stride = static_cast<std::size_t>(std::stoull(value));
            } else if (argument == "--max-value") {
                if (!take_value(index, argc, argv, value, error)) return false;
                const auto maximum = std::stoul(value);
                if (maximum == 0UL || maximum > 65535UL) {
                    throw std::invalid_argument("max-value must be 1..65535");
                }
                options.raw.max_value = static_cast<std::uint16_t>(maximum);
            } else if (!argument.empty() && argument.front() == '-') {
                error = "unknown option: " + argument;
                return false;
            } else if (options.input.empty()) {
                options.input = argument;
            } else {
                error = "more than one input image was provided";
                return false;
            }
        }
    } catch (const std::exception& exception) {
        error = std::string("invalid option value: ") + exception.what();
        return false;
    }
    if (options.input.empty()) {
        error = "an input image is required";
        return false;
    }
    options.detector.collect_diagnostics = !options.diagnostic_prefix.empty();
    return true;
}

void emit_json(const mf_detect_star::OwnedImage& image,
               const mf_detect_star::DetectionResult& result) {
    std::cout << std::fixed << std::setprecision(4);
    std::cout << "{\n"
              << "  \"image\": {\"width\": " << image.width
              << ", \"height\": " << image.height
              << ", \"max_value\": " << image.max_value << "},\n"
              << "  \"elapsed_ms\": " << result.elapsed_ms << ",\n"
              << "  \"quality\": {\n"
              << "    \"global_background\": " << result.quality.global_background << ",\n"
              << "    \"global_noise\": " << result.quality.global_noise << ",\n"
              << "    \"masked_fraction\": " << result.quality.masked_fraction << ",\n"
              << "    \"mesh_cells\": " << result.quality.mesh_cells << ",\n"
              << "    \"thin_cloud_cells\": " << result.quality.thin_cloud_cells << ",\n"
              << "    \"invalid_cells\": " << result.quality.invalid_cells << "\n"
              << "  },\n"
              << "  \"stars\": [\n";
    for (std::size_t index = 0; index < result.stars.size(); ++index) {
        const auto& star = result.stars[index];
        std::cout << "    {\"x\": " << star.x
                  << ", \"y\": " << star.y
                  << ", \"flux\": " << star.flux
                  << ", \"response_sigma\": " << star.response_sigma
                  << ", \"peak_sigma\": " << star.peak_sigma
                  << ", \"fwhm\": " << star.fwhm
                  << ", \"eccentricity\": " << star.eccentricity
                  << ", \"psf_sigma\": " << star.psf_sigma
                  << ", \"flags\": " << star.flags << '}';
        std::cout << (index + 1U == result.stars.size() ? "\n" : ",\n");
    }
    std::cout << "  ]\n}\n";
}

void emit_csv(const mf_detect_star::DetectionResult& result) {
    std::cout << "x,y,flux,response_sigma,peak_sigma,fwhm,eccentricity,psf_sigma,flags\n";
    std::cout << std::fixed << std::setprecision(5);
    for (const auto& star : result.stars) {
        std::cout << star.x << ',' << star.y << ',' << star.flux << ','
                  << star.response_sigma << ',' << star.peak_sigma << ','
                  << star.fwhm << ',' << star.eccentricity << ','
                  << star.psf_sigma << ',' << star.flags << '\n';
    }
}

bool write_diagnostics(const std::string& prefix,
                       const mf_detect_star::Diagnostics& diagnostics,
                       std::string& error) {
    if (!mf_detect_star::write_float_pgm(prefix + "_background.pgm",
            diagnostics.background, diagnostics.width, diagnostics.height,
            0.01F, 0.99F, error)) return false;
    if (!mf_detect_star::write_float_pgm(prefix + "_noise.pgm",
            diagnostics.noise, diagnostics.width, diagnostics.height,
            0.01F, 0.99F, error)) return false;
    if (!mf_detect_star::write_float_pgm(prefix + "_z.pgm",
            diagnostics.normalized, diagnostics.width, diagnostics.height,
            0.01F, 0.995F, error)) return false;
    if (!mf_detect_star::write_float_pgm(prefix + "_response.pgm",
            diagnostics.response, diagnostics.width, diagnostics.height,
            0.01F, 0.999F, error)) return false;
    return mf_detect_star::write_mask_pgm(prefix + "_mask.pgm",
        diagnostics.mask, diagnostics.width, diagnostics.height, error);
}

}  // namespace

int main(int argc, char** argv) {
    CliOptions options;
    std::string error;
    if (!parse_cli(argc, argv, options, error)) {
        std::cerr << "error: " << error << "\n\n";
        print_usage(std::cerr);
        return 2;
    }

    mf_detect_star::OwnedImage image;
    if (!mf_detect_star::load_image(options.input, options.raw, image, error)) {
        std::cerr << "error: " << error << '\n';
        return 3;
    }

    try {
        const mf_detect_star::Detector detector(options.detector);
        const mf_detect_star::ImageView view{
            image.pixels.data(), image.width, image.height, image.width, image.max_value};
        const auto result = detector.detect(view);
        if (!result.ok()) {
            std::cerr << "error: " << result.error << '\n';
            return 4;
        }
        if (!options.diagnostic_prefix.empty() &&
            !write_diagnostics(options.diagnostic_prefix, result.diagnostics, error)) {
            std::cerr << "error: " << error << '\n';
            return 5;
        }
        if (options.csv) {
            emit_csv(result);
        } else {
            emit_json(image, result);
        }
    } catch (const std::exception& exception) {
        std::cerr << "error: " << exception.what() << '\n';
        return 6;
    }
    return 0;
}
