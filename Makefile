CXX ?= c++
PKG_CONFIG ?= pkg-config
.DEFAULT_GOAL := all

BUILD_DIR := build
HAVE_LIBPNG := $(shell $(PKG_CONFIG) --exists libpng && printf 1 || printf 0)
PNG_CFLAGS := $(shell $(PKG_CONFIG) --cflags libpng 2>/dev/null)
PNG_LIBS := $(shell $(PKG_CONFIG) --libs libpng 2>/dev/null)

CPPFLAGS += -Iinclude -Isrc -I$(BUILD_DIR) -DMFDS_HAVE_LIBPNG=$(HAVE_LIBPNG) $(PNG_CFLAGS)
CXXFLAGS ?= -O3 -g
CXXFLAGS += -std=c++20 -Wall -Wextra -Wpedantic -Wconversion -Wshadow
LDLIBS += $(PNG_LIBS)

# Baseline AArch64 code also runs on Pi 4; never tune this library to the host
# Pi 5 instruction set. Other targets build an unavailable-backend stub.
TARGET_TRIPLE := $(shell $(CXX) -dumpmachine)
REDUCE_ARCH_FLAGS := $(if $(findstring aarch64,$(TARGET_TRIPLE)),-march=armv8-a -mtune=generic,)

COMMON_OBJECTS := $(BUILD_DIR)/detector.o
CLI_OBJECTS := $(COMMON_OBJECTS) $(BUILD_DIR)/image_io.o $(BUILD_DIR)/main.o
TEST_OBJECTS := $(COMMON_OBJECTS) $(BUILD_DIR)/self_test.o

.PHONY: all runtime test clean info license-notices

# Optional OpenGL ES 3.1 compute backend. CPU builds need no EGL/GLES headers.
.PHONY: gpu
gpu: $(BUILD_DIR)/libmf_preprocess_gpu.so

$(BUILD_DIR)/libmf_preprocess_gpu.so: integrations/pifinder/native/preprocess_gpu.cpp | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -fPIC -shared $< -o $@.tmp -lEGL -lGLESv2 -pthread
	mv $@.tmp $@

.PHONY: preprocess
preprocess: $(BUILD_DIR)/libmf_temporal_reduce.so

$(BUILD_DIR)/libmf_temporal_reduce.so: integrations/pifinder/native/temporal_reduce.cpp integrations/pifinder/native/temporal_reduce.h | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $(REDUCE_ARCH_FLAGS) -fno-fast-math -ffp-contract=off -fPIC -shared $< -o $@.tmp
	mv $@.tmp $@

all: license-notices preprocess $(BUILD_DIR)/mf_detect_star $(BUILD_DIR)/mf_detect_star_tests $(BUILD_DIR)/libmf_detect_star.so $(BUILD_DIR)/mf_detect_star_server

# Production process transport. Keep CLI, ctypes and tests in the all target
# for development and comparisons. Include the optional CPU preprocessing helper.
runtime: license-notices preprocess $(BUILD_DIR)/mf_detect_star_server

$(BUILD_DIR)/mf_detect_star_server: src/server.cpp src/c_api.cpp $(COMMON_OBJECTS) include/mf_detect_star/c_api.h $(BUILD_DIR)/mfds_version.hpp | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) src/server.cpp src/c_api.cpp $(COMMON_OBJECTS) -o $@.tmp
	mv $@.tmp $@

$(BUILD_DIR)/libmf_detect_star.so: src/c_api.cpp src/detector.cpp include/mf_detect_star/detector.hpp include/mf_detect_star/c_api.h $(BUILD_DIR)/mfds_version.hpp | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -fPIC -shared src/c_api.cpp src/detector.cpp -o $@.tmp
	mv $@.tmp $@

license-notices: | $(BUILD_DIR)
	mkdir -p $(BUILD_DIR)/licenses
	cp LICENSE LICENSING.md $(BUILD_DIR)/licenses/
	cp LICENSES/MIT-legacy.txt LICENSES/GPL-3.0.txt $(BUILD_DIR)/licenses/

info:
	@printf 'CXX=%s\nHAVE_LIBPNG=%s\n' '$(CXX)' '$(HAVE_LIBPNG)'

test: $(BUILD_DIR)/mf_detect_star_tests $(BUILD_DIR)/mf_temporal_reduce_tests
	$(BUILD_DIR)/mf_detect_star_tests
	$(BUILD_DIR)/mf_temporal_reduce_tests

$(BUILD_DIR)/mf_temporal_reduce_tests: integrations/pifinder/native/temporal_reduce_test.cpp integrations/pifinder/native/temporal_reduce.h $(BUILD_DIR)/libmf_temporal_reduce.so
	$(CXX) $(CXXFLAGS) $(REDUCE_ARCH_FLAGS) -fno-fast-math -ffp-contract=off -Iintegrations/pifinder/native $< -L$(BUILD_DIR) -Wl,-rpath,'$$ORIGIN' -lmf_temporal_reduce -o $@

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BUILD_DIR)/detector.o: src/detector.cpp include/mf_detect_star/detector.hpp | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@

$(BUILD_DIR)/image_io.o: src/image_io.cpp src/image_io.hpp | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@

$(BUILD_DIR)/main.o: src/main.cpp src/image_io.hpp include/mf_detect_star/detector.hpp $(BUILD_DIR)/mfds_version.hpp | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@

$(BUILD_DIR)/self_test.o: tests/self_test.cpp include/mf_detect_star/detector.hpp | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@

$(BUILD_DIR)/mf_detect_star: $(CLI_OBJECTS)
	$(CXX) $(CXXFLAGS) $^ $(LDLIBS) -o $@

$(BUILD_DIR)/mf_detect_star_tests: $(TEST_OBJECTS)
	$(CXX) $(CXXFLAGS) $^ -o $@

clean:
	rm -rf $(BUILD_DIR)

$(BUILD_DIR)/mfds_version.hpp: VERSION tools/version.py | $(BUILD_DIR)
	python3 tools/version.py --header $@
