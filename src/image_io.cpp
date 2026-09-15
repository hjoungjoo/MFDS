// SPDX-License-Identifier: LicenseRef-Cedar-FSL-1.1-MIT-5year
#include "image_io.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>
#include <sstream>

#if MFDS_HAVE_LIBPNG
#include <png.h>
#endif

namespace mf_detect_star {
namespace {

std::string lowercase_extension(const std::string& path) {
    const auto dot = path.find_last_of('.');
    if (dot == std::string::npos) {
        return {};
    }
    std::string extension = path.substr(dot);
    std::transform(extension.begin(), extension.end(), extension.begin(),
                   [](unsigned char value) { return static_cast<char>(std::tolower(value)); });
    return extension;
}

bool read_pgm_token(std::istream& input, std::string& token) {
    token.clear();
    char value = 0;
    while (input.get(value)) {
        if (value == '#') {
            input.ignore(std::numeric_limits<std::streamsize>::max(), '\n');
            continue;
        }
        if (!std::isspace(static_cast<unsigned char>(value))) {
            token.push_back(value);
            break;
        }
    }
    while (input.get(value)) {
        if (std::isspace(static_cast<unsigned char>(value))) {
            return !token.empty();
        }
        token.push_back(value);
    }
    return !token.empty();
}

bool load_pgm(const std::string& path, OwnedImage& image, std::string& error) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        error = "cannot open PGM: " + path;
        return false;
    }
    std::string token;
    if (!read_pgm_token(input, token) || token != "P5") {
        error = "only binary P5 PGM is supported";
        return false;
    }
    try {
        if (!read_pgm_token(input, token)) {
            throw std::runtime_error("missing width");
        }
        image.width = static_cast<std::size_t>(std::stoull(token));
        if (!read_pgm_token(input, token)) {
            throw std::runtime_error("missing height");
        }
        image.height = static_cast<std::size_t>(std::stoull(token));
        if (!read_pgm_token(input, token)) {
            throw std::runtime_error("missing max value");
        }
        const auto maximum = std::stoul(token);
        if (maximum == 0UL || maximum > 65535UL || image.width == 0U ||
            image.height == 0U) {
            throw std::runtime_error("invalid PGM dimensions or max value");
        }
        image.max_value = static_cast<std::uint16_t>(maximum);
    } catch (const std::exception& exception) {
        error = std::string("invalid PGM header: ") + exception.what();
        return false;
    }

    image.pixels.resize(image.width * image.height);
    if (image.max_value <= 255U) {
        std::vector<unsigned char> bytes(image.pixels.size());
        input.read(reinterpret_cast<char*>(bytes.data()),
                   static_cast<std::streamsize>(bytes.size()));
        if (input.gcount() != static_cast<std::streamsize>(bytes.size())) {
            error = "truncated PGM pixel data";
            return false;
        }
        std::transform(bytes.begin(), bytes.end(), image.pixels.begin(),
                       [](unsigned char value) { return static_cast<std::uint16_t>(value); });
    } else {
        std::vector<unsigned char> bytes(image.pixels.size() * 2U);
        input.read(reinterpret_cast<char*>(bytes.data()),
                   static_cast<std::streamsize>(bytes.size()));
        if (input.gcount() != static_cast<std::streamsize>(bytes.size())) {
            error = "truncated PGM pixel data";
            return false;
        }
        for (std::size_t index = 0; index < image.pixels.size(); ++index) {
            image.pixels[index] = static_cast<std::uint16_t>(
                static_cast<std::uint16_t>(bytes[2U * index]) << 8U |
                static_cast<std::uint16_t>(bytes[2U * index + 1U]));
        }
    }
    return true;
}

