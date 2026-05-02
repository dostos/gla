// SOURCE: https://github.com/mrdoob/three.js/pull/31528
// Minimal GL reproduction of the BloomNode/GaussianBlurNode "blocky halo"
// bug.
//
// A separable 1D Gaussian blur shader receives per-iteration coefficient
// weights through a uniform array. The host computes those coefficients
// using `sigma = kernelRadius` (broken: bell curve truncated at ±1 sigma,
// becomes a near-uniform box) instead of `sigma = kernelRadius / 3`
// (correct: bell curve covers ±3 sigma).
//
// The blur is applied (1D horizontal pass) to a rendered field that has a
// single bright spike at the framebuffer center. The expected output is a
// smooth Gaussian falloff to the left/right; the broken output is a
// near-uniform plateau the width of the kernel.
//
// We sample a pixel 6 px right of center: the analytic Gaussian intensity
// (sigma=4, kernelRadius=12) drops to ~25% (~mid-grey 60); the broken
// uniform-blur output is ~85% (saturating to 255).

#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const int W = 256, H = 256;
#define KERNEL_RADIUS 12

static GLuint compile_shader(GLenum kind, const char* src) {
    GLuint s = glCreateShader(kind);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok = 0; glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024]; glGetShaderInfoLog(s, sizeof log, NULL, log);
        fprintf(stderr, "shader compile failed: %s\n", log);
        exit(1);
    }
    return s;
}

static GLuint link_program(const char* vsrc, const char* fsrc) {
    GLuint vs = compile_shader(GL_VERTEX_SHADER, vsrc);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, fsrc);
    GLuint p = glCreateProgram();
    glAttachShader(p, vs); glAttachShader(p, fs);
    glLinkProgram(p);
    GLint ok = 0; glGetProgramiv(p, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[1024]; glGetProgramInfoLog(p, sizeof log, NULL, log);
        fprintf(stderr, "link failed: %s\n", log);
        exit(1);
    }
    glDeleteShader(vs); glDeleteShader(fs);
    return p;
}

// Pre-pass: render a single bright spike into the source texture.
static const char* SPIKE_VS =
"#version 330 core\n"
"layout(location=0) in vec2 a_pos;\n"
"void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }\n";

static const char* SPIKE_FS =
"#version 330 core\n"
"uniform vec2 u_size;\n"
"out vec4 fragColor;\n"
"void main() {\n"
"    vec2 c = gl_FragCoord.xy - u_size * 0.5;\n"
"    if (length(c) < 1.5) fragColor = vec4(1.0);\n"
"    else                 fragColor = vec4(0.0, 0.0, 0.0, 1.0);\n"
"}\n";

// Blur pass: separable 1D blur with uniform coefficient array.
// We sample the source texture at offsets ±i along the X axis and
// accumulate `coef[i] * sample`.
static const char* BLUR_VS =
"#version 330 core\n"
"layout(location=0) in vec2 a_pos;\n"
"out vec2 v_uv;\n"
"void main() { gl_Position = vec4(a_pos, 0.0, 1.0); v_uv = a_pos * 0.5 + 0.5; }\n";

#define KSTR_INNER "12"

static const char* BLUR_FS =
"#version 330 core\n"
"in vec2 v_uv;\n"
"uniform sampler2D u_src;\n"
"uniform vec2 u_invSize;\n"
"uniform float u_coef[" KSTR_INNER "];\n"
"out vec4 fragColor;\n"
"void main() {\n"
"    vec3 sum = texture(u_src, v_uv).rgb * u_coef[0];\n"
"    for (int i = 1; i < " KSTR_INNER "; ++i) {\n"
"        vec2 off = vec2(float(i) * u_invSize.x, 0.0);\n"
"        sum += (texture(u_src, v_uv + off).rgb + texture(u_src, v_uv - off).rgb)\n"
"               * u_coef[i];\n"
"    }\n"
"    fragColor = vec4(sum, 1.0);\n"
"}\n";

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "cannot open display\n"); return 1; }
    int attribs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, attribs);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    swa.colormap   = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, W, H, 0, vi->depth,
        InputOutput, vi->visual, CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, win);

    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);
    glViewport(0, 0, W, H);

    // Off-screen FBO for the spike pass.
    GLuint tex = 0; glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, W, H, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    GLuint fbo = 0; glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_2D, tex, 0);

    float quad[] = {
        -1.0f, -1.0f,  1.0f, -1.0f,  1.0f,  1.0f,
        -1.0f, -1.0f,  1.0f,  1.0f, -1.0f,  1.0f,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glGenBuffers(1, &vbo);
    glBindVertexArray(vao);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof quad, quad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL);

    // ===== Spike pre-pass into the texture. =====
    GLuint spike_prog = link_program(SPIKE_VS, SPIKE_FS);
    glUseProgram(spike_prog);
    glUniform2f(glGetUniformLocation(spike_prog, "u_size"), (float)W, (float)H);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    // ===== Compute blur kernel coefficients (BUGGY: sigma = kernelRadius). =====
    // Pre-fix BloomNode/GaussianBlurNode used the kernel radius directly
    // as sigma. The bell curve only decays to ~60% at i = R, so the kernel
    // looks more like a top-hat than a Gaussian.
    float coef_buggy[KERNEL_RADIUS];
    {
        const float R = (float)KERNEL_RADIUS;
        for (int i = 0; i < KERNEL_RADIUS; ++i) {
            const float fi = (float)i;
            coef_buggy[i] = 0.39894f * expf(-0.5f * fi * fi / (R * R)) / R;
        }
    }
    // Post-fix path would be:
    //   sigma = R / 3.0f;
    //   coef_fix[i] = 0.39894 * exp(-0.5 * i*i / (sigma*sigma)) / sigma;

    // ===== Blur pass to default framebuffer. =====
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glClear(GL_COLOR_BUFFER_BIT);
    GLuint blur_prog = link_program(BLUR_VS, BLUR_FS);
    glUseProgram(blur_prog);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, tex);
    glUniform1i(glGetUniformLocation(blur_prog, "u_src"), 0);
    glUniform2f(glGetUniformLocation(blur_prog, "u_invSize"),
                1.0f / (float)W, 1.0f / (float)H);
    glUniform1fv(glGetUniformLocation(blur_prog, "u_coef"),
                 KERNEL_RADIUS, coef_buggy);
    glDrawArrays(GL_TRIANGLES, 0, 6);
    glXSwapBuffers(dpy, win);

    // Sample 6 px right of center.
    unsigned char px[4];
    glReadPixels(W/2 + 6, H/2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("pixel 6px right of center rgba=%u,%u,%u,%u "
           "(expected ~60,60,60 with sigma=R/3 Gaussian; "
           "broken ~255,255,255 with sigma=R box-like blur)\n",
           px[0], px[1], px[2], px[3]);
    printf("coef[0] = %f (expected ~0.23936 with sigma=R/3=4; "
           "broken ~0.07979 with sigma=R=12)\n", coef_buggy[0]);

    glDeleteProgram(spike_prog);
    glDeleteProgram(blur_prog);
    glDeleteTextures(1, &tex);
    glDeleteFramebuffers(1, &fbo);
    glDeleteVertexArrays(1, &vao);
    glDeleteBuffers(1, &vbo);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}
