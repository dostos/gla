// SOURCE: https://github.com/mrdoob/three.js/issues/26784

#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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
typedef void   (*PFNGLGENBUFFERSPROC)(GLsizei, GLuint *);
typedef void   (*PFNGLBINDBUFFERPROC)(GLenum, GLuint);
typedef void   (*PFNGLBUFFERDATAPROC)(GLenum, GLsizeiptr, const void *, GLenum);
typedef void   (*PFNGLGENVERTEXARRAYSPROC)(GLsizei, GLuint *);
typedef void   (*PFNGLBINDVERTEXARRAYPROC)(GLuint);
typedef void   (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef void   (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void *);
typedef GLint  (*PFNGLGETATTRIBLOCATIONPROC)(GLuint, const GLchar *);

#define LOAD_PROC(type, name) \
    type name = (type)glXGetProcAddress((const GLubyte *)#name); \
    if (!name) { fprintf(stderr, "Cannot resolve " #name "\n"); return 1; }

static const char *vert_src =
    "#version 120\n"
    "attribute vec2 aPos;\n"
    "void main() { gl_Position = vec4(aPos, 0.0, 1.0); }\n";

static const char *frag_src =
    "#version 120\n"
    "void main() { gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0); }\n";

int main(void)
{
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "Cannot open X display\n"); return 1; }

    int attrs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo *vi = glXChooseVisual(dpy, 0, attrs);
    if (!vi) { fprintf(stderr, "No GLX visual\n"); return 1; }

    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    memset(&swa, 0, sizeof(swa));
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 400, 400, 0, vi->depth,
                               InputOutput, vi->visual, CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    XStoreName(dpy, win, "R4: Bevel Linejoin Reversed Winding");

    GLXContext glc = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    if (!glc) { fprintf(stderr, "Cannot create GL context\n"); return 1; }
    glXMakeCurrent(dpy, win, glc);

    LOAD_PROC(PFNGLCREATESHADERPROC,            glCreateShader)
    LOAD_PROC(PFNGLSHADERSOURCEPROC,            glShaderSource)
    LOAD_PROC(PFNGLCOMPILESHADERPROC,           glCompileShader)
    LOAD_PROC(PFNGLGETSHADERIVPROC,             glGetShaderiv)
    LOAD_PROC(PFNGLGETSHADERINFOLOGPROC,        glGetShaderInfoLog)
    LOAD_PROC(PFNGLCREATEPROGRAMPROC,           glCreateProgram)
    LOAD_PROC(PFNGLATTACHSHADERPROC,            glAttachShader)
    LOAD_PROC(PFNGLLINKPROGRAMPROC,             glLinkProgram)
    LOAD_PROC(PFNGLGETPROGRAMIVPROC,            glGetProgramiv)
    LOAD_PROC(PFNGLGETPROGRAMINFOLOGPROC,       glGetProgramInfoLog)
    LOAD_PROC(PFNGLUSEPROGRAMPROC,              glUseProgram)
    LOAD_PROC(PFNGLGENBUFFERSPROC,              glGenBuffers)
    LOAD_PROC(PFNGLBINDBUFFERPROC,              glBindBuffer)
    LOAD_PROC(PFNGLBUFFERDATAPROC,              glBufferData)
    LOAD_PROC(PFNGLGENVERTEXARRAYSPROC,         glGenVertexArrays)
    LOAD_PROC(PFNGLBINDVERTEXARRAYPROC,         glBindVertexArray)
    LOAD_PROC(PFNGLENABLEVERTEXATTRIBARRAYPROC, glEnableVertexAttribArray)
    LOAD_PROC(PFNGLVERTEXATTRIBPOINTERPROC,     glVertexAttribPointer)
    LOAD_PROC(PFNGLGETATTRIBLOCATIONPROC,       glGetAttribLocation)

    glViewport(0, 0, 400, 400);

    // CCW front, cull back.
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    glFrontFace(GL_CCW);

    GLuint vs = glCreateShader(GL_VERTEX_SHADER);
    glShaderSource(vs, 1, &vert_src, NULL);
    glCompileShader(vs);
    GLuint fs = glCreateShader(GL_FRAGMENT_SHADER);
    glShaderSource(fs, 1, &frag_src, NULL);
    glCompileShader(fs);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);
    GLint locPos = glGetAttribLocation(prog, "aPos");

    // Stroked V-shape (3-point polyline) with half-width 0.05 in NDC.
    // P0=(-0.5,-0.5), P1=(0,0), P2=(0.5,-0.5). Perpendicular-left offsets:
    //   seg A: left = (-0.0354, +0.0354)
    //   seg B: left = (+0.0354, +0.0354)
    static const GLfloat verts[] = {
        // --- Segment A quad, CCW (two triangles) ---
        // tri: LA0, RA0, RA1
        -0.5354f, -0.4646f,
        -0.4646f, -0.5354f,
         0.0354f, -0.0354f,
        // tri: LA0, RA1, LA1
        -0.5354f, -0.4646f,
         0.0354f, -0.0354f,
        -0.0354f,  0.0354f,

        // --- Segment B quad, CCW ---
        // tri: LB1, RB1, RB2
         0.0354f,  0.0354f,
        -0.0354f, -0.0354f,
         0.4646f, -0.5354f,
        // tri: LB1, RB2, LB2
         0.0354f,  0.0354f,
         0.4646f, -0.5354f,
         0.5354f, -0.4646f,

        // --- Bevel join triangle at P1 ---
        -0.0354f,  0.0354f,
         0.0354f,  0.0354f,
         0.0000f,  0.0000f,
    };

    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray((GLuint)locPos);
    glVertexAttribPointer((GLuint)locPos, 2, GL_FLOAT, GL_FALSE,
                          2 * sizeof(GLfloat), (void *)0);

    for (int frame = 0; frame < 3; frame++) {
        glClearColor(1.0f, 1.0f, 1.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glUseProgram(prog);
        glBindVertexArray(vao);
        glDrawArrays(GL_TRIANGLES, 0, 15);
        glXSwapBuffers(dpy, win);
    }

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, glc);
    XDestroyWindow(dpy, win);
    XFreeColormap(dpy, swa.colormap);
    XFree(vi);
    XCloseDisplay(dpy);

    printf("r4_svgloader_pointstostroke_incorrect_resul: completed 3 frames\n");
    return 0;
}