bool load_raw16(const std::string& path, const RawInputOptions& options,
                OwnedImage& image, std::string& error) {
    if (options.width == 0U || options.height == 0U) {
        error = "RAW16 requires --width and --height";
        return false;
    }
    const std::size_t stride = options.stride == 0U ? options.width : options.stride;
    if (stride < options.width) {
        error = "RAW16 stride is smaller than width";
        return false;
    }
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        error = "cannot open RAW16: " + path;
        return false;
    }
    const std::size_t sample_count = stride * options.height;
    std::vector<unsigned char> bytes(sample_count * 2U);
    input.read(reinterpret_cast<char*>(bytes.data()),
               static_cast<std::streamsize>(bytes.size()));
    if (input.gcount() != static_cast<std::streamsize>(bytes.size())) {
        error = "truncated RAW16 data (expected little-endian uint16 rows)";
        return false;
    }

    image.width = options.width;
    image.height = options.height;
    image.max_value = options.max_value;
    image.pixels.resize(image.width * image.height);
    for (std::size_t y = 0; y < image.height; ++y) {
        for (std::size_t x = 0; x < image.width; ++x) {
            const std::size_t source = (y * stride + x) * 2U;
            image.pixels[y * image.width + x] = static_cast<std::uint16_t>(
                static_cast<std::uint16_t>(bytes[source]) |
                static_cast<std::uint16_t>(bytes[source + 1U]) << 8U);
        }
    }
    return true;
}

#if MFDS_HAVE_LIBPNG
bool load_png(const std::string& path, OwnedImage& image, std::string& error) {
    FILE* file = std::fopen(path.c_str(), "rb");
    if (file == nullptr) {
        error = "cannot open PNG: " + path;
        return false;
    }
    png_structp png = png_create_read_struct(PNG_LIBPNG_VER_STRING, nullptr, nullptr, nullptr);
    png_infop info = png == nullptr ? nullptr : png_create_info_struct(png);
    if (png == nullptr || info == nullptr) {
        if (png != nullptr) {
            png_destroy_read_struct(&png, nullptr, nullptr);
        }
        std::fclose(file);
        error = "cannot initialize libpng";
        return false;
    }
    if (setjmp(png_jmpbuf(png)) != 0) {
        png_destroy_read_struct(&png, &info, nullptr);
        std::fclose(file);
        error = "libpng failed while reading: " + path;
        return false;
    }

    png_init_io(png, file);
    png_read_info(png, info);
    const auto width = png_get_image_width(png, info);
    const auto height = png_get_image_height(png, info);
    int bit_depth = png_get_bit_depth(png, info);
    int color_type = png_get_color_type(png, info);
    if (color_type == PNG_COLOR_TYPE_PALETTE) {
        png_set_palette_to_rgb(png);
        color_type = PNG_COLOR_TYPE_RGB;
    }
    if (color_type == PNG_COLOR_TYPE_GRAY && bit_depth < 8) {
        png_set_expand_gray_1_2_4_to_8(png);
    }
    if (png_get_valid(png, info, PNG_INFO_tRNS) != 0U) {
        png_set_tRNS_to_alpha(png);
        color_type |= PNG_COLOR_MASK_ALPHA;
    }
    if ((color_type & PNG_COLOR_MASK_ALPHA) != 0) {
        png_set_strip_alpha(png);
    }
    if ((color_type & PNG_COLOR_MASK_COLOR) != 0) {
        png_set_rgb_to_gray_fixed(png, 1, -1, -1);
    }
#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
    if (bit_depth == 16) {
        png_set_swap(png);
    }
#endif
    png_read_update_info(png, info);
    bit_depth = png_get_bit_depth(png, info);
    const int channels = png_get_channels(png, info);
    const png_size_t row_bytes = png_get_rowbytes(png, info);
    if (channels != 1 || (bit_depth != 8 && bit_depth != 16)) {
        png_destroy_read_struct(&png, &info, nullptr);
        std::fclose(file);
        error = "PNG conversion did not produce 8/16-bit grayscale";
        return false;
    }
    std::vector<unsigned char> bytes(row_bytes * height);
    std::vector<png_bytep> rows(height);
    for (std::size_t y = 0; y < height; ++y) {
        rows[y] = bytes.data() + y * row_bytes;
    }
    png_read_image(png, rows.data());
    png_read_end(png, nullptr);
    png_destroy_read_struct(&png, &info, nullptr);
    std::fclose(file);

    image.width = width;
    image.height = height;
    image.max_value = bit_depth == 16 ? 65535U : 255U;
    image.pixels.resize(image.width * image.height);
    for (std::size_t y = 0; y < image.height; ++y) {
        for (std::size_t x = 0; x < image.width; ++x) {
            if (bit_depth == 8) {
                image.pixels[y * image.width + x] = bytes[y * row_bytes + x];
            } else {
                std::uint16_t value = 0;
                std::memcpy(&value, bytes.data() + y * row_bytes + 2U * x, sizeof(value));
                image.pixels[y * image.width + x] = value;
            }
        }
    }
    return true;
}
#endif

