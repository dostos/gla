// SOURCE: https://github.com/mapbox/mapbox-gl-js/issues/13367
// Minimal OpenGL reproduction of the "two overlapping symbol icons
// sharing a source, only one is drawn" pattern from the upstream
// issue.  Two textured-style quads are drawn at the same screen-space
// position; the second draw call shares vertex-array state with the
// first but with a different per-instance vertex buffer.
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef char GLchar;
typedef ptrdiff_t GLsizeiptr;

typedef GLuint (*PFNGLCREATESHADERPROC)(GLenum);
typedef void   (*PFNGLSHADERSOURCEPROC)(GLuint, GLsizei, const GLchar *const*, const GLint *);
typedef void   (*PFNGLCOMPILESHADERPROC)(GLuint);
typedef void   (*PFNGLGETSHADERIVPROC)(GLuint, GLenum, GLint *);
typedef void   (*PFNGLGETSHADERINFOLOGPROC)(GLuint, GLsizei, GLsizei *, GLchar *);
typedef GLuint (*PFNGLCREATEPROGRAMPROC)(void);
typedef void   (*PFNGLATTACHSHADERPROC)(GLuint, GLuint);
typedef void   (*PFNGLLINKPROGRAMPROC)(GLuint);
typedef void   (*PFNGLGETPROGRAMIVPROC)(GLuint, GLenum, GLint *);
typedef void   (*PFNGLGETPROGRAMINFOLOGPROC)(GLuint, GLsizei, GLsizei *, GLchar *);
typedef void   (*PFNGLUSEPROGRAMPROC)(GLuint);
typedef GLint  (*PFNGLGETUNIFORMLOCATIONPROC)(GLuint, const GLchar *);
typedef void   (*PFNGLUNIFORM3FPROC)(GLint, GLfloat, GLfloat, GLfloat);
typedef void   (*PFNGLGENBUFFERSPROC)(GLsizei, GLuint *);
typedef void   (*PFNGLBINDBUFFERPROC)(GLenum, GLuint);
typedef void   (*PFNGLBUFFERDATAPROC)(GLenum, GLsizeiptr, const void *, GLenum);
typedef void   (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef void   (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void *);
typedef GLint  (*PFNGLGETATTRIBLOCATIONPROC)(GLuint, const GLchar *);
typedef void   (*PFNGLDELETESHADERPROC)(GLuint);

#ifndef GL_VERTEX_SHADER
#define GL_VERTEX_SHADER    0x8B31
#define GL_FRAGMENT_SHADER  0x8B30
#define GL_ARRAY_BUFFER     0x8892
#define GL_ELEMENT_ARRAY_BUFFER 0x8893
#define GL_STATIC_DRAW      0x88E4
#define GL_COMPILE_STATUS   0x8B81
#define GL_LINK_STATUS      0x8B82
#endif

static PFNGLCREATESHADERPROC            glCreateShader;
static PFNGLSHADERSOURCEPROC            glShaderSource;
static PFNGLCOMPILESHADERPROC           glCompileShader;
static PFNGLGETSHADERIVPROC             glGetShaderiv;
static PFNGLGETSHADERINFOLOGPROC        glGetShaderInfoLog;
static PFNGLCREATEPROGRAMPROC           glCreateProgram;
static PFNGLATTACHSHADERPROC            glAttachShader;
static PFNGLLINKPROGRAMPROC             glLinkProgram;
static PFNGLGETPROGRAMIVPROC            glGetProgramiv;
static PFNGLGETPROGRAMINFOLOGPROC       glGetProgramInfoLog;
static PFNGLUSEPROGRAMPROC              glUseProgram;
static PFNGLGETUNIFORMLOCATIONPROC      glGetUniformLocation;
static PFNGLUNIFORM3FPROC               glUniform3f;
static PFNGLGENBUFFERSPROC              glGenBuffers;
static PFNGLBINDBUFFERPROC              glBindBuffer;
static PFNGLBUFFERDATAPROC              glBufferData;
static PFNGLENABLEVERTEXATTRIBARRAYPROC glEnableVertexAttribArray;
static PFNGLVERTEXATTRIBPOINTERPROC     glVertexAttribPointer;
static PFNGLGETATTRIBLOCATIONPROC       glGetAttribLocation;
static PFNGLDELETESHADERPROC            glDeleteShader;

#define LOAD_PROC(name) \
    name = (void *)glXGetProcAddress((const GLubyte *)#name); \
    if (!name) { fprintf(stderr, "resolve failed: " #name "\n"); return 1; }

static const char *VS =
    "#version 120\n"
    "attribute vec2 aPos;\n"
    "attribute vec2 aUV;\n"
    "varying vec2 vUV;\n"
    "void main(){ vUV = aUV; gl_Position = vec4(aPos, 0.0, 1.0); }\n";

static const char *FS =
    "#version 120\n"
    "varying vec2 vUV;\n"
    "uniform vec3 uColor;\n"
    "void main(){\n"
    "  float d = length(vUV - vec2(0.5));\n"
    "  float a = smoothstep(0.5, 0.35, d);\n"
    "  gl_FragColor = vec4(uColor, a);\n"
    "}\n";

static GLuint compile(GLenum t, const char *s) {
    GLuint sh = glCreateShader(t);
    glShaderSource(sh, 1, &s, NULL);
    glCompileShader(sh);
    GLint ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[512];
        glGetShaderInfoLog(sh, sizeof(log), NULL, log);
        fprintf(stderr, "shader compile: %s\n", log);
    }
    return sh;
}

static GLuint link_program(void) {
    GLuint vs = compile(GL_VERTEX_SHADER, VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    GLuint p = glCreateProgram();
    glAttachShader(p, vs);
    glAttachShader(p, fs);
    glLinkProgram(p);
    GLint ok = 0;
    glGetProgramiv(p, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[512];
        glGetProgramInfoLog(p, sizeof(log), NULL, log);
        fprintf(stderr, "link: %s\n", log);
    }
    glDeleteShader(vs);
    glDeleteShader(fs);
    return p;
}

int main(void) {
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }

    int attrs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo *vi = glXChooseVisual(dpy, 0, attrs);
    if (!vi) { fprintf(stderr, "no visual\n"); XCloseDisplay(dpy); return 1; }

    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    memset(&swa, 0, sizeof(swa));
    swa.colormap   = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 512, 512, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    if (!ctx) { fprintf(stderr, "no ctx\n"); return 1; }
    glXMakeCurrent(dpy, win, ctx);

    LOAD_PROC(glCreateShader);
    LOAD_PROC(glShaderSource);
    LOAD_PROC(glCompileShader);
    LOAD_PROC(glGetShaderiv);
    LOAD_PROC(glGetShaderInfoLog);
    LOAD_PROC(glCreateProgram);
    LOAD_PROC(glAttachShader);
    LOAD_PROC(glLinkProgram);
    LOAD_PROC(glGetProgramiv);
    LOAD_PROC(glGetProgramInfoLog);
    LOAD_PROC(glUseProgram);
    LOAD_PROC(glGetUniformLocation);
    LOAD_PROC(glUniform3f);
    LOAD_PROC(glGenBuffers);
    LOAD_PROC(glBindBuffer);
    LOAD_PROC(glBufferData);
    LOAD_PROC(glEnableVertexAttribArray);
    LOAD_PROC(glVertexAttribPointer);
    LOAD_PROC(glGetAttribLocation);
    LOAD_PROC(glDeleteShader);

    GLuint prog = link_program();
    glUseProgram(prog);
    GLint locColor = glGetUniformLocation(prog, "uColor");
    GLint locPos   = glGetAttribLocation(prog, "aPos");
    GLint locUV    = glGetAttribLocation(prog, "aUV");

    // Quad A ("animated/pulsing" icon) at center.
    float vertsA[] = {
        -0.15f,-0.15f, 0.0f,0.0f,
         0.15f,-0.15f, 1.0f,0.0f,
         0.15f, 0.15f, 1.0f,1.0f,
        -0.15f,-0.15f, 0.0f,0.0f,
         0.15f, 0.15f, 1.0f,1.0f,
        -0.15f, 0.15f, 0.0f,1.0f};
    // Quad B ("static" icon) sharing the same geometry source; same center.
    float vertsB[] = {
        -0.10f,-0.10f, 0.0f,0.0f,
         0.10f,-0.10f, 1.0f,0.0f,
         0.10f, 0.10f, 1.0f,1.0f,
        -0.10f,-0.10f, 0.0f,0.0f,
         0.10f, 0.10f, 1.0f,1.0f,
        -0.10f, 0.10f, 0.0f,1.0f};

    GLuint vboA, vboB;
    glGenBuffers(1, &vboA);
    glGenBuffers(1, &vboB);

    glBindBuffer(GL_ARRAY_BUFFER, vboA);
    glBufferData(GL_ARRAY_BUFFER, sizeof(vertsA), vertsA, GL_STATIC_DRAW);

    glBindBuffer(GL_ARRAY_BUFFER, vboB);
    glBufferData(GL_ARRAY_BUFFER, sizeof(vertsB), vertsB, GL_STATIC_DRAW);

    glClearColor(0.05f, 0.05f, 0.08f, 1.0f);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);

    for (int frame = 0; frame < 2; ++frame) {
        glClear(GL_COLOR_BUFFER_BIT);
        glUseProgram(prog);

        glUniform3f(locColor, 0.9f, 0.2f, 0.2f);
        glBindBuffer(GL_ARRAY_BUFFER, vboA);
        glEnableVertexAttribArray(locPos);
        glVertexAttribPointer(locPos, 2, GL_FLOAT, GL_FALSE,
                              4 * sizeof(float), (void *)0);
        glEnableVertexAttribArray(locUV);
        glVertexAttribPointer(locUV, 2, GL_FLOAT, GL_FALSE,
                              4 * sizeof(float),
                              (void *)(2 * sizeof(float)));
        glDrawArrays(GL_TRIANGLES, 0, 6);

        glUniform3f(locColor, 0.2f, 0.8f, 0.9f);
        glBindBuffer(GL_ARRAY_BUFFER, vboB);
        glEnableVertexAttribArray(locPos);
        glVertexAttribPointer(locPos, 2, GL_FLOAT, GL_FALSE,
                              4 * sizeof(float), (void *)0);
        glEnableVertexAttribArray(locUV);
        glVertexAttribPointer(locUV, 2, GL_FLOAT, GL_FALSE,
                              4 * sizeof(float),
                              (void *)(2 * sizeof(float)));
        glDrawArrays(GL_TRIANGLES, 0, 6);

        glXSwapBuffers(dpy, win);
    }

    XFree(vi);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}
