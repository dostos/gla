// SOURCE: synthetic (no upstream)
// Mesh authored with clockwise winding under default GL_CCW front-face with back-face culling enabled.
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

typedef GLuint (*PFNGLCREATESHADERPROC)(GLenum);
typedef void (*PFNGLSHADERSOURCEPROC)(GLuint, GLsizei, const GLchar* const*, const GLint*);
typedef void (*PFNGLCOMPILESHADERPROC)(GLuint);
typedef void (*PFNGLGETSHADERIVPROC)(GLuint, GLenum, GLint*);
typedef void (*PFNGLGETSHADERINFOLOGPROC)(GLuint, GLsizei, GLsizei*, GLchar*);
typedef GLuint (*PFNGLCREATEPROGRAMPROC)(void);
typedef void (*PFNGLATTACHSHADERPROC)(GLuint, GLuint);
typedef void (*PFNGLLINKPROGRAMPROC)(GLuint);
typedef void (*PFNGLGETPROGRAMIVPROC)(GLuint, GLenum, GLint*);
typedef void (*PFNGLUSEPROGRAMPROC)(GLuint);
typedef void (*PFNGLGENBUFFERSPROC)(GLsizei, GLuint*);
typedef void (*PFNGLBINDBUFFERPROC)(GLenum, GLuint);
typedef void (*PFNGLBUFFERDATAPROC)(GLenum, GLsizeiptr, const void*, GLenum);
typedef void (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef GLint (*PFNGLGETATTRIBLOCATIONPROC)(GLuint, const GLchar*);
typedef GLint (*PFNGLGETUNIFORMLOCATIONPROC)(GLuint, const GLchar*);
typedef void (*PFNGLUNIFORM4FPROC)(GLint, GLfloat, GLfloat, GLfloat, GLfloat);

static PFNGLCREATESHADERPROC glCreateShader_;
static PFNGLSHADERSOURCEPROC glShaderSource_;
static PFNGLCOMPILESHADERPROC glCompileShader_;
static PFNGLGETSHADERIVPROC glGetShaderiv_;
static PFNGLGETSHADERINFOLOGPROC glGetShaderInfoLog_;
static PFNGLCREATEPROGRAMPROC glCreateProgram_;
static PFNGLATTACHSHADERPROC glAttachShader_;
static PFNGLLINKPROGRAMPROC glLinkProgram_;
static PFNGLGETPROGRAMIVPROC glGetProgramiv_;
static PFNGLUSEPROGRAMPROC glUseProgram_;
static PFNGLGENBUFFERSPROC glGenBuffers_;
static PFNGLBINDBUFFERPROC glBindBuffer_;
static PFNGLBUFFERDATAPROC glBufferData_;
static PFNGLVERTEXATTRIBPOINTERPROC glVertexAttribPointer_;
static PFNGLENABLEVERTEXATTRIBARRAYPROC glEnableVertexAttribArray_;
static PFNGLGETATTRIBLOCATIONPROC glGetAttribLocation_;
static PFNGLGETUNIFORMLOCATIONPROC glGetUniformLocation_;
static PFNGLUNIFORM4FPROC glUniform4f_;

#define LOAD(name) name##_ = (PFN##name##PROC_UP)glXGetProcAddress((const GLubyte*)#name)

static void* load(const char* n) {
    return (void*)glXGetProcAddress((const GLubyte*)n);
}

static const char* vs_src =
    "#version 120\n"
    "attribute vec2 a_pos;\n"
    "void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }\n";

static const char* fs_src =
    "#version 120\n"
    "uniform vec4 u_color;\n"
    "void main() { gl_FragColor = u_color; }\n";

static GLuint compile(GLenum t, const char* s) {
    GLuint sh = glCreateShader_(t);
    glShaderSource_(sh, 1, &s, NULL);
    glCompileShader_(sh);
    GLint ok = 0;
    glGetShaderiv_(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog_(sh, sizeof(log), NULL, log);
        fprintf(stderr, "shader: %s\n", log);
        exit(1);
    }
    return sh;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int attr[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attr);
    if (!vi) { fprintf(stderr, "glXChooseVisual failed\n"); return 1; }
    Window root = RootWindow(dpy, vi->screen);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 400, 300, 0, vi->depth,
        InputOutput, vi->visual, CWColormap | CWEventMask, &swa);
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
    glGetProgramiv_ = load("glGetProgramiv");
    glUseProgram_ = load("glUseProgram");
    glGenBuffers_ = load("glGenBuffers");
    glBindBuffer_ = load("glBindBuffer");
    glBufferData_ = load("glBufferData");
    glVertexAttribPointer_ = load("glVertexAttribPointer");
    glEnableVertexAttribArray_ = load("glEnableVertexAttribArray");
    glGetAttribLocation_ = load("glGetAttribLocation");
    glGetUniformLocation_ = load("glGetUniformLocation");
    glUniform4f_ = load("glUniform4f");

    GLuint vs = compile(GL_VERTEX_SHADER, vs_src);
    GLuint fs = compile(GL_FRAGMENT_SHADER, fs_src);
    GLuint prog = glCreateProgram_();
    glAttachShader_(prog, vs);
    glAttachShader_(prog, fs);
    glLinkProgram_(prog);
    GLint linked = 0;
    glGetProgramiv_(prog, GL_LINK_STATUS, &linked);
    if (!linked) { fprintf(stderr, "link failed\n"); return 1; }

    // Two triangles forming a quad covering most of the viewport.
    // Vertices authored with CLOCKWISE winding (artist convention from a
    // DirectX-style asset pipeline).
    float verts[] = {
        // triangle 1 (CW): TL -> BL -> TR
        -0.8f,  0.8f,
        -0.8f, -0.8f,
         0.8f,  0.8f,
        // triangle 2 (CW): TR -> BL -> BR
         0.8f,  0.8f,
        -0.8f, -0.8f,
         0.8f, -0.8f,
    };

    GLuint vbo;
    glGenBuffers_(1, &vbo);
    glBindBuffer_(GL_ARRAY_BUFFER, vbo);
    glBufferData_(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);

    glUseProgram_(prog);
    GLint a_pos = glGetAttribLocation_(prog, "a_pos");
    GLint u_color = glGetUniformLocation_(prog, "u_color");
    glEnableVertexAttribArray_(a_pos);
    glVertexAttribPointer_(a_pos, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), (void*)0);

    // Enable back-face culling. GL defaults: front_face=GL_CCW, cull_face=GL_BACK.
    // Our CW-wound vertices are therefore treated as back faces and culled.
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    glFrontFace(GL_CCW);

    glViewport(0, 0, 400, 300);

    for (int f = 0; f < 4; f++) {
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glUniform4f_(u_color, 1.0f, 0.5f, 0.2f, 1.0f);
        glDrawArrays(GL_TRIANGLES, 0, 6);
        glXSwapBuffers(dpy, win);
    }

    unsigned char px[4] = {0};
    glReadPixels(200, 150, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center RGBA = %u %u %u %u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}