float quantile(std::vector<float> values, float fraction) {
    if (values.empty()) {
        return 0.0F;
    }
    const auto index = static_cast<std::size_t>(std::clamp(fraction, 0.0F, 1.0F) *
                                                static_cast<float>(values.size() - 1U));
    std::nth_element(values.begin(), values.begin() + static_cast<std::ptrdiff_t>(index),
                     values.end());
    return values[index];
}

}  // namespace

bool load_image(const std::string& path, const RawInputOptions& raw_options,
                OwnedImage& image, std::string& error) {
    const std::string extension = lowercase_extension(path);
    if (extension == ".pgm") {
        return load_pgm(path, image, error);
    }
    if (extension == ".raw" || extension == ".raw16" || extension == ".bin") {
        return load_raw16(path, raw_options, image, error);
    }
    if (extension == ".png") {
#if MFDS_HAVE_LIBPNG
        return load_png(path, image, error);
#else
        error = "PNG support was not built; install libpng-dev or use PGM/RAW16";
        return false;
#endif
    }
    error = "unsupported input type; use PNG, P5 PGM, or little-endian RAW16";
    return false;
}

bool write_float_pgm(const std::string& path, const std::vector<float>& values,
                     std::size_t width, std::size_t height, float low_quantile,
                     float high_quantile, std::string& error) {
    if (values.size() != width * height || values.empty()) {
        error = "invalid float diagnostic image";
        return false;
    }
    std::vector<float> finite;
    finite.reserve(values.size());
    std::copy_if(values.begin(), values.end(), std::back_inserter(finite),
                 [](float value) { return std::isfinite(value); });
    if (finite.empty()) {
        error = "diagnostic image has no finite values";
        return false;
    }
    const float low = quantile(finite, low_quantile);
    const float high = quantile(std::move(finite), high_quantile);
    const float scale = high > low ? 65535.0F / (high - low) : 1.0F;

    std::ofstream output(path, std::ios::binary);
    if (!output) {
        error = "cannot create diagnostic PGM: " + path;
        return false;
    }
    output << "P5\n" << width << ' ' << height << "\n65535\n";
    for (const float value : values) {
        const auto mapped = static_cast<std::uint16_t>(std::lround(std::clamp(
            (std::isfinite(value) ? value - low : 0.0F) * scale, 0.0F, 65535.0F)));
        const unsigned char bytes[2] = {
            static_cast<unsigned char>(mapped >> 8U),
            static_cast<unsigned char>(mapped & 0xffU),
        };
        output.write(reinterpret_cast<const char*>(bytes), 2);
    }
    if (!output) {
        error = "failed while writing diagnostic PGM: " + path;
        return false;
    }
    return true;
}

bool write_mask_pgm(const std::string& path,
                    const std::vector<std::uint8_t>& values,
                    std::size_t width, std::size_t height,
                    std::string& error) {
    if (values.size() != width * height) {
        error = "invalid mask diagnostic image";
        return false;
    }
    std::ofstream output(path, std::ios::binary);
    if (!output) {
        error = "cannot create mask PGM: " + path;
        return false;
    }
    output << "P5\n" << width << ' ' << height << "\n255\n";
    for (const auto value : values) {
        output.put(value == 0U ? static_cast<char>(0) : static_cast<char>(255));
    }
    if (!output) {
        error = "failed while writing mask PGM: " + path;
        return false;
    }
    return true;
}

}  // namespace mf_detect_star

