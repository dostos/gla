// SOURCE: synthetic (no upstream)
// Two-program renderer: dark-gray background quad + centered red quad,
// each drawn by a separate GLSL program that exposes a uniform named uColor.
//
// Minimal OpenGL 2.1 compatible program. Uses GLX for context.
// Link: -lGL -lX11 -lm only. Compiles with:
//   gcc -Wall -std=gnu11 main.c -lGL -lX11 -lm
// Runs under Xvfb; exits cleanly after rendering 3 frames.
// The rendered output manifests on the first frame.
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>

#define GL_COMPILE_STATUS 0x8B81
#define GL_LINK_STATUS    0x8B82
#define GL_FRAGMENT_SHADER 0x8B30
#define GL_VERTEX_SHADER   0x8B31
#define GL_ARRAY_BUFFER    0x8892
#define GL_STATIC_DRAW     0x88E4

typedef GLuint (*PFN_CREATESHADER)(GLenum);
typedef void   (*PFN_SHADERSOURCE)(GLuint, GLsizei, const char* const*, const GLint*);
typedef void   (*PFN_COMPILESHADER)(GLuint);
typedef void   (*PFN_GETSHADERIV)(GLuint, GLenum, GLint*);
typedef void   (*PFN_GETSHADERINFOLOG)(GLuint, GLsizei, GLsizei*, char*);
typedef GLuint (*PFN_CREATEPROGRAM)(void);
typedef void   (*PFN_ATTACHSHADER)(GLuint, GLuint);
typedef void   (*PFN_LINKPROGRAM)(GLuint);
typedef void   (*PFN_GETPROGRAMIV)(GLuint, GLenum, GLint*);
typedef void   (*PFN_USEPROGRAM)(GLuint);
typedef GLint  (*PFN_GETUNIFORMLOCATION)(GLuint, const char*);
typedef void   (*PFN_UNIFORM4F)(GLint, GLfloat, GLfloat, GLfloat, GLfloat);
typedef void   (*PFN_GENBUFFERS)(GLsizei, GLuint*);
typedef void   (*PFN_BINDBUFFER)(GLenum, GLuint);
typedef void   (*PFN_BUFFERDATA)(GLenum, ptrdiff_t, const void*, GLenum);
typedef void   (*PFN_VERTEXATTRIBPOINTER)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void   (*PFN_ENABLEVERTEXATTRIBARRAY)(GLuint);
typedef void   (*PFN_BINDATTRIBLOCATION)(GLuint, GLuint, const char*);

static PFN_CREATESHADER            gl_CreateShader;
static PFN_SHADERSOURCE            gl_ShaderSource;
static PFN_COMPILESHADER           gl_CompileShader;
static PFN_GETSHADERIV             gl_GetShaderiv;
static PFN_GETSHADERINFOLOG        gl_GetShaderInfoLog;
static PFN_CREATEPROGRAM           gl_CreateProgram;
static PFN_ATTACHSHADER            gl_AttachShader;
static PFN_LINKPROGRAM             gl_LinkProgram;
static PFN_GETPROGRAMIV            gl_GetProgramiv;
static PFN_USEPROGRAM              gl_UseProgram;
static PFN_GETUNIFORMLOCATION      gl_GetUniformLocation;
static PFN_UNIFORM4F               gl_Uniform4f;
static PFN_GENBUFFERS              gl_GenBuffers;
static PFN_BINDBUFFER              gl_BindBuffer;
static PFN_BUFFERDATA              gl_BufferData;
static PFN_VERTEXATTRIBPOINTER     gl_VertexAttribPointer;
static PFN_ENABLEVERTEXATTRIBARRAY gl_EnableVertexAttribArray;
static PFN_BINDATTRIBLOCATION      gl_BindAttribLocation;

#define LOAD(name, suf) gl_##name = (PFN_##suf)glXGetProcAddress((const GLubyte*)"gl" #name)

