// SOURCE: synthetic (no upstream)
// Program re-links between uniform query and draw.
//
// Minimal OpenGL 2.1 compatible program. Uses GLX for context.
// Link: -lGL -lX11 -lm only. Compiles with:
//   gcc -Wall -std=gnu11 main.c -lGL -lX11 -lm
// Runs under Xvfb; renders 3 frames then exits cleanly.
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <stdio.h>
#include <stdlib.h>

typedef GLuint (*fn_CreateShader)(GLenum);
typedef void   (*fn_ShaderSource)(GLuint, GLsizei, const char* const*, const GLint*);
typedef void   (*fn_CompileShader)(GLuint);
typedef void   (*fn_GetShaderiv)(GLuint, GLenum, GLint*);
typedef void   (*fn_GetShaderInfoLog)(GLuint, GLsizei, GLsizei*, char*);
typedef GLuint (*fn_CreateProgram)(void);
typedef void   (*fn_AttachShader)(GLuint, GLuint);
typedef void   (*fn_DetachShader)(GLuint, GLuint);
typedef void   (*fn_LinkProgram)(GLuint);
typedef void   (*fn_GetProgramiv)(GLuint, GLenum, GLint*);
typedef void   (*fn_UseProgram)(GLuint);
typedef GLint  (*fn_GetUniformLocation)(GLuint, const char*);
typedef void   (*fn_Uniform4f)(GLint, GLfloat, GLfloat, GLfloat, GLfloat);
typedef void   (*fn_GenBuffers)(GLsizei, GLuint*);
typedef void   (*fn_BindBuffer)(GLenum, GLuint);
typedef void   (*fn_BufferData)(GLenum, GLsizeiptr, const void*, GLenum);
typedef void   (*fn_EnableVertexAttribArray)(GLuint);
typedef void   (*fn_VertexAttribPointer)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void   (*fn_BindAttribLocation)(GLuint, GLuint, const char*);

static fn_CreateShader            p_CreateShader;
static fn_ShaderSource            p_ShaderSource;
static fn_CompileShader           p_CompileShader;
static fn_GetShaderiv             p_GetShaderiv;
static fn_GetShaderInfoLog        p_GetShaderInfoLog;
static fn_CreateProgram           p_CreateProgram;
static fn_AttachShader            p_AttachShader;
static fn_DetachShader            p_DetachShader;
static fn_LinkProgram             p_LinkProgram;
static fn_GetProgramiv            p_GetProgramiv;
static fn_UseProgram              p_UseProgram;
static fn_GetUniformLocation      p_GetUniformLocation;
static fn_Uniform4f               p_Uniform4f;
static fn_GenBuffers              p_GenBuffers;
static fn_BindBuffer              p_BindBuffer;
static fn_BufferData              p_BufferData;
static fn_EnableVertexAttribArray p_EnableVertexAttribArray;
static fn_VertexAttribPointer     p_VertexAttribPointer;
static fn_BindAttribLocation      p_BindAttribLocation;

#define LOAD(T, var, sym) \
    do { var = (T)glXGetProcAddress((const GLubyte*)sym); \
         if (!var) { fprintf(stderr, "missing %s\n", sym); exit(1); } } while (0)

