// SOURCE: https://github.com/mrdoob/three.js/issues/26668
// Minimal GL reproduction of the HemisphereLightProbe over-brightness bug.
//
// The fragment shader below computes an "irradiance-scale" color as
//     final = albedo * u_shCoeff0
// where the shader is *defined* under the non-legacy lighting-model
// convention: `u_shCoeff0` should be the color multiplied by 1 / sqrt(PI).
// The CPU host below emulates three.js r156 and uploads
//     u_shCoeff0 = color * sqrt(PI)            (WRONG)
// instead of
//     u_shCoeff0 = color * (1.0 / sqrt(PI))    (CORRECT)
// i.e. an over-scale of PI. With albedo = (0.5, 0.5, 0.5) and
// color = (1, 1, 1), the expected center pixel is ~128 gray
// (0.5 * 1 / sqrt(PI) * sqrt(PI) = 0.5 under the correct path, then the
// shader multiplies back by sqrt(PI), etc); the broken path produces
// ~255 (saturates to white) — the ~PI× over-brightness the user saw.

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

// Vertex: full-screen quad (x, y in [-1, 1]).
static const char* VS =
"#version 330 core\n"
"layout(location=0) in vec2 a_pos;\n"
"void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }\n";

// Fragment: the shader follows the non-legacy convention. It multiplies
// the authored albedo by the uniform SH0 coefficient, then by sqrt(PI) to
// reconstruct the un-scaled irradiance. Under this convention the host
// MUST upload SH0 = color * (1/sqrt(PI)).
static const char* FS =
"#version 330 core\n"
"uniform vec3 u_albedo;\n"
"uniform vec3 u_shCoeff0;\n"
"out vec4 fragColor;\n"
"void main() {\n"
"    // Shader convention: SH0 carries color/sqrt(PI). Reconstruct irradiance.\n"
"    vec3 irradiance = u_shCoeff0 * sqrt(3.14159265359);\n"
"    fragColor = vec4(u_albedo * irradiance, 1.0);\n"
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

    GLuint prog = link_program(VS, FS);

    float quad[] = {
        -1.0f, -1.0f,
         1.0f, -1.0f,
         1.0f,  1.0f,
        -1.0f, -1.0f,
         1.0f,  1.0f,
        -1.0f,  1.0f,
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

    // Albedo = middle-gray diffuse surface.
    glUniform3f(glGetUniformLocation(prog, "u_albedo"), 0.5f, 0.5f, 0.5f);

    // Authored light: white sky-ground sum = (1,1,1).
    const float color_r = 1.0f, color_g = 1.0f, color_b = 1.0f;

    // ==== The bug: compute SH order-0 coefficient the r156 way. ====
    // Reproduces the pre-fix HemisphereLightProbe.js constructor.
    const float sqrt_pi = sqrtf(3.14159265359f);
    const float c0_broken = sqrt_pi;              // WRONG (pre-fix value)
    // const float c0_fixed  = 1.0f / sqrt_pi;    // CORRECT (post-fix value)

    float sh0_r = color_r * c0_broken;
    float sh0_g = color_g * c0_broken;
    float sh0_b = color_b * c0_broken;

    // Upload the broken coefficient. Under the shader's sqrt(PI) rescale,
    // the rendered pixel is now albedo * color * PI = 0.5 * 1 * 3.14 = ~1.57
    // which saturates to 255 instead of the expected ~128.
    glUniform3f(glGetUniformLocation(prog, "u_shCoeff0"), sh0_r, sh0_g, sh0_b);

    glDrawArrays(GL_TRIANGLES, 0, 6);
    glXSwapBuffers(dpy, win);

    unsigned char px[4];
    glReadPixels(W/2, H/2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center pixel rgba=%u,%u,%u,%u (expected ~128,128,128, broken ~255,255,255)\n",
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
