// SPDX-License-Identifier: LicenseRef-MFDS-FSL-1.1-MIT-5year
#include "image_io.hpp"

#include <cassert>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>

int main() {
    namespace fs = std::filesystem;
    using namespace mf_detect_star;
    const auto dir = fs::temp_directory_path() / ("mfds-image-test-" +
        std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    fs::create_directory(dir);
    const auto raw = dir / "test.raw16";
    std::ofstream(raw, std::ios::binary).close();
    OwnedImage image;
    std::string error;
    const auto maximum = std::numeric_limits<std::size_t>::max();
    for (const RawInputOptions options : {
            RawInputOptions{64, 32, maximum / 32 + 1, 4095},
            RawInputOptions{2, 1, maximum / 2 + 1, 4095},
            RawInputOptions{maximum, 2, maximum, 4095},
            RawInputOptions{1000000, 1000000, 1000000, 4095},
            RawInputOptions{2, 2, 1, 4095}}) {
        error.clear();
        assert(!load_image(raw.string(), options, image, error));
        assert(!error.empty());
    }
    {
        const unsigned char samples[] = {1, 0, 2, 0, 99, 0, 3, 0, 4, 0, 99, 0};
        std::ofstream output(raw, std::ios::binary);
        output.write(reinterpret_cast<const char*>(samples), sizeof(samples));
    }
    assert(load_image(raw.string(), {2, 2, 3, 4095}, image, error));
    assert(image.width == 2 && image.height == 2);
    assert(image.pixels == std::vector<std::uint16_t>({1, 2, 3, 4}));

    const auto pgm = dir / "test.pgm";
    for (const std::string& header : {
            "P5\n" + std::to_string(maximum) + " 2\n65535\n",
            std::string("P5\n1000000 1000000\n255\n"),
            std::string("P5\n2junk 2\n255\n"),
            std::string("P5\n-1 2\n255\n"),
            std::string("P5\n2 2\n65535\n")}) {
        std::ofstream(pgm, std::ios::binary) << header;
        assert(!load_image(pgm.string(), {}, image, error));
    }
    for (const int depth : {8, 16}) {
        {
            std::ofstream output(pgm, std::ios::binary);
            output << "P5\n2 2\n" << (depth == 8 ? 255 : 65535) << '\n';
            for (unsigned char value = 1; value <= 4; ++value) {
                if (depth == 16) output.put('\0');
                output.put(static_cast<char>(value));
            }
        }
        assert(load_image(pgm.string(), {}, image, error));
        assert(image.pixels == std::vector<std::uint16_t>({1, 2, 3, 4}));
    }
    fs::remove_all(dir);
    std::cout << "PASS image_io invalid sizes, truncated inputs, RAW16 stride and PGM 8/16-bit\n";
}