static GLuint compile_shader(GLenum type, const char* src) {
    GLuint s = p_CreateShader(type);
    p_ShaderSource(s, 1, &src, NULL);
    p_CompileShader(s);
    GLint ok;
    p_GetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        p_GetShaderInfoLog(s, sizeof(log), NULL, log);
        fprintf(stderr, "shader compile failed: %s\n", log);
        exit(1);
    }
    return s;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int attrs[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, attrs);
    if (!vi) { fprintf(stderr, "no visual\n"); return 1; }
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

    LOAD(fn_CreateShader,            p_CreateShader,            "glCreateShader");
    LOAD(fn_ShaderSource,            p_ShaderSource,            "glShaderSource");
    LOAD(fn_CompileShader,           p_CompileShader,           "glCompileShader");
    LOAD(fn_GetShaderiv,             p_GetShaderiv,             "glGetShaderiv");
    LOAD(fn_GetShaderInfoLog,        p_GetShaderInfoLog,        "glGetShaderInfoLog");
    LOAD(fn_CreateProgram,           p_CreateProgram,           "glCreateProgram");
    LOAD(fn_AttachShader,            p_AttachShader,            "glAttachShader");
    LOAD(fn_DetachShader,            p_DetachShader,            "glDetachShader");
    LOAD(fn_LinkProgram,             p_LinkProgram,             "glLinkProgram");
    LOAD(fn_GetProgramiv,            p_GetProgramiv,            "glGetProgramiv");
    LOAD(fn_UseProgram,              p_UseProgram,              "glUseProgram");
    LOAD(fn_GetUniformLocation,      p_GetUniformLocation,      "glGetUniformLocation");
    LOAD(fn_Uniform4f,               p_Uniform4f,               "glUniform4f");
    LOAD(fn_GenBuffers,              p_GenBuffers,              "glGenBuffers");
    LOAD(fn_BindBuffer,              p_BindBuffer,              "glBindBuffer");
    LOAD(fn_BufferData,              p_BufferData,              "glBufferData");
    LOAD(fn_EnableVertexAttribArray, p_EnableVertexAttribArray, "glEnableVertexAttribArray");
    LOAD(fn_VertexAttribPointer,     p_VertexAttribPointer,     "glVertexAttribPointer");
    LOAD(fn_BindAttribLocation,      p_BindAttribLocation,      "glBindAttribLocation");

    const char* vs_src =
        "#version 120\n"
        "attribute vec2 aPos;\n"
        "void main(){ gl_Position = vec4(aPos, 0.0, 1.0); }\n";

    const char* fs_a =
        "#version 120\n"
        "uniform vec4 uTint;\n"
        "uniform vec4 uColor;\n"
        "void main(){ gl_FragColor = vec4(uColor.rgb * uTint.a, 1.0); }\n";

    const char* fs_b =
        "#version 120\n"
        "uniform vec4 uColor;\n"
        "void main(){ gl_FragColor = vec4(uColor.rgb, 1.0); }\n";

    GLuint vs  = compile_shader(GL_VERTEX_SHADER,   vs_src);
    GLuint fsA = compile_shader(GL_FRAGMENT_SHADER, fs_a);
    GLuint fsB = compile_shader(GL_FRAGMENT_SHADER, fs_b);

    GLuint prog = p_CreateProgram();
    p_AttachShader(prog, vs);
    p_AttachShader(prog, fsA);
    p_BindAttribLocation(prog, 0, "aPos");
    p_LinkProgram(prog);
    GLint linked;
    p_GetProgramiv(prog, GL_LINK_STATUS, &linked);
    if (!linked) { fprintf(stderr, "link A failed\n"); return 1; }

    GLint locColor = p_GetUniformLocation(prog, "uColor");

    float quad[] = { -1.0f,-1.0f,  1.0f,-1.0f,  -1.0f,1.0f,  1.0f,1.0f };
    GLuint vbo;
    p_GenBuffers(1, &vbo);
    p_BindBuffer(GL_ARRAY_BUFFER, vbo);
    p_BufferData(GL_ARRAY_BUFFER, (GLsizeiptr)sizeof(quad), quad, GL_STATIC_DRAW);
    p_EnableVertexAttribArray(0);
    p_VertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL);

    p_DetachShader(prog, fsA);
    p_AttachShader(prog, fsB);
    p_LinkProgram(prog);
    p_GetProgramiv(prog, GL_LINK_STATUS, &linked);
    if (!linked) { fprintf(stderr, "link B failed\n"); return 1; }

    p_UseProgram(prog);
    glViewport(0, 0, 400, 300);

    for (int frame = 0; frame < 3; frame++) {
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        p_Uniform4f(locColor, 1.0f, 0.0f, 0.0f, 1.0f);
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
        glXSwapBuffers(dpy, win);
    }

    unsigned char px[4] = {0};
    glReadPixels(200, 150, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center RGBA: %u %u %u %u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, NULL, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    (void)vs; (void)fsB;
    return 0;
}