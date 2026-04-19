// SOURCE: synthetic (no upstream)
// Depth buffer never cleared between frames; frame 0's near quad occludes frame 1's farther quad.
//
// Minimal OpenGL 2.1 / 3.3 compatible program. Uses GLX for context.
// Link: -lGL -lX11 -lm only. Compiles with:
//   gcc -Wall -std=gnu11 main.c -lGL -lX11 -lm
// Runs under Xvfb; exits cleanly after rendering 3-5 frames.
// The bug manifests on the second rendered frame (frame index 1).
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
typedef void   (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void   (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef GLint  (*PFNGLGETATTRIBLOCATIONPROC)(GLuint, const char*);
typedef GLint  (*PFNGLGETUNIFORMLOCATIONPROC)(GLuint, const char*);
typedef void   (*PFNGLUNIFORM4FPROC)(GLint, GLfloat, GLfloat, GLfloat, GLfloat);

static PFNGLCREATESHADERPROC             p_glCreateShader;
static PFNGLSHADERSOURCEPROC             p_glShaderSource;
static PFNGLCOMPILESHADERPROC            p_glCompileShader;
static PFNGLGETSHADERIVPROC              p_glGetShaderiv;
static PFNGLGETSHADERINFOLOGPROC         p_glGetShaderInfoLog;
static PFNGLCREATEPROGRAMPROC            p_glCreateProgram;
static PFNGLATTACHSHADERPROC             p_glAttachShader;
static PFNGLLINKPROGRAMPROC              p_glLinkProgram;
static PFNGLUSEPROGRAMPROC               p_glUseProgram;
static PFNGLGENBUFFERSPROC               p_glGenBuffers;
static PFNGLBINDBUFFERPROC               p_glBindBuffer;
static PFNGLBUFFERDATAPROC               p_glBufferData;
static PFNGLVERTEXATTRIBPOINTERPROC      p_glVertexAttribPointer;
static PFNGLENABLEVERTEXATTRIBARRAYPROC  p_glEnableVertexAttribArray;
static PFNGLGETATTRIBLOCATIONPROC        p_glGetAttribLocation;
static PFNGLGETUNIFORMLOCATIONPROC       p_glGetUniformLocation;
static PFNGLUNIFORM4FPROC                p_glUniform4f;

static void* gp(const char* name) {
    return (void*)glXGetProcAddress((const GLubyte*)name);
}

static void load_gl(void) {
    p_glCreateShader            = gp("glCreateShader");
    p_glShaderSource            = gp("glShaderSource");
    p_glCompileShader           = gp("glCompileShader");
    p_glGetShaderiv             = gp("glGetShaderiv");
    p_glGetShaderInfoLog        = gp("glGetShaderInfoLog");
    p_glCreateProgram           = gp("glCreateProgram");
    p_glAttachShader            = gp("glAttachShader");
    p_glLinkProgram             = gp("glLinkProgram");
    p_glUseProgram              = gp("glUseProgram");
    p_glGenBuffers              = gp("glGenBuffers");
    p_glBindBuffer              = gp("glBindBuffer");
    p_glBufferData              = gp("glBufferData");
    p_glVertexAttribPointer     = gp("glVertexAttribPointer");
    p_glEnableVertexAttribArray = gp("glEnableVertexAttribArray");
    p_glGetAttribLocation       = gp("glGetAttribLocation");
    p_glGetUniformLocation      = gp("glGetUniformLocation");
    p_glUniform4f               = gp("glUniform4f");
}

static GLuint compile(GLenum type, const char* src) {
    GLuint s = p_glCreateShader(type);
    p_glShaderSource(s, 1, &src, NULL);
    p_glCompileShader(s);
    GLint ok = 0;
    p_glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024]; p_glGetShaderInfoLog(s, 1024, NULL, log);
        fprintf(stderr, "shader: %s\n", log);
        exit(1);
    }
    return s;
}

static const char* VS =
    "#version 120\n"
    "attribute vec3 aPos;\n"
    "void main(){ gl_Position = vec4(aPos, 1.0); }\n";

static const char* FS =
    "#version 120\n"
    "uniform vec4 uColor;\n"
    "void main(){ gl_FragColor = uColor; }\n";

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    int attr[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, attr);
    if (!vi) { fprintf(stderr, "no visual\n"); return 1; }
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 400, 300, 0, vi->depth,
        InputOutput, vi->visual, CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);
    load_gl();

    GLuint prog = p_glCreateProgram();
    p_glAttachShader(prog, compile(GL_VERTEX_SHADER, VS));
    p_glAttachShader(prog, compile(GL_FRAGMENT_SHADER, FS));
    p_glLinkProgram(prog);
    p_glUseProgram(prog);

    // Frame 0 quad: small centered quad at z = -0.2 (near).
    float near_quad[] = {
        -0.3f, -0.3f, -0.2f,
         0.3f, -0.3f, -0.2f,
         0.3f,  0.3f, -0.2f,
        -0.3f, -0.3f, -0.2f,
         0.3f,  0.3f, -0.2f,
        -0.3f,  0.3f, -0.2f,
    };
    // Frame 1 quad: larger quad covering the viewport at z = +0.5 (farther).
    float far_quad[] = {
        -0.8f, -0.8f,  0.5f,
         0.8f, -0.8f,  0.5f,
         0.8f,  0.8f,  0.5f,
        -0.8f, -0.8f,  0.5f,
         0.8f,  0.8f,  0.5f,
        -0.8f,  0.8f,  0.5f,
    };

    GLuint vbo_near, vbo_far;
    p_glGenBuffers(1, &vbo_near);
    p_glBindBuffer(GL_ARRAY_BUFFER, vbo_near);
    p_glBufferData(GL_ARRAY_BUFFER, sizeof(near_quad), near_quad, GL_STATIC_DRAW);
    p_glGenBuffers(1, &vbo_far);
    p_glBindBuffer(GL_ARRAY_BUFFER, vbo_far);
    p_glBufferData(GL_ARRAY_BUFFER, sizeof(far_quad), far_quad, GL_STATIC_DRAW);

    GLint aPos = p_glGetAttribLocation(prog, "aPos");
    GLint uColor = p_glGetUniformLocation(prog, "uColor");

    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);
    glViewport(0, 0, 400, 300);

    for (int frame = 0; frame < 4; ++frame) {
        glClearColor(0.1f, 0.1f, 0.1f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);  // depth intentionally not cleared

        if (frame == 0) {
            p_glBindBuffer(GL_ARRAY_BUFFER, vbo_near);
            p_glVertexAttribPointer(aPos, 3, GL_FLOAT, GL_FALSE, 3*sizeof(float), 0);
            p_glEnableVertexAttribArray(aPos);
            p_glUniform4f(uColor, 1.0f, 0.2f, 0.2f, 1.0f);
            glDrawArrays(GL_TRIANGLES, 0, 6);
        } else {
            p_glBindBuffer(GL_ARRAY_BUFFER, vbo_far);
            p_glVertexAttribPointer(aPos, 3, GL_FLOAT, GL_FALSE, 3*sizeof(float), 0);
            p_glEnableVertexAttribArray(aPos);
            p_glUniform4f(uColor, 0.2f, 1.0f, 0.2f, 1.0f);
            glDrawArrays(GL_TRIANGLES, 0, 6);
        }

        glXSwapBuffers(dpy, win);
    }

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(200, 150, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center RGBA: %u %u %u %u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}