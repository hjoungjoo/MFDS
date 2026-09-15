// SPDX-License-Identifier: LicenseRef-Cedar-FSL-1.1-MIT-5year
// Standalone Linux image/centroid worker. No PiFinder or Python dependencies.
#include "mf_detect_star/c_api.h"
#include <bit>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <limits>
#include <locale>
#include <sstream>
#include <string>
#include <vector>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace {
constexpr std::size_t max_bytes = 64 * 1024 * 1024;
bool read_line(std::string& line) {
    line.clear();
    char c;
    while (std::cin.get(c)) {
        if (c == '\n') return true;
        if (line.size() >= 512) return false;
        line.push_back(c);
    }
    return false;
}
}

int main(int argc, char** argv) {
    static_assert(std::endian::native == std::endian::little);
    static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559);
    if (argc == 2 && std::string(argv[1]) == "--version") {
        std::cout << "MFDS " << mfds_version() << "\n";
        return 0;
    }
    if (argc == 2 && std::string(argv[1]) == "--help") {
        std::cout << "mf_detect_star_server --shm-fd FD --capacity BYTES\n"
                     "Persistent MFDS1 worker: uint16 little-endian image memory,\n"
                     "stdin requests, stdout headers + float32 y/x/flux results.\n"
                     "See docs/PROCESS_PROTOCOL.md.\n";
        return 0;
    }
    if (argc != 5 || std::string(argv[1]) != "--shm-fd" ||
        std::string(argv[3]) != "--capacity") return 2;
    int fd;
    std::size_t bytes;
    try {
        std::size_t used = 0;
        fd = std::stoi(argv[2], &used);
        if (used != std::string(argv[2]).size() || fd < 3) return 2;
        bytes = std::stoull(argv[4], &used);
        if (used != std::string(argv[4]).size() || bytes == 0 || bytes > max_bytes)
            return 2;
    } catch (...) { return 2; }
    struct stat info{};
    if (fstat(fd, &info) != 0 || !S_ISREG(info.st_mode) || info.st_size < 0 ||
        static_cast<std::uint64_t>(info.st_size) < bytes) return 2;
    // Also exit after abrupt parent death, even if another child inherited a pipe.
    const auto parent = getppid();
    if (prctl(PR_SET_PDEATHSIG, SIGTERM) != 0 || getppid() != parent || parent == 1)
        return 2;
    void* memory = mmap(nullptr, bytes, PROT_READ, MAP_SHARED, fd, 0);
    close(fd);
    if (memory == MAP_FAILED) return 2;
    std::locale::global(std::locale::classic());
    std::cout << std::setprecision(17) << "MFDS1 READY\n" << std::flush;
    std::string line;
    while (read_line(line)) {
        std::istringstream request(line);
        std::string magic, extra;
        std::uint64_t sequence = 0, stamp = 0;
        std::size_t width = 0, height = 0, capacity = 0;
        unsigned saturation = 0;
        int binning = 0, mode = -1;
        float sigma = 0;
        if (!(request >> magic >> sequence >> stamp >> width >> height >> saturation
                      >> binning >> sigma >> mode >> capacity) || request >> extra ||
            magic != "MFDS1") break;
        int count = -1;
        double elapsed = 0;
        std::vector<float> output;
        if (width > 0 && height > 0 && width <= 16384 && height <= 16384 &&
            width <= bytes / sizeof(std::uint16_t) / height &&
            saturation > 0 && saturation <= 65535 && capacity > 0 && capacity <= 4096 &&
            (binning == 1 || binning == 2 || binning == 4 || binning == 8) &&
            std::isfinite(sigma) && sigma > 0 && mode >= 0 && mode <= 3) {
            output.resize(capacity * 3);
            auto detect = mfds_detect_u16;
            if (mode == 1) detect = mfds_detect_u16_refined;
            if (mode == 2) detect = mfds_detect_u16_pyramid;
            if (mode == 3) detect = mfds_detect_u16_pyramid_full;
            count = detect(static_cast<const std::uint16_t*>(memory), width, height,
                           width, saturation, binning, sigma, output.data(), capacity,
                           &elapsed);
        }
        std::cout << "MFDS1 " << sequence << ' ' << stamp << ' '
                  << (count < 0 ? count : 0) << ' ' << (count < 0 ? 0 : count)
                  << ' ' << elapsed << '\n';
        if (count > 0) std::cout.write(reinterpret_cast<const char*>(output.data()),
            static_cast<std::streamsize>(count) * 3 * sizeof(float));
        std::cout.flush();
        if (!std::cout) break;
    }
    munmap(memory, bytes);
    return 0;
}
