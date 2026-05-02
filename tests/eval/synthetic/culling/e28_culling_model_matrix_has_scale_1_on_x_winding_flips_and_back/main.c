// SOURCE: synthetic (no upstream)
// Negative X scale in model matrix flips triangle winding; GL_BACK culling
// then discards every triangle, leaving only the clear color.
//
// Minimal OpenGL 2.1 / 3.3 compatible program. Uses GLX for context.
// Link: -lGL -lX11 -lm only. Compiles with:
//   gcc -Wall -std=gnu11 main.c -lGL -lX11 -lm
// Runs under Xvfb; exits cleanly after rendering 3-5 frames.
// The bug manifests on the first rendered frame.
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

typedef char GLchar;
typedef ptrdiff_t GLsizeiptr;
typedef ptrdiff_t GLintptr;

typedef GLuint (*PFNGLCREATESHADERPROC)(GLenum);
typedef void (*PFNGLSHADERSOURCEPROC)(GLuint, GLsizei, const GLchar* const*, const GLint*);
typedef void (*PFNGLCOMPILESHADERPROC)(GLuint);
typedef void (*PFNGLGETSHADERIVPROC)(GLuint, GLenum, GLint*);
typedef void (*PFNGLGETSHADERINFOLOGPROC)(GLuint, GLsizei, GLsizei*, GLchar*);
typedef GLuint (*PFNGLCREATEPROGRAMPROC)(void);
typedef void (*PFNGLATTACHSHADERPROC)(GLuint, GLuint);
typedef void (*PFNGLLINKPROGRAMPROC)(GLuint);
typedef void (*PFNGLUSEPROGRAMPROC)(GLuint);
typedef void (*PFNGLGETPROGRAMIVPROC)(GLuint, GLenum, GLint*);
typedef void (*PFNGLGENBUFFERSPROC)(GLsizei, GLuint*);
typedef void (*PFNGLBINDBUFFERPROC)(GLenum, GLuint);
typedef void (*PFNGLBUFFERDATAPROC)(GLenum, GLsizeiptr, const void*, GLenum);
typedef void (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef GLint (*PFNGLGETUNIFORMLOCATIONPROC)(GLuint, const GLchar*);
typedef void (*PFNGLUNIFORMMATRIX4FVPROC)(GLint, GLsizei, GLboolean, const GLfloat*);
typedef void (*PFNGLUNIFORM3FPROC)(GLint, GLfloat, GLfloat, GLfloat);
typedef void (*PFNGLBINDATTRIBLOCATIONPROC)(GLuint, GLuint, const GLchar*);

static PFNGLCREATESHADERPROC glCreateShader_;
static PFNGLSHADERSOURCEPROC glShaderSource_;
static PFNGLCOMPILESHADERPROC glCompileShader_;
static PFNGLGETSHADERIVPROC glGetShaderiv_;
static PFNGLGETSHADERINFOLOGPROC glGetShaderInfoLog_;
static PFNGLCREATEPROGRAMPROC glCreateProgram_;
static PFNGLATTACHSHADERPROC glAttachShader_;
static PFNGLLINKPROGRAMPROC glLinkProgram_;
static PFNGLUSEPROGRAMPROC glUseProgram_;
static PFNGLGETPROGRAMIVPROC glGetProgramiv_;
static PFNGLGENBUFFERSPROC glGenBuffers_;
static PFNGLBINDBUFFERPROC glBindBuffer_;
static PFNGLBUFFERDATAPROC glBufferData_;
static PFNGLVERTEXATTRIBPOINTERPROC glVertexAttribPointer_;
static PFNGLENABLEVERTEXATTRIBARRAYPROC glEnableVertexAttribArray_;
static PFNGLGETUNIFORMLOCATIONPROC glGetUniformLocation_;
static PFNGLUNIFORMMATRIX4FVPROC glUniformMatrix4fv_;
static PFNGLUNIFORM3FPROC glUniform3f_;
static PFNGLBINDATTRIBLOCATIONPROC glBindAttribLocation_;

#define LOAD(name) name##_ = (PFN##name##_UPPER##PROC)glXGetProcAddress((const GLubyte*)#name)

static void* load(const char* n) { return (void*)glXGetProcAddress((const GLubyte*)n); }

static const char* VS =
    "#version 120\n"
    "attribute vec3 aPos;\n"
    "attribute vec3 aColor;\n"
    "varying vec3 vColor;\n"
    "uniform mat4 uModel;\n"
    "uniform mat4 uViewProj;\n"
    "void main() {\n"
    "  vColor = aColor;\n"
    "  gl_Position = uViewProj * uModel * vec4(aPos, 1.0);\n"
    "}\n";

static const char* FS =
    "#version 120\n"
    "varying vec3 vColor;\n"
    "void main() { gl_FragColor = vec4(vColor, 1.0); }\n";

static void mat4_identity(float* m) {
    memset(m, 0, 16 * sizeof(float));
    m[0] = m[5] = m[10] = m[15] = 1.0f;
}

static void mat4_scale(float* m, float sx, float sy, float sz) {
    mat4_identity(m);
    m[0] = sx; m[5] = sy; m[10] = sz;
}

static void mat4_ortho(float* m, float l, float r, float b, float t, float n, float f) {
    mat4_identity(m);
    m[0] = 2.0f / (r - l);
    m[5] = 2.0f / (t - b);
    m[10] = -2.0f / (f - n);
    m[12] = -(r + l) / (r - l);
    m[13] = -(t + b) / (t - b);
    m[14] = -(f + n) / (f - n);
}

static GLuint compile(GLenum type, const char* src) {
    GLuint s = glCreateShader_(type);
    glShaderSource_(s, 1, &src, NULL);
    glCompileShader_(s);
    GLint ok = 0;
    glGetShaderiv_(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog_(s, sizeof(log), NULL, log);
        fprintf(stderr, "shader error: %s\n", log);
        exit(1);
    }
    return s;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    int attrs[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, attrs);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 400, 300, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    glCreateShader_ = load("glCreateShader");
    glShaderSource_ = load("glShaderSource");
    glCompileShader_ = load("glCompileShader");
    glGetShaderiv_ = load("glGetShaderiv");
    glGetShaderInfoLog_ = load("glGetShaderInfoLog");
    glCreateProgram_ = load("glCreateProgram");
    glAttachShader_ = load("glAttachShader");
    glLinkProgram_ = load("glLinkProgram");
    glUseProgram_ = load("glUseProgram");
    glGetProgramiv_ = load("glGetProgramiv");
    glGenBuffers_ = load("glGenBuffers");
    glBindBuffer_ = load("glBindBuffer");
    glBufferData_ = load("glBufferData");
    glVertexAttribPointer_ = load("glVertexAttribPointer");
    glEnableVertexAttribArray_ = load("glEnableVertexAttribArray");
    glGetUniformLocation_ = load("glGetUniformLocation");
    glUniformMatrix4fv_ = load("glUniformMatrix4fv");
    glUniform3f_ = load("glUniform3f");
    glBindAttribLocation_ = load("glBindAttribLocation");

    GLuint vs = compile(GL_VERTEX_SHADER, VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    GLuint prog = glCreateProgram_();
    glAttachShader_(prog, vs);
    glAttachShader_(prog, fs);
    glBindAttribLocation_(prog, 0, "aPos");
    glBindAttribLocation_(prog, 1, "aColor");
    glLinkProgram_(prog);

    // Two CCW triangles forming a quad centered at origin.
    float verts[] = {
        -0.5f, -0.5f, 0.0f,  1.0f, 0.5f, 0.2f,
         0.5f, -0.5f, 0.0f,  1.0f, 0.5f, 0.2f,
         0.5f,  0.5f, 0.0f,  1.0f, 0.5f, 0.2f,

        -0.5f, -0.5f, 0.0f,  1.0f, 0.5f, 0.2f,
         0.5f,  0.5f, 0.0f,  1.0f, 0.5f, 0.2f,
        -0.5f,  0.5f, 0.0f,  1.0f, 0.5f, 0.2f,
    };
    GLuint vbo = 0;
    glGenBuffers_(1, &vbo);
    glBindBuffer_(GL_ARRAY_BUFFER, vbo);
    glBufferData_(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glVertexAttribPointer_(0, 3, GL_FLOAT, GL_FALSE, 6 * sizeof(float), (void*)0);
    glEnableVertexAttribArray_(0);
    glVertexAttribPointer_(1, 3, GL_FLOAT, GL_FALSE, 6 * sizeof(float), (void*)(3 * sizeof(float)));
    glEnableVertexAttribArray_(1);

    // Viewport model assumes CCW front faces; cull back faces.
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    glFrontFace(GL_CCW);

    glViewport(0, 0, 400, 300);

    float viewProj[16];
    mat4_ortho(viewProj, -1.0f, 1.0f, -1.0f, 1.0f, -1.0f, 1.0f);

    // Horizontal "mirror" for a UI quad: flip X so art faces inward.
    // (Composed with a uniform 1.0 scale on Y/Z.)
    float model[16];
    mat4_scale(model, -1.0f, 1.0f, 1.0f);

    glUseProgram_(prog);
    GLint uModel = glGetUniformLocation_(prog, "uModel");
    GLint uVP = glGetUniformLocation_(prog, "uViewProj");

    for (int i = 0; i < 4; ++i) {
        glClearColor(0.05f, 0.07f, 0.10f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glUniformMatrix4fv_(uVP, 1, GL_FALSE, viewProj);
        glUniformMatrix4fv_(uModel, 1, GL_FALSE, model);
        glDrawArrays(GL_TRIANGLES, 0, 6);
        glXSwapBuffers(dpy, win);
    }

    unsigned char px[4] = {0};
    glReadPixels(200, 150, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center pixel RGBA = %u %u %u %u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}