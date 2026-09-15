CXX ?= c++
PKG_CONFIG ?= pkg-config

BUILD_DIR := build
HAVE_LIBPNG := $(shell $(PKG_CONFIG) --exists libpng && printf 1 || printf 0)
PNG_CFLAGS := $(shell $(PKG_CONFIG) --cflags libpng 2>/dev/null)
PNG_LIBS := $(shell $(PKG_CONFIG) --libs libpng 2>/dev/null)

CPPFLAGS += -Iinclude -Isrc -DMFDS_HAVE_LIBPNG=$(HAVE_LIBPNG) $(PNG_CFLAGS)
CXXFLAGS ?= -O3 -g
CXXFLAGS += -std=c++20 -Wall -Wextra -Wpedantic -Wconversion -Wshadow
LDLIBS += $(PNG_LIBS)

COMMON_OBJECTS := $(BUILD_DIR)/detector.o
CLI_OBJECTS := $(COMMON_OBJECTS) $(BUILD_DIR)/image_io.o $(BUILD_DIR)/main.o
TEST_OBJECTS := $(COMMON_OBJECTS) $(BUILD_DIR)/self_test.o

.PHONY: all test clean info license-notices

all: license-notices $(BUILD_DIR)/mf_detect_star $(BUILD_DIR)/mf_detect_star_tests $(BUILD_DIR)/libmf_detect_star.so $(BUILD_DIR)/mf_detect_star_server

$(BUILD_DIR)/mf_detect_star_server: src/server.cpp src/c_api.cpp $(COMMON_OBJECTS) include/mf_detect_star/c_api.h | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) src/server.cpp src/c_api.cpp $(COMMON_OBJECTS) -o $@.tmp
	mv $@.tmp $@

$(BUILD_DIR)/libmf_detect_star.so: src/c_api.cpp src/detector.cpp include/mf_detect_star/detector.hpp include/mf_detect_star/c_api.h | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -fPIC -shared src/c_api.cpp src/detector.cpp -o $@.tmp
	mv $@.tmp $@

license-notices: | $(BUILD_DIR)
	mkdir -p $(BUILD_DIR)/licenses
	cp LICENSE LICENSING.md $(BUILD_DIR)/licenses/
	cp LICENSES/MIT-legacy.txt LICENSES/GPL-3.0.txt $(BUILD_DIR)/licenses/

info:
	@printf 'CXX=%s\nHAVE_LIBPNG=%s\n' '$(CXX)' '$(HAVE_LIBPNG)'

test: $(BUILD_DIR)/mf_detect_star_tests
	$(BUILD_DIR)/mf_detect_star_tests

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BUILD_DIR)/detector.o: src/detector.cpp include/mf_detect_star/detector.hpp | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@

$(BUILD_DIR)/image_io.o: src/image_io.cpp src/image_io.hpp | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@

$(BUILD_DIR)/main.o: src/main.cpp src/image_io.hpp include/mf_detect_star/detector.hpp | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@

$(BUILD_DIR)/self_test.o: tests/self_test.cpp include/mf_detect_star/detector.hpp | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@

$(BUILD_DIR)/mf_detect_star: $(CLI_OBJECTS)
	$(CXX) $(CXXFLAGS) $^ $(LDLIBS) -o $@

$(BUILD_DIR)/mf_detect_star_tests: $(TEST_OBJECTS)
	$(CXX) $(CXXFLAGS) $^ -o $@

clean:
	rm -rf $(BUILD_DIR)
