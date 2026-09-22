// SPDX-License-Identifier: GPL-3.0-only
// Optional CFA-preserving DoG compute backend; CPU reference lives in integration.
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl31.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>

namespace {
std::mutex gpu_mutex;
unsigned display_users = 0;
constexpr const char* shader_source = R"GLSL(precision highp float;
precision highp int;
layout(local_size_x=16, local_size_y=8) in;
layout(std430, binding=0) readonly buffer Source { float src[]; };
layout(std430, binding=1) buffer Intermediate { vec2 tmp[]; };
layout(std430, binding=2) writeonly buffer Destination { float dst[]; };
uniform int width, height, axis;
uniform float kn[21], kb[21];
int reflect_index(int x, int n) {
    if (x >= 0 && x < n) return x;
    // GLSL ES leaves negative integer modulo undefined; reflect first.
    if (x < 0) x = -x-1;
    int r = x % (2*n);
    return r < n ? r : 2*n-1-r;
}
void main() {
    int x=int(gl_GlobalInvocationID.x), y=int(gl_GlobalInvocationID.y);
    if (x>=width || y>=height) return;
    int coord=axis==0 ? y : x;
    int size=axis==0 ? height : width;
    int phase=coord % period;
    int n=(size-1-phase)/period+1;
    float small=0.0, broad=0.0;
    for (int k=-rb; k<=rb; ++k) {
        int c=reflect_index(coord/period+k,n)*period+phase;
        int i=axis==0 ? c*width+x : y*width+c;
        vec2 v;
        if (axis==0) v=vec2(src[i]); else v=tmp[i];
        if (abs(k)<=rn) small += kn[k+rn]*v.x;
        broad += kb[k+rb]*v.y;
    }
    int i=y*width+x;
    if (axis==0) tmp[i]=vec2(small,broad);
    else dst[i]=max(small-broad,0.0);
}
)GLSL";

