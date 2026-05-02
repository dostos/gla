// SOURCE: synthetic (no upstream)
// glFrontFace(GL_CW) leaked from a debug/diagnostic path; subsequent CCW
// geometry is culled as back-facing, leaving the framebuffer at clear color.
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
typedef void   (*PFNGLUSEPROGRAMPROC)(GLuint);
typedef void   (*PFNGLGENBUFFERSPROC)(GLsizei, GLuint*);
typedef void   (*PFNGLBINDBUFFERPROC)(GLenum, GLuint);
typedef void   (*PFNGLBUFFERDATAPROC)(GLenum, GLsizeiptr, const void*, GLenum);
typedef GLint  (*PFNGLGETATTRIBLOCATIONPROC)(GLuint, const char*);
typedef void   (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef void   (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef GLint  (*PFNGLGETUNIFORMLOCATIONPROC)(GLuint, const char*);
typedef void   (*PFNGLUNIFORM4FPROC)(GLint, GLfloat, GLfloat, GLfloat, GLfloat);

static PFNGLCREATESHADERPROC          glCreateShader_;
static PFNGLSHADERSOURCEPROC          glShaderSource_;
static PFNGLCOMPILESHADERPROC         glCompileShader_;
static PFNGLGETSHADERIVPROC           glGetShaderiv_;
static PFNGLGETSHADERINFOLOGPROC      glGetShaderInfoLog_;
static PFNGLCREATEPROGRAMPROC         glCreateProgram_;
static PFNGLATTACHSHADERPROC          glAttachShader_;
static PFNGLLINKPROGRAMPROC           glLinkProgram_;
static PFNGLUSEPROGRAMPROC            glUseProgram_;
static PFNGLGENBUFFERSPROC            glGenBuffers_;
static PFNGLBINDBUFFERPROC            glBindBuffer_;
static PFNGLBUFFERDATAPROC            glBufferData_;
static PFNGLGETATTRIBLOCATIONPROC     glGetAttribLocation_;
static PFNGLENABLEVERTEXATTRIBARRAYPROC glEnableVertexAttribArray_;
static PFNGLVERTEXATTRIBPOINTERPROC   glVertexAttribPointer_;
static PFNGLGETUNIFORMLOCATIONPROC    glGetUniformLocation_;
static PFNGLUNIFORM4FPROC             glUniform4f_;

#define LOAD(name) name##_ = (PFN##name##PROC_upper)glXGetProcAddress((const GLubyte*)#name)
static void load_gl(void) {
    glCreateShader_ = (PFNGLCREATESHADERPROC)glXGetProcAddress((const GLubyte*)"glCreateShader");
    glShaderSource_ = (PFNGLSHADERSOURCEPROC)glXGetProcAddress((const GLubyte*)"glShaderSource");
    glCompileShader_ = (PFNGLCOMPILESHADERPROC)glXGetProcAddress((const GLubyte*)"glCompileShader");
    glGetShaderiv_ = (PFNGLGETSHADERIVPROC)glXGetProcAddress((const GLubyte*)"glGetShaderiv");
    glGetShaderInfoLog_ = (PFNGLGETSHADERINFOLOGPROC)glXGetProcAddress((const GLubyte*)"glGetShaderInfoLog");
    glCreateProgram_ = (PFNGLCREATEPROGRAMPROC)glXGetProcAddress((const GLubyte*)"glCreateProgram");
    glAttachShader_ = (PFNGLATTACHSHADERPROC)glXGetProcAddress((const GLubyte*)"glAttachShader");
    glLinkProgram_ = (PFNGLLINKPROGRAMPROC)glXGetProcAddress((const GLubyte*)"glLinkProgram");
    glUseProgram_ = (PFNGLUSEPROGRAMPROC)glXGetProcAddress((const GLubyte*)"glUseProgram");
    glGenBuffers_ = (PFNGLGENBUFFERSPROC)glXGetProcAddress((const GLubyte*)"glGenBuffers");
    glBindBuffer_ = (PFNGLBINDBUFFERPROC)glXGetProcAddress((const GLubyte*)"glBindBuffer");
    glBufferData_ = (PFNGLBUFFERDATAPROC)glXGetProcAddress((const GLubyte*)"glBufferData");
    glGetAttribLocation_ = (PFNGLGETATTRIBLOCATIONPROC)glXGetProcAddress((const GLubyte*)"glGetAttribLocation");
    glEnableVertexAttribArray_ = (PFNGLENABLEVERTEXATTRIBARRAYPROC)glXGetProcAddress((const GLubyte*)"glEnableVertexAttribArray");
    glVertexAttribPointer_ = (PFNGLVERTEXATTRIBPOINTERPROC)glXGetProcAddress((const GLubyte*)"glVertexAttribPointer");
    glGetUniformLocation_ = (PFNGLGETUNIFORMLOCATIONPROC)glXGetProcAddress((const GLubyte*)"glGetUniformLocation");
    glUniform4f_ = (PFNGLUNIFORM4FPROC)glXGetProcAddress((const GLubyte*)"glUniform4f");
}

static GLuint compile(GLenum type, const char* src) {
    GLuint s = glCreateShader_(type);
    glShaderSource_(s, 1, &src, NULL);
    glCompileShader_(s);
    GLint ok = 0; glGetShaderiv_(s, GL_COMPILE_STATUS, &ok);
    if (!ok) { char log[1024]; glGetShaderInfoLog_(s, 1024, NULL, log); fprintf(stderr, "shader: %s\n", log); exit(2); }
    return s;
}

static const char* VS =
    "#version 120\n"
    "attribute vec2 a_pos;\n"
    "void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }\n";

static const char* FS =
    "#version 120\n"
    "uniform vec4 u_color;\n"
    "void main() { gl_FragColor = u_color; }\n";

// "Debug helper" from a diagnostic module — draws a small marker and
// flips the winding order because the marker mesh was authored CW.
// The helper neglects to restore GL_CCW before returning.
static void debug_overlay_marker(void) {
    glFrontFace(GL_CW);
    // (a real helper would also issue its own draw here; we simulate the leak)
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int attrs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attrs);
    if (!vi) { fprintf(stderr, "glXChooseVisual failed\n"); return 1; }
    Window root = RootWindow(dpy, vi->screen);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 400, 300, 0, vi->depth,
                               InputOutput, vi->visual, CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, True);
    glXMakeCurrent(dpy, win, ctx);
    load_gl();

    GLuint prog = glCreateProgram_();
    glAttachShader_(prog, compile(GL_VERTEX_SHADER, VS));
    glAttachShader_(prog, compile(GL_FRAGMENT_SHADER, FS));
    glLinkProgram_(prog);
    glUseProgram_(prog);

    // Full-screen CCW triangle (covers center pixel).
    float verts[] = {
        -1.0f, -1.0f,
         3.0f, -1.0f,
        -1.0f,  3.0f,
    };
    GLuint vbo; glGenBuffers_(1, &vbo);
    glBindBuffer_(GL_ARRAY_BUFFER, vbo);
    glBufferData_(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    GLint a_pos = glGetAttribLocation_(prog, "a_pos");
    glEnableVertexAttribArray_(a_pos);
    glVertexAttribPointer_(a_pos, 2, GL_FLOAT, GL_FALSE, 0, 0);

    GLint u_color = glGetUniformLocation_(prog, "u_color");

    // Engine convention: back-face culling with CCW front-faces.
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    glFrontFace(GL_CCW);

    // Startup diagnostics ran once and leaked GL_CW.
    debug_overlay_marker();

    for (int f = 0; f < 4; ++f) {
        glViewport(0, 0, 400, 300);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        glUniform4f_(u_color, 0.2f, 0.8f, 0.3f, 1.0f); // bright green
        glDrawArrays(GL_TRIANGLES, 0, 3);
        glXSwapBuffers(dpy, win);
    }

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(200, 150, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center RGBA = %u %u %u %u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}