// SOURCE: https://github.com/mrdoob/three.js/issues/21483
// Minimal GL reproduction of the "no shadows on Windows when geometry lacks
// a normal attribute" bug.
//
// The vertex shader below unconditionally computes
//     vShadowWorldNormal = inverseTransformDirection(transformedNormal, V)
// just like the three.js r148 `shadowmap_vertex` chunk — without a
// `HAS_NORMAL` guard. The draw call binds ONLY a position attribute; the
// `a_normal` attribute array is NOT enabled. Under Windows ANGLE/D3D11 the
// unbound attribute reads frequently yield NaN, which this reproducer
// models by uploading an explicit (NaN, NaN, NaN) vertex-constant-attribute
// via glVertexAttrib3f + a NaN value. The NaN then flows through
// shadowWorldNormal -> shadowWorldPosition -> shadow-space coord, and the
// simulated "PCF sample" returns 1.0 (fully lit), giving a fully lit pixel
// where a shadow was expected.

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

// Vertex shader matches the shape of three.js' shadowmap_vertex chunk.
static const char* VS =
"#version 330 core\n"
"layout(location=0) in vec3 a_pos;\n"
"layout(location=1) in vec3 a_normal;\n"
"uniform float u_normalBias;\n"
"out vec3 vShadowWorldNormal;\n"
"out vec3 vShadowWorldPosition;\n"
"void main() {\n"
"    // three.js shadowmap_vertex:\n"
"    //   vec3 shadowWorldNormal = inverseTransformDirection(transformedNormal, viewMatrix);\n"
"    //   vec4 shadowWorldPosition = modelMatrix * vec4(position, 1.0);\n"
"    //   shadowWorldPosition.xyz += shadowWorldNormal * shadowNormalBias;\n"
"    // In this repro model+view = identity.\n"
"    vShadowWorldNormal   = a_normal;\n"
"    vShadowWorldPosition = a_pos + vShadowWorldNormal * u_normalBias;\n"
"    gl_Position = vec4(a_pos.xy, 0.0, 1.0);\n"
"}\n";

// Fragment: simulate a PCF shadow comparison. If the shadow-space coord
// is inside [0,1] we compare against a constant depth; otherwise return 1.0
// (fully lit). Because NaN comparisons are false in GLSL, both `>= 0.0` and
// `<= 1.0` tests fail when shadowCoord has NaN components, and the fragment
// lands in the "fully lit" branch.
static const char* FS =
"#version 330 core\n"
"in vec3 vShadowWorldNormal;\n"
"in vec3 vShadowWorldPosition;\n"
"out vec4 fragColor;\n"
"void main() {\n"
"    vec3 shadowCoord = vShadowWorldPosition * 0.5 + 0.5;\n"
"    bool inside = shadowCoord.x >= 0.0 && shadowCoord.x <= 1.0 &&\n"
"                  shadowCoord.y >= 0.0 && shadowCoord.y <= 1.0;\n"
"    float shadow = 1.0;\n"
"    if (inside) {\n"
"        // Simulated shadow-map sample: any fragment inside [0,1] is occluded.\n"
"        shadow = 0.1;\n"
"    }\n"
"    vec3 lit = vec3(0.8, 0.8, 0.8) * shadow;\n"
"    fragColor = vec4(lit, 1.0);\n"
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

    // Receiver quad — position only, no normal.
    float quad[] = {
        -0.8f, -0.8f, 0.0f,
         0.8f, -0.8f, 0.0f,
         0.8f,  0.8f, 0.0f,
        -0.8f, -0.8f, 0.0f,
         0.8f,  0.8f, 0.0f,
        -0.8f,  0.8f, 0.0f,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glGenBuffers(1, &vbo);
    glBindVertexArray(vao);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof quad, quad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, NULL);

    // CRITICAL: do NOT enable location=1 (a_normal). Instead, set the
    // generic vertex-constant attribute to NaN to model the Windows
    // driver's behaviour for unbound attribute reads.
    // (MacOS drivers typically return (0, 0, 1) here, producing no bug.)
    const float nan_val = nanf("");
    glVertexAttrib3f(1, nan_val, nan_val, nan_val);

    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    glUseProgram(prog);
    glUniform1f(glGetUniformLocation(prog, "u_normalBias"), 0.05f);

    glDrawArrays(GL_TRIANGLES, 0, 6);
    glXSwapBuffers(dpy, win);

    unsigned char px[4];
    glReadPixels(W/2, H/2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center pixel rgba=%u,%u,%u,%u (expected ~30,30,30 shadowed; broken ~200,200,200 lit)\n",
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
