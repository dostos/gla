// SOURCE: https://github.com/mrdoob/three.js/issues/33201
// Minimal GL reproduction of the anisotropic visibility-term div-by-zero bug
// that produces "black squares" on glass under direct lights.
//
// The fragment shader below reproduces the unguarded anisotropic visibility
// computation from three.js r183 `V_GGX_SmithCorrelated_Anisotropic`:
//
//     float v = 0.5 / (gv + gl);
//
// With the fragment-local tangent-space configuration set up here, `gv + gl`
// evaluates to 0.0, so `v` is `+Inf`. The output colour is then
// `albedo * v`, which after LDR clamp becomes pure black (0, 0, 0) — exactly
// the "small black squares" the reporter observed.

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
"void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }\n";

// Fragment: reproduces the unguarded 0.5 / (gv + gl) site. The per-pixel
// inputs `u_dotNL`, `u_alphaT`, `u_alphaB`, `u_dotTV`, `u_dotBV`, `u_dotNV`,
// `u_dotTL`, `u_dotBL` are set from the CPU so that `gv + gl == 0.0`. Under
// the fixed path, the denominator would be replaced with max(gv+gl, EPSILON).
static const char* FS =
"#version 330 core\n"
"uniform float u_dotNL;\n"
"uniform float u_dotNV;\n"
"uniform float u_alphaT;\n"
"uniform float u_alphaB;\n"
"uniform float u_dotTV;\n"
"uniform float u_dotBV;\n"
"uniform float u_dotTL;\n"
"uniform float u_dotBL;\n"
"uniform vec3  u_albedo;\n"
"out vec4 fragColor;\n"
"void main() {\n"
"    float gv = u_dotNL * length( vec3( u_alphaT * u_dotTV, u_alphaB * u_dotBV, u_dotNV ) );\n"
"    float gl = u_dotNV * length( vec3( u_alphaT * u_dotTL, u_alphaB * u_dotBL, u_dotNL ) );\n"
"    // THE BUG — unguarded division. Fix: 0.5 / max(gv + gl, EPSILON).\n"
"    float v  = 0.5 / ( gv + gl );\n"
"    vec3 col = u_albedo * v;\n"
"    fragColor = vec4(col, 1.0);\n"
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
        -1.0f, -1.0f,   1.0f, -1.0f,   1.0f,  1.0f,
        -1.0f, -1.0f,   1.0f,  1.0f,  -1.0f,  1.0f,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glGenBuffers(1, &vbo);
    glBindVertexArray(vao);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof quad, quad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL);

    glClearColor(0.3f, 0.3f, 0.3f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    glUseProgram(prog);
    glUniform3f(glGetUniformLocation(prog, "u_albedo"), 0.3f, 0.4f, 0.5f);
    // Pathological tangent-space configuration where both `gv` and `gl`
    // evaluate to zero: dotNL = dotNV = 0 makes both scalar prefactors 0,
    // so gv = gl = 0. (Alternative: alphaT = alphaB = 0 with dotNV = 0.)
    glUniform1f(glGetUniformLocation(prog, "u_dotNL"),  0.0f);
    glUniform1f(glGetUniformLocation(prog, "u_dotNV"),  0.0f);
    glUniform1f(glGetUniformLocation(prog, "u_alphaT"), 0.5f);
    glUniform1f(glGetUniformLocation(prog, "u_alphaB"), 0.5f);
    glUniform1f(glGetUniformLocation(prog, "u_dotTV"),  0.1f);
    glUniform1f(glGetUniformLocation(prog, "u_dotBV"),  0.1f);
    glUniform1f(glGetUniformLocation(prog, "u_dotTL"),  0.1f);
    glUniform1f(glGetUniformLocation(prog, "u_dotBL"),  0.1f);

    glDrawArrays(GL_TRIANGLES, 0, 6);
    glXSwapBuffers(dpy, win);

    unsigned char px[4];
    glReadPixels(W/2, H/2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center pixel rgba=%u,%u,%u,%u (expected ~70,80,100, broken 0,0,0)\n",
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
