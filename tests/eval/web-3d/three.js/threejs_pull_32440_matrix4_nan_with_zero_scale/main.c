// SOURCE: https://github.com/mrdoob/three.js/pull/32440
// Minimal GL reproduction of the Matrix4 NaN-when-scale-is-zero bug.
//
// The host computes a model-view-projection matrix following the same
// recipe `Matrix4.extractRotation()` uses: normalize each basis column by
// dividing through its length. When a column has length zero (e.g. the
// matrix came from `makeScale(0, 0, 0)`), the division produces +Infinity,
// which after subsequent matrix multiplication propagates to NaN throughout
// the result.
//
// The buggy `u_mvp` uniform contains NaN entries. The vertex shader
// transforms the triangle's positions by `u_mvp`; NaN-transformed vertices
// are clipped/clamped by the GPU, so the rasterized triangle either misses
// the framebuffer entirely or covers only spurious fragments. The center
// pixel reads the clear color (black) instead of the geometry's diffuse
// mid-gray.

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

// Vertex/fragment: pass-through with mat4 MVP transform.
static const char* VS =
"#version 330 core\n"
"layout(location=0) in vec2 a_pos;\n"
"uniform mat4 u_mvp;\n"
"void main() { gl_Position = u_mvp * vec4(a_pos, 0.0, 1.0); }\n";

static const char* FS =
"#version 330 core\n"
"out vec4 fragColor;\n"
"void main() { fragColor = vec4(0.7, 0.7, 0.7, 1.0); }\n";

// Mimic `Matrix4.extractRotation()` pre-fix:
// extract each basis column from `src` and divide it by its length.
// If `src` came from `makeScale(0,0,0)` then length == 0 and the
// division yields Infinity; subsequent matrix multiplications turn
// Infinity into NaN.
static void extract_rotation_buggy(const float* src16, float* dst16) {
    // src16 / dst16 are 4x4 column-major.
    // Column 0 = src[0..2], Column 1 = src[4..6], Column 2 = src[8..10].
    for (int col = 0; col < 3; ++col) {
        float x = src16[4*col + 0];
        float y = src16[4*col + 1];
        float z = src16[4*col + 2];
        float len = sqrtf(x*x + y*y + z*z);
        // BUGGY: no len-is-zero guard; division by zero -> +Inf.
        // Post-fix path would early-return identity here.
        dst16[4*col + 0] = x / len;
        dst16[4*col + 1] = y / len;
        dst16[4*col + 2] = z / len;
        dst16[4*col + 3] = 0.0f;
    }
    dst16[12] = 0.0f;
    dst16[13] = 0.0f;
    dst16[14] = 0.0f;
    dst16[15] = 1.0f;
}

// `makeScale(s, s, s)` 4x4.
static void make_scale(float sx, float sy, float sz, float* m16) {
    memset(m16, 0, 16 * sizeof(float));
    m16[0]  = sx;
    m16[5]  = sy;
    m16[10] = sz;
    m16[15] = 1.0f;
}

// Multiply a*b into out (column-major mat4).
static void mat4_mul(const float* a, const float* b, float* out) {
    float r[16];
    for (int c = 0; c < 4; ++c) {
        for (int row = 0; row < 4; ++row) {
            float s = 0.0f;
            for (int k = 0; k < 4; ++k) s += a[4*k + row] * b[4*c + k];
            r[4*c + row] = s;
        }
    }
    memcpy(out, r, sizeof r);
}

// Identity 4x4.
static void identity(float* m16) {
    memset(m16, 0, 16 * sizeof(float));
    m16[0] = m16[5] = m16[10] = m16[15] = 1.0f;
}

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

    GLuint prog = link_program(VS, FS);

    float quad[] = {
        -0.6f, -0.6f,  0.6f, -0.6f,  0.6f,  0.6f,
        -0.6f, -0.6f,  0.6f,  0.6f, -0.6f,  0.6f,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glGenBuffers(1, &vbo);
    glBindVertexArray(vao);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof quad, quad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL);

    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(prog);

    // Build the model matrix the way Object3D does:
    //   parent_world * makeScale(0, 0, 0)
    // then "extract rotation" the way Matrix4.extractRotation does.
    float scale_zero[16];
    make_scale(0.0f, 0.0f, 0.0f, scale_zero);

    float parent_world[16];
    identity(parent_world);

    float local[16];
    mat4_mul(parent_world, scale_zero, local);

    // Pre-fix path: extract_rotation_buggy on the zero-determinant matrix.
    // Post-fix path would short-circuit with identity instead.
    float rot[16];
    extract_rotation_buggy(local, rot);

    // u_mvp = rot   (placeholder; in the live path this is mvp = proj*view*world).
    glUniformMatrix4fv(glGetUniformLocation(prog, "u_mvp"), 1, GL_FALSE, rot);

    glDrawArrays(GL_TRIANGLES, 0, 6);
    glXSwapBuffers(dpy, win);

    unsigned char px[4];
    glReadPixels(W/2, H/2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center pixel rgba=%u,%u,%u,%u "
           "(expected ~180,180,180 with finite MVP; "
           "broken ~0,0,0 with NaN-filled MVP)\n",
           px[0], px[1], px[2], px[3]);

    // Print one element of the buggy rotation matrix to confirm NaN.
    printf("rot[0] = %f (expected 1.0; broken Inf or NaN)\n", rot[0]);

    glDeleteProgram(prog);
    glDeleteVertexArrays(1, &vao);
    glDeleteBuffers(1, &vbo);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}
