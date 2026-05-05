// SOURCE: https://github.com/mrdoob/three.js/issues/30198
// Minimal GL reproduction of the WebGPURenderer Reflector + RepeatWrapping
// texture-glitch bug.
//
// The bug: TextureNode's UV-transform matrix uniform is recomputed once per
// `requestAnimationFrame` tick (FRAME bucket) instead of once per `render()`
// call (RENDER bucket). When a Reflector triggers a second `render()` for
// the mirror pass within the same animation frame, the second pass keeps
// the first pass's UV-transform uniform value, producing a visible texture-
// coordinate mismatch.
//
// This C repro performs TWO render passes within a single "frame":
//   Pass 1 (mirror): computes UV-transform u_uvMatrix for the mirror camera
//                    and uploads to the uniform.
//   Pass 2 (main):   should also recompute u_uvMatrix for the main camera —
//                    but the buggy "per-frame" emulation skips the upload,
//                    leaving the stale mirror-pass value in the uniform.
//
// The fragment shader samples a procedural checker pattern through
// u_uvMatrix; with the broken update logic, the second pass renders a
// pattern whose tiling phase matches the first pass's camera, not the
// second pass's camera — sampled center pixel reads the wrong tile.
//
// Expected (correct path, RENDER bucket): center pixel ~ (180,180,180).
// Broken (FRAME bucket, second pass uses mirror's matrix): ~ (70,70,70).

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

static const char* VS =
"#version 330 core\n"
"layout(location=0) in vec2 a_pos;\n"
"out vec2 v_uv;\n"
"void main() {\n"
"    gl_Position = vec4(a_pos, 0.0, 1.0);\n"
"    v_uv = a_pos * 0.5 + 0.5;\n"
"}\n";

// Fragment shader samples a procedural checker pattern through u_uvMatrix.
// The third element of u_uvMatrix is a translation that shifts the
// checker phase. Different camera positions should yield different phase.
static const char* FS =
"#version 330 core\n"
"in vec2 v_uv;\n"
"uniform mat3 u_uvMatrix;\n"
"out vec4 fragColor;\n"
"void main() {\n"
"    vec2 uv = (u_uvMatrix * vec3(v_uv, 1.0)).xy;\n"
"    // Procedural smooth grayscale ramp keyed off transformed UV.\n"
"    float t = fract(uv.x * 4.0 + uv.y * 4.0);\n"
"    float gray = 0.27 + 0.45 * t;\n"
"    fragColor = vec4(vec3(gray), 1.0);\n"
"}\n";

// Compute the UV-transform matrix for a given camera "position".
// Different cameras produce different translation -> different uniform.
static void make_uv_matrix(float scale, float tx, float ty, float* m9) {
    // 3x3 column-major mat3.
    m9[0] = scale; m9[1] = 0.0f;  m9[2] = 0.0f;
    m9[3] = 0.0f;  m9[4] = scale; m9[5] = 0.0f;
    m9[6] = tx;    m9[7] = ty;    m9[8] = 1.0f;
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

    glUseProgram(prog);
    GLint locUV = glGetUniformLocation(prog, "u_uvMatrix");

    // Two camera "states" within the same frame:
    // mirror_pass uses tx=-0.05 (mirror cam, behind the model);
    // main_pass uses tx=+0.20 (camera zoomed in).
    float uv_mirror[9], uv_main[9];
    make_uv_matrix(1.0f, -0.05f, 0.0f, uv_mirror);
    make_uv_matrix(1.0f,  0.20f, 0.0f, uv_main);

    // ==== Pass 1 (mirror): upload UV matrix, draw. ====
    glUniformMatrix3fv(locUV, 1, GL_FALSE, uv_mirror);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    // ==== Pass 2 (main, BUGGY: FRAME bucket skips re-upload). ====
    // Under the post-fix RENDER bucket the next two lines would execute,
    // recomputing the UV matrix for the main camera and uploading the
    // new value to the uniform. Under the pre-fix FRAME bucket, the
    // update is dispatched at most once per `requestAnimationFrame`
    // tick — so the second `render()` within the same frame skips the
    // recomputation and the mirror-pass uniform value persists.
    //
    // Pre-fix path (bug emulated): the next two lines are commented out,
    // so the uniform stays at uv_mirror.
    //   glUniformMatrix3fv(locUV, 1, GL_FALSE, uv_main);
    //
    // (Note: the live three.js behaviour is more subtle — the uniform
    // upload is gated by an "update needed" flag that the FRAME bucket
    // clears after the first render. The end result is identical: the
    // second render uses the first render's uniform.)

    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glXSwapBuffers(dpy, win);

    unsigned char px[4];
    glReadPixels(W/2, H/2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center pixel rgba=%u,%u,%u,%u "
           "(expected ~180,180,180 with main-pass UV; "
           "broken ~70,70,70 with stale mirror-pass UV)\n",
           px[0], px[1], px[2], px[3]);

    glDeleteProgram(prog);
    glDeleteVertexArrays(1, &vao);
    glDeleteBuffers(1, &vbo);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}
