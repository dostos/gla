// SOURCE: https://github.com/mrdoob/three.js/issues/33076
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char* VS =
    "#version 330 core\n"
    "layout(location=0) in vec3 aPos;\n"
    "uniform mat4 uProj;\n"
    "uniform mat4 uView;\n"
    "void main(){ gl_Position = uProj * uView * vec4(aPos,1.0); }\n";

static const char* FS =
    "#version 330 core\n"
    "out vec4 oColor;\n"
    "void main(){ oColor = vec4(0.9, 0.3, 0.2, 1.0); }\n";

// Reversed-Z, [0, 1] clip-space perspective projection (WebGPU style).
// At view-space z = -near  -> clip z / w = 1 (closest).
// At view-space z = -far   -> clip z / w = 0 (farthest).
// Column-major.
static void reversed_z_proj_01(float* m, float fovy, float aspect,
                               float n, float f) {
    float t = 1.0f / tanf(fovy * 0.5f);
    memset(m, 0, 16 * sizeof(float));
    m[0]  = t / aspect;
    m[5]  = t;
    m[10] = n / (f - n);
    m[11] = -1.0f;
    m[14] = (n * f) / (f - n);
}

static void identity(float* m) {
    memset(m, 0, 16 * sizeof(float));
    m[0] = m[5] = m[10] = m[15] = 1.0f;
}

static void translate_z(float* m, float z) {
    identity(m);
    m[14] = z;
}

static GLuint compile(GLenum stage, const char* src) {
    GLuint s = glCreateShader(stage);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    return s;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int attribs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, attribs);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    Window win = XCreateWindow(dpy, root, 0, 0, 800, 600, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap, &swa);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    // Reversed-Z [0, 1] pipeline state:
    //   clear depth = 0.0
    //   depth func  = GL_GREATER
    //   projection  -> clip z in [0, w]
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_GREATER);
    glClearDepth(0.0);

    GLuint vs = compile(GL_VERTEX_SHADER,   VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);
    glUseProgram(prog);

    float verts[] = {
        -0.6f, -0.5f, 0.0f,
         0.6f, -0.5f, 0.0f,
         0.0f,  0.6f, 0.0f,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), 0);
    glEnableVertexAttribArray(0);

    float proj[16], view[16];
    reversed_z_proj_01(proj, 1.1f, 800.0f / 600.0f, 0.1f, 100.0f);
    translate_z(view, -3.0f);
    glUniformMatrix4fv(glGetUniformLocation(prog, "uProj"), 1, GL_FALSE, proj);
    glUniformMatrix4fv(glGetUniformLocation(prog, "uView"), 1, GL_FALSE, view);

    glViewport(0, 0, 800, 600);
    glClearColor(0.1f, 0.1f, 0.15f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glXSwapBuffers(dpy, win);
    glFinish();

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}