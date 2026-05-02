// SOURCE: https://github.com/mrdoob/three.js/issues/29721
// Minimal GL reproduction of the `ConeGeometry` missing-triangles bug for
// heightSegments > 1.
//
// We build a cone-side vertex grid with radialSegments = 8 and
// heightSegments = 3 (12 vertices per ring, 4 rings = 32 vertices). The
// broken index-generation path mimics three.js r169 `CylinderGeometry`:
// when `radiusTop == 0` (cone apex), the (a, b, d) triangle is skipped
// for EVERY strip instead of only the degenerate top one. Result: only
// 8 * 3 * 1 = 24 triangles instead of the correct 8 * 3 * 2 = 48, i.e.
// half the triangles missing. Rendered output: a row of gaps across the
// middle of the cone where pixels read the clear color instead of the
// cone's diffuse gray.

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
static const int RADIAL   = 8;
static const int HEIGHT_S = 3;

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

static const char* VS =
"#version 330 core\n"
"layout(location=0) in vec3 a_pos;\n"
"void main() { gl_Position = vec4(a_pos.x, a_pos.y, 0.0, 1.0); }\n";

static const char* FS =
"#version 330 core\n"
"out vec4 fragColor;\n"
"void main() { fragColor = vec4(0.63, 0.63, 0.63, 1.0); }\n";

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

    // Build vertex ring grid. (RADIAL+1) vertices per ring (seam duplicated),
    // (HEIGHT_S+1) rings along Y. Radii taper linearly: top apex at r=0,
    // bottom at r=0.7. Y rings evenly spaced in [-0.7, 0.7].
    int cols = RADIAL + 1;
    int rows = HEIGHT_S + 1;
    int nv = cols * rows;
    float* verts = malloc(sizeof(float) * 3 * nv);
    float radiusBottom = 0.7f;
    float radiusTop    = 0.0f;   // cone apex
    for (int y = 0; y < rows; y++) {
        float t  = (float)y / (float)HEIGHT_S;           // 0 = bottom ring
        float r  = radiusBottom * (1.0f - t) + radiusTop * t;
        float py = -0.7f + 1.4f * t;
        for (int x = 0; x < cols; x++) {
            float theta = (float)x / (float)RADIAL * 2.0f * 3.14159265f;
            verts[3*(y*cols + x) + 0] = r * cosf(theta);
            verts[3*(y*cols + x) + 1] = py;
            verts[3*(y*cols + x) + 2] = 0.0f;
        }
    }

    // ===================================================================
    // Emit index buffer the r169 buggy way. For each height strip `y` and
    // radial column `x`:
    //    a = (y  , x  ), b = (y+1, x  ),
    //    c = (y+1, x+1), d = (y  , x+1)
    // Broken condition: `radiusTop > 0` skips the (a,b,d) triangle on EVERY
    // strip when radiusTop is 0, even though only the topmost strip actually
    // degenerates. Analogous issue for radiusBottom.
    // ===================================================================
    unsigned short* idx = malloc(sizeof(unsigned short) * HEIGHT_S * RADIAL * 6);
    int nidx = 0;
    for (int y = 0; y < HEIGHT_S; y++) {
        for (int x = 0; x < RADIAL; x++) {
            unsigned short a = (unsigned short)((y    ) * cols + (x    ));
            unsigned short b = (unsigned short)((y + 1) * cols + (x    ));
            unsigned short c = (unsigned short)((y + 1) * cols + (x + 1));
            unsigned short d = (unsigned short)((y    ) * cols + (x + 1));

            // BUG: skips every strip, not just `y == HEIGHT_S - 1`.
            if (radiusTop > 0.0f) {
                idx[nidx++] = a; idx[nidx++] = b; idx[nidx++] = d;
            }
            // BUG: skips every strip, not just `y == 0`.
            if (radiusBottom > 0.0f) {
                idx[nidx++] = b; idx[nidx++] = c; idx[nidx++] = d;
            }
        }
    }
    // nidx should be 48 * 3 = 144 in the correct case; broken path yields
    // only the radiusBottom branch for all strips (since radiusTop = 0),
    // giving 24 * 3 = 72 indices — half.

    GLuint vao, vbo, ebo;
    glGenVertexArrays(1, &vao);
    glGenBuffers(1, &vbo);
    glGenBuffers(1, &ebo);
    glBindVertexArray(vao);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(float) * 3 * nv, verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, NULL);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, sizeof(unsigned short) * nidx, idx,
                 GL_STATIC_DRAW);

    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(prog);
    glDrawElements(GL_TRIANGLES, nidx, GL_UNSIGNED_SHORT, 0);
    glXSwapBuffers(dpy, win);

    unsigned char px[4];
    // Sample the middle strip — the row where triangles should exist
    // around y = 0.0 in NDC (middle of the cone).
    glReadPixels(W/2, H/2 - 20, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("middle-strip pixel rgba=%u,%u,%u,%u "
           "(expected ~160 gray, broken 0 background); nidx=%d (expected 144, broken 72)\n",
           px[0], px[1], px[2], px[3], nidx);

    free(verts);
    free(idx);
    glDeleteProgram(prog);
    glDeleteVertexArrays(1, &vao);
    glDeleteBuffers(1, &vbo);
    glDeleteBuffers(1, &ebo);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}
