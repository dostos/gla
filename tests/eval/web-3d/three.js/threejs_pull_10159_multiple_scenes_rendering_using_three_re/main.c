// SOURCE: https://stackoverflow.com/questions/40548144/multiple-scenes-rendering-using-three-renderpass
// Two render passes in a single frame: "terrain" pass then "text overlay" pass.
// Pass 2 expects to draw on top of pass 1 but does NOT clear the depth buffer,
// so text fragments at greater depth than leftover terrain depth fail GL_LESS
// and get occluded by the previous pass's depth values.
//
// Mirrors three.js pre-r83 RenderPass: setting `clearDepth = true` had no effect
// because RenderPass.render() never honored it (PR mrdoob/three.js#10159 added the call).
//
// Compiles with: gcc -Wall -O0 main.c -lGL -lX11 -lm
// Runs under Xvfb. Bug manifests on the first (and only) rendered frame.
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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

static void* gp(const char* n) { return (void*)glXGetProcAddress((const GLubyte*)n); }

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

    // "Terrain" — large near quad covering most of the viewport at z = -0.2.
    float terrain[] = {
        -0.9f, -0.9f, -0.2f,
         0.9f, -0.9f, -0.2f,
         0.9f,  0.9f, -0.2f,
        -0.9f, -0.9f, -0.2f,
         0.9f,  0.9f, -0.2f,
        -0.9f,  0.9f, -0.2f,
    };
    // "Text" overlay — small centered quad at z = +0.5 (further from camera).
    // Semantically meant to be drawn unconditionally on top of pass 1.
    float text[] = {
        -0.3f, -0.1f, 0.5f,
         0.3f, -0.1f, 0.5f,
         0.3f,  0.1f, 0.5f,
        -0.3f, -0.1f, 0.5f,
         0.3f,  0.1f, 0.5f,
        -0.3f,  0.1f, 0.5f,
    };

    GLuint vbo_terrain, vbo_text;
    p_glGenBuffers(1, &vbo_terrain);
    p_glBindBuffer(GL_ARRAY_BUFFER, vbo_terrain);
    p_glBufferData(GL_ARRAY_BUFFER, sizeof(terrain), terrain, GL_STATIC_DRAW);
    p_glGenBuffers(1, &vbo_text);
    p_glBindBuffer(GL_ARRAY_BUFFER, vbo_text);
    p_glBufferData(GL_ARRAY_BUFFER, sizeof(text), text, GL_STATIC_DRAW);

    GLint aPos = p_glGetAttribLocation(prog, "aPos");
    GLint uColor = p_glGetUniformLocation(prog, "uColor");

    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);
    glViewport(0, 0, 400, 300);

    // Pass 1: terrain. Clear color + depth, then draw.
    glClearColor(0.05f, 0.05f, 0.1f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    p_glBindBuffer(GL_ARRAY_BUFFER, vbo_terrain);
    p_glVertexAttribPointer(aPos, 3, GL_FLOAT, GL_FALSE, 3*sizeof(float), 0);
    p_glEnableVertexAttribArray(aPos);
    p_glUniform4f(uColor, 0.8f, 0.3f, 0.2f, 1.0f); // terrain = red-brown
    glDrawArrays(GL_TRIANGLES, 0, 6);

    // Pass 2: text overlay. BUG: depth NOT cleared. Equivalent to three.js
    // pre-r83 RenderPass with `clearDepth = true` set but never honored.
    // The text fragments (z=+0.5) lose GL_LESS against terrain depth (z=-0.2).
    p_glBindBuffer(GL_ARRAY_BUFFER, vbo_text);
    p_glVertexAttribPointer(aPos, 3, GL_FLOAT, GL_FALSE, 3*sizeof(float), 0);
    p_glEnableVertexAttribArray(aPos);
    p_glUniform4f(uColor, 0.2f, 1.0f, 0.3f, 1.0f); // text = bright green
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glXSwapBuffers(dpy, win);

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(200, 150, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center RGBA: %u %u %u %u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}