static void load_gl_funcs(void) {
    LOAD(CreateShader, CREATESHADER);
    LOAD(ShaderSource, SHADERSOURCE);
    LOAD(CompileShader, COMPILESHADER);
    LOAD(GetShaderiv, GETSHADERIV);
    LOAD(GetShaderInfoLog, GETSHADERINFOLOG);
    LOAD(CreateProgram, CREATEPROGRAM);
    LOAD(AttachShader, ATTACHSHADER);
    LOAD(LinkProgram, LINKPROGRAM);
    LOAD(GetProgramiv, GETPROGRAMIV);
    LOAD(UseProgram, USEPROGRAM);
    LOAD(GetUniformLocation, GETUNIFORMLOCATION);
    LOAD(Uniform4f, UNIFORM4F);
    LOAD(GenBuffers, GENBUFFERS);
    LOAD(BindBuffer, BINDBUFFER);
    LOAD(BufferData, BUFFERDATA);
    LOAD(VertexAttribPointer, VERTEXATTRIBPOINTER);
    LOAD(EnableVertexAttribArray, ENABLEVERTEXATTRIBARRAY);
    LOAD(BindAttribLocation, BINDATTRIBLOCATION);
}

static GLuint build_program(const char* vs_src, const char* fs_src) {
    GLuint v = gl_CreateShader(GL_VERTEX_SHADER);
    gl_ShaderSource(v, 1, &vs_src, NULL);
    gl_CompileShader(v);
    GLint ok = 0;
    gl_GetShaderiv(v, GL_COMPILE_STATUS, &ok);
    if (!ok) { char log[512]; gl_GetShaderInfoLog(v, 512, NULL, log); fprintf(stderr, "vs: %s\n", log); exit(1); }
    GLuint f = gl_CreateShader(GL_FRAGMENT_SHADER);
    gl_ShaderSource(f, 1, &fs_src, NULL);
    gl_CompileShader(f);
    gl_GetShaderiv(f, GL_COMPILE_STATUS, &ok);
    if (!ok) { char log[512]; gl_GetShaderInfoLog(f, 512, NULL, log); fprintf(stderr, "fs: %s\n", log); exit(1); }
    GLuint prog = gl_CreateProgram();
    gl_AttachShader(prog, v);
    gl_AttachShader(prog, f);
    gl_BindAttribLocation(prog, 0, "aPos");
    gl_LinkProgram(prog);
    gl_GetProgramiv(prog, GL_LINK_STATUS, &ok);
    if (!ok) { fprintf(stderr, "link failed\n"); exit(1); }
    return prog;
}

static const char* vs_src =
    "#version 120\n"
    "attribute vec2 aPos;\n"
    "void main() { gl_Position = vec4(aPos, 0.0, 1.0); }\n";

static const char* fs_src =
    "#version 120\n"
    "uniform vec4 uColor;\n"
    "void main() { gl_FragColor = uColor; }\n";

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int attrs[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attrs);
    if (!vi) { fprintf(stderr, "glXChooseVisual failed\n"); return 1; }
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 400, 300, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);
    load_gl_funcs();

    GLuint progBg = build_program(vs_src, fs_src);
    GLuint progFg = build_program(vs_src, fs_src);
    GLint locBgColor = gl_GetUniformLocation(progBg, "uColor");
    GLint locFgColor = gl_GetUniformLocation(progFg, "uColor");

    float verts[] = {
        -1.0f, -1.0f,   1.0f, -1.0f,   1.0f,  1.0f,
        -1.0f, -1.0f,   1.0f,  1.0f,  -1.0f,  1.0f,
        -0.3f, -0.3f,   0.3f, -0.3f,   0.3f,  0.3f,
        -0.3f, -0.3f,   0.3f,  0.3f,  -0.3f,  0.3f,
    };
    GLuint vbo;
    gl_GenBuffers(1, &vbo);
    gl_BindBuffer(GL_ARRAY_BUFFER, vbo);
    gl_BufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    gl_EnableVertexAttribArray(0);
    gl_VertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);

    glViewport(0, 0, 400, 300);

    for (int frame = 0; frame < 3; frame++) {
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);

        gl_UseProgram(progBg);
        gl_Uniform4f(locBgColor, 0.2f, 0.2f, 0.2f, 1.0f);
        gl_Uniform4f(locFgColor, 1.0f, 0.0f, 0.0f, 1.0f);

        glDrawArrays(GL_TRIANGLES, 0, 6);

        gl_UseProgram(progFg);
        glDrawArrays(GL_TRIANGLES, 6, 6);

        glXSwapBuffers(dpy, win);
    }

    unsigned char px[4] = {0, 0, 0, 0};
    glReadPixels(200, 150, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center RGBA: %u %u %u %u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}