void require(bool ok, const char* message) {
    if (!ok) throw std::runtime_error(message);
}
void gl_check() { require(glGetError() == GL_NO_ERROR, "OpenGL compute operation failed"); }
void error_text(char* error, std::size_t size, const char* message) {
    if (error && size) std::snprintf(error, size, "%s", message);
}
struct GPU {
    EGLDisplay display = EGL_NO_DISPLAY;
    EGLContext context = EGL_NO_CONTEXT;
    GLuint program = 0;
    int program_period = 0;
    GLuint buffers[3] = {};
    std::size_t pixels = 0;
    std::string renderer;
    bool registered = false;
    ~GPU() {
        if (context != EGL_NO_CONTEXT) {
            if (eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, context)) {
                glDeleteBuffers(3, buffers);
                if (program) glDeleteProgram(program);
                eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
            }
            eglDestroyContext(display, context);
        }
        if (registered && --display_users == 0) eglTerminate(display);
        eglReleaseThread();
    }
    void init() {
        display = eglGetPlatformDisplay(EGL_PLATFORM_SURFACELESS_MESA, EGL_DEFAULT_DISPLAY, nullptr);
        require(display != EGL_NO_DISPLAY && eglInitialize(display, nullptr, nullptr), "EGL initialization failed");
        ++display_users;
        registered = true;
        require(eglBindAPI(EGL_OPENGL_ES_API), "EGL ES binding failed");
        const EGLint attrs[] = {EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT, EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_NONE};
        EGLConfig config;
        EGLint count = 0;
        require(eglChooseConfig(display, attrs, &config, 1, &count) && count == 1, "No EGL ES3 configuration");
        const EGLint ctx_attrs[] = {EGL_CONTEXT_MAJOR_VERSION, 3, EGL_CONTEXT_MINOR_VERSION, 1, EGL_NONE};
        context = eglCreateContext(display, config, EGL_NO_CONTEXT, ctx_attrs);
        require(context != EGL_NO_CONTEXT && eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, context), "No OpenGL ES 3.1 compute context");
        const auto* name = glGetString(GL_RENDERER);
        require(name != nullptr, "Missing GPU renderer");
        renderer = reinterpret_cast<const char*>(name);
        // This backend is validated for Raspberry Pi V3D only. In particular,
        // never report llvmpipe (CPU emulation) as hardware acceleration.
        require(renderer.find("V3D") != std::string::npos, "GPU backend requires Raspberry Pi V3D; software/other renderer rejected");
        compile_program(2);
        glGenBuffers(3, buffers);
        gl_check();
    }
    void compile_program(int period) {
        const int rn = static_cast<int>(4.0*std::max(0.5,0.8/period)+0.5);
        const int rb = static_cast<int>(4.0*std::max(1.0,2.5/period)+0.5);
        const std::string source = "#version 310 es\n#define period " + std::to_string(period) +
            "\n#define rn " + std::to_string(rn) + "\n#define rb " + std::to_string(rb) + "\n" + shader_source;
        const char* text = source.c_str();
        const GLuint shader = glCreateShader(GL_COMPUTE_SHADER);
        glShaderSource(shader, 1, &text, nullptr);
        glCompileShader(shader);
        GLint ok = 0;
        glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
        if (!ok) {
            char log[2048] = {};
            glGetShaderInfoLog(shader, sizeof(log), nullptr, log);
            glDeleteShader(shader);
            throw std::runtime_error(std::string("Compute shader: ") + log);
        }
        if (program) glDeleteProgram(program);
        program = glCreateProgram();
        glAttachShader(program, shader);
        glLinkProgram(program);
        glDeleteShader(shader);
        glGetProgramiv(program, GL_LINK_STATUS, &ok);
        require(ok != 0, "Compute program link failed");
        program_period = period;
        gl_check();
    }
    void integer(const char* name, int value) {
        glUniform1i(glGetUniformLocation(program, name), value);
    }
    void kernel(const char* name, double sigma) {
        const int radius = static_cast<int>(4.0*sigma+0.5);
        float weights[21] = {};
        double total = 0.0;
        for (int k=-radius; k<=radius; ++k) total += std::exp(-0.5*k*k/(sigma*sigma));
        for (int k=-radius; k<=radius; ++k) weights[k+radius] = static_cast<float>(std::exp(-0.5*k*k/(sigma*sigma))/total);
        glUniform1fv(glGetUniformLocation(program, name), 21, weights);
    }
    void run(const float* input, float* output, int width, int height, int period) {
        require(input && output && width > 0 && height > 0 && width <= 16384 && height <= 16384 && period >= 1 && period <= std::min(width,height), "Invalid GPU image dimensions or CFA period");
        if (program_period != period) compile_program(period);
        const auto count = static_cast<std::size_t>(width)*static_cast<std::size_t>(height);
        GLint64 limit = 0;
        glGetInteger64v(GL_MAX_SHADER_STORAGE_BLOCK_SIZE, &limit);
        require(count <= static_cast<std::size_t>(limit)/8, "Image exceeds GPU storage buffer limit");
        const auto bytes = static_cast<GLsizeiptr>(count*sizeof(float));
        for (unsigned i=0; i<3; ++i) {
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffers[i]);
            if (pixels != count) glBufferData(GL_SHADER_STORAGE_BUFFER, i==1 ? bytes*2 : bytes, nullptr, GL_DYNAMIC_COPY);
            glBindBufferBase(GL_SHADER_STORAGE_BUFFER, i, buffers[i]);
        }
        gl_check();
        pixels = count;
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffers[0]);
        glBufferSubData(GL_SHADER_STORAGE_BUFFER, 0, bytes, input);
        glUseProgram(program);
        integer("width", width); integer("height", height);
        kernel("kn", std::max(0.5, 0.8/period));
        kernel("kb", std::max(1.0, 2.5/period));
        for (int axis=0; axis<2; ++axis) {
            integer("axis", axis);
            glDispatchCompute(static_cast<GLuint>((width+15)/16), static_cast<GLuint>((height+7)/8), 1);
            glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT | GL_BUFFER_UPDATE_BARRIER_BIT);
        }
        gl_check();
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffers[2]);
        const void* mapped = glMapBufferRange(GL_SHADER_STORAGE_BUFFER, 0, bytes, GL_MAP_READ_BIT);
        require(mapped != nullptr, "GPU readback failed");
        std::memcpy(output, mapped, static_cast<std::size_t>(bytes));
        require(glUnmapBuffer(GL_SHADER_STORAGE_BUFFER) == GL_TRUE, "GPU output buffer invalidated");
        gl_check();
    }
};
} // namespace

// Call each handle on its creation thread; Python owns a dedicated executor.
extern "C" void* mf_gpu_create(char* error, std::size_t size) noexcept {
    std::lock_guard<std::mutex> lock(gpu_mutex);
    try {
        auto gpu = std::make_unique<GPU>();
        gpu->init();
        return gpu.release();
    } catch (const std::exception& e) { error_text(error,size,e.what()); return nullptr; }
}
extern "C" const char* mf_gpu_renderer(void* handle) noexcept {
    return handle ? static_cast<GPU*>(handle)->renderer.c_str() : "";
}
extern "C" int mf_gpu_dog(void* handle, const float* input, float* output,
                          int width, int height, int period, char* error, std::size_t size) noexcept {
    std::lock_guard<std::mutex> lock(gpu_mutex);
    try {
        require(handle != nullptr, "Missing GPU context");
        static_cast<GPU*>(handle)->run(input, output, width, height, period);
        return 0;
    } catch (const std::exception& e) { error_text(error,size,e.what()); return -1; }
}
extern "C" void mf_gpu_destroy(void* handle) noexcept {
    std::lock_guard<std::mutex> lock(gpu_mutex);
    delete static_cast<GPU*>(handle);
}
