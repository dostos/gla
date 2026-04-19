// SOURCE: synthetic (no upstream)
// Uniform "uTint" was optimized away by the GLSL compiler because the
// fragment shader's final color doesn't actually use it. glGetUniformLocation
// returns -1 and every glUniform3f call becomes a silent no-op.
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
typedef void   (*PFNGLSHADERSOURCEPROC)(GLuint, GLsizei, const char* const*, const GLint*);
typedef void   (*PFNGLCOMPILESHADERPROC)(GLuint);
typedef void   (*PFNGLGETSHADERIVPROC)(GLuint, GLenum, GLint*);
typedef void   (*PFNGLGETSHADERINFOLOGPROC)(GLuint, GLsizei, GLsizei*, char*);
typedef GLuint (*PFNGLCREATEPROGRAMPROC)(void);
typedef void   (*PFNGLATTACHSHADERPROC)(GLuint, GLuint);
typedef void   (*PFNGLLINKPROGRAMPROC)(GLuint);
typedef void   (*PFNGLGETPROGRAMIVPROC)(GLuint, GLenum, GLint*);
typedef void   (*PFNGLUSEPROGRAMPROC)(GLuint);
typedef GLint  (*PFNGLGETUNIFORMLOCATIONPROC)(GLuint, const char*);
typedef GLint  (*PFNGLGETATTRIBLOCATIONPROC)(GLuint, const char*);
typedef void   (*PFNGLUNIFORM3FPROC)(GLint, GLfloat, GLfloat, GLfloat);
typedef void   (*PFNGLGENBUFFERSPROC)(GLsizei, GLuint*);
typedef void   (*PFNGLBINDBUFFERPROC)(GLenum, GLuint);
typedef void   (*PFNGLBUFFERDATAPROC)(GLenum, ptrdiff_t, const void*, GLenum);
typedef void   (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef void   (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);

#define GL_FRAGMENT_SHADER 0x8B30
#define GL_VERTEX_SHADER   0x8B31
#define GL_COMPILE_STATUS  0x8B81
#define GL_LINK_STATUS     0x8B82
#define GL_ARRAY_BUFFER    0x8892
#define GL_STATIC_DRAW     0x88E4

static PFNGLCREATESHADERPROC            glCreateShader_;
static PFNGLSHADERSOURCEPROC            glShaderSource_;
static PFNGLCOMPILESHADERPROC           glCompileShader_;
static PFNGLGETSHADERIVPROC             glGetShaderiv_;
static PFNGLGETSHADERINFOLOGPROC        glGetShaderInfoLog_;
static PFNGLCREATEPROGRAMPROC           glCreateProgram_;
static PFNGLATTACHSHADERPROC            glAttachShader_;
static PFNGLLINKPROGRAMPROC             glLinkProgram_;
static PFNGLGETPROGRAMIVPROC            glGetProgramiv_;
static PFNGLUSEPROGRAMPROC              glUseProgram_;
static PFNGLGETUNIFORMLOCATIONPROC      glGetUniformLocation_;
static PFNGLGETATTRIBLOCATIONPROC       glGetAttribLocation_;
static PFNGLUNIFORM3FPROC               glUniform3f_;
static PFNGLGENBUFFERSPROC              glGenBuffers_;
static PFNGLBINDBUFFERPROC              glBindBuffer_;
static PFNGLBUFFERDATAPROC              glBufferData_;
static PFNGLENABLEVERTEXATTRIBARRAYPROC glEnableVertexAttribArray_;
static PFNGLVERTEXATTRIBPOINTERPROC     glVertexAttribPointer_;

static void* gp(const char* n) { return (void*)glXGetProcAddress((const GLubyte*)n); }

static void load_gl(void) {
    glCreateShader_            = gp("glCreateShader");
    glShaderSource_            = gp("glShaderSource");
    glCompileShader_           = gp("glCompileShader");
    glGetShaderiv_             = gp("glGetShaderiv");
    glGetShaderInfoLog_        = gp("glGetShaderInfoLog");
    glCreateProgram_           = gp("glCreateProgram");
    glAttachShader_            = gp("glAttachShader");
    glLinkProgram_             = gp("glLinkProgram");
    glGetProgramiv_            = gp("glGetProgramiv");
    glUseProgram_              = gp("glUseProgram");
    glGetUniformLocation_      = gp("glGetUniformLocation");
    glGetAttribLocation_       = gp("glGetAttribLocation");
    glUniform3f_               = gp("glUniform3f");
    glGenBuffers_              = gp("glGenBuffers");
    glBindBuffer_              = gp("glBindBuffer");
    glBufferData_              = gp("glBufferData");
    glEnableVertexAttribArray_ = gp("glEnableVertexAttribArray");
    glVertexAttribPointer_     = gp("glVertexAttribPointer");
}

static const char* VS =
    "#version 120\n"
    "attribute vec2 aPos;\n"
    "void main() { gl_Position = vec4(aPos, 0.0, 1.0); }\n";

// The author intended uTint to modulate the output, but the final assignment
// uses only vBase. The compiler sees uTint is unreferenced and eliminates it.
static const char* FS =
    "#version 120\n"
    "uniform vec3 uTint;\n"
    "void main() {\n"
    "    vec3 vBase = vec3(0.9, 0.1, 0.1);\n"
    "    vec3 tinted = vBase * uTint;\n"
    "    // oops: output uses the untinted base, not `tinted`\n"
    "    gl_FragColor = vec4(vBase, 1.0);\n"
    "}\n";

static GLuint compile(GLenum type, const char* src) {
    GLuint s = glCreateShader_(type);
    glShaderSource_(s, 1, &src, NULL);
    glCompileShader_(s);
    GLint ok = 0;
    glGetShaderiv_(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog_(s, sizeof log, NULL, log);
        fprintf(stderr, "shader compile: %s\n", log);
        exit(1);
    }
    return s;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    int attr[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attr);
    if (!vi) { fprintf(stderr, "no visual\n"); return 1; }
    Window root = RootWindow(dpy, vi->screen);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 400, 300, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);
    load_gl();

    GLuint vs = compile(GL_VERTEX_SHADER, VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    GLuint prog = glCreateProgram_();
    glAttachShader_(prog, vs);
    glAttachShader_(prog, fs);
    glLinkProgram_(prog);
    GLint linked = 0;
    glGetProgramiv_(prog, GL_LINK_STATUS, &linked);
    if (!linked) { fprintf(stderr, "link failed\n"); return 1; }
    glUseProgram_(prog);

    // Author expects this to desaturate the red to a muted gray-red.
    GLint locTint = glGetUniformLocation_(prog, "uTint");
    glUniform3f_(locTint, 0.3f, 0.3f, 0.3f);

    float quad[] = {
        -1.0f, -1.0f,
         1.0f, -1.0f,
        -1.0f,  1.0f,
         1.0f,  1.0f,
    };
    GLuint vbo = 0;
    glGenBuffers_(1, &vbo);
    glBindBuffer_(GL_ARRAY_BUFFER, vbo);
    glBufferData_(GL_ARRAY_BUFFER, sizeof quad, quad, GL_STATIC_DRAW);
    GLint aPos = glGetAttribLocation_(prog, "aPos");
    glEnableVertexAttribArray_(aPos);
    glVertexAttribPointer_(aPos, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), (void*)0);

    for (int f = 0; f < 3; ++f) {
        glViewport(0, 0, 400, 300);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
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