// SOURCE: https://github.com/mapbox/mapbox-gl-js/issues/13555
//
// R5: 16-bit index buffer overflow
//
// A mesh with > 65535 vertices is drawn with a GL_UNSIGNED_SHORT index buffer.
// Indices that should address vertices >= 65536 wrap to low values (i & 0xFFFF),
// so the upper portion of the geometry never renders at its intended location.
//
// Repro: 70000 vertices.
//   Indices 0..65535    -> green points along y = -0.5 (bottom strip).
//   Indices 65536..69999 -> red points along y = +0.5 (top strip).
// Index buffer stored as GLushort, so logical indices are truncated.
// Expected: green strip at bottom, red strip at top.
// Actual:   only a green strip at the bottom; no red pixels at top.

#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

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
    "attribute vec3 aCol;\n"
    "varying vec3 vCol;\n"
    "void main() {\n"
    "    gl_Position = vec4(aPos, 0.0, 1.0);\n"
    "    gl_PointSize = 3.0;\n"
    "    vCol = aCol;\n"
    "}\n";

static const char *frag_src =
    "#version 120\n"
    "varying vec3 vCol;\n"
    "void main() { gl_FragColor = vec4(vCol, 1.0); }\n";

#define N_VERTS 70000

static int xerror_handler(Display *dpy, XErrorEvent *ev) {
    (void)dpy; (void)ev;
    return 0;
}

int main(void)
{
    XSetErrorHandler(xerror_handler);
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "Cannot open X display\n"); return 1; }

    int attrs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo *vi = glXChooseVisual(dpy, 0, attrs);
    if (!vi) { fprintf(stderr, "No suitable GLX visual\n"); return 1; }

    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    memset(&swa, 0, sizeof(swa));
    swa.colormap   = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 400, 300, 0, vi->depth,
                               InputOutput, vi->visual, CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    XStoreName(dpy, win, "R5: 16-bit index buffer overflow");

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

    glViewport(0, 0, 400, 300);
    glEnable(0x8642);  // GL_PROGRAM_POINT_SIZE

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
    GLint ok = 0;
    glGetProgramiv(prog, GL_LINK_STATUS, &ok);
    if (!ok) { fprintf(stderr, "Program link failed\n"); return 1; }

    GLint locPos = glGetAttribLocation(prog, "aPos");
    GLint locCol = glGetAttribLocation(prog, "aCol");

    // Interleaved: x, y, r, g, b (5 floats per vertex)
    float *verts = (float*)malloc((size_t)N_VERTS * 5 * sizeof(float));
    for (int i = 0; i < N_VERTS; i++) {
        float t = (float)i / (float)N_VERTS;
        verts[i*5 + 0] = t * 2.0f - 1.0f;          // x: -1..+1
        if (i < 65536) {
            verts[i*5 + 1] = -0.5f;                // bottom strip
            verts[i*5 + 2] = 0.0f; verts[i*5 + 3] = 1.0f; verts[i*5 + 4] = 0.0f;  // green
        } else {
            verts[i*5 + 1] = 0.5f;                 // top strip
            verts[i*5 + 2] = 1.0f; verts[i*5 + 3] = 0.0f; verts[i*5 + 4] = 0.0f;  // red
        }
    }

    // Index buffer stored as uint16. Logical indices 0..N_VERTS-1,
    // but values >= 65536 silently truncate to (i & 0xFFFF) on store.
    GLushort *idx = (GLushort*)malloc((size_t)N_VERTS * sizeof(GLushort));
    for (int i = 0; i < N_VERTS; i++) idx[i] = (GLushort)i;

    GLuint vao, vbo, ebo;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, (GLsizeiptr)N_VERTS * 5 * sizeof(float), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray((GLuint)locPos);
    glVertexAttribPointer((GLuint)locPos, 2, GL_FLOAT, GL_FALSE,
                          5 * sizeof(float), (void*)0);
    glEnableVertexAttribArray((GLuint)locCol);
    glVertexAttribPointer((GLuint)locCol, 3, GL_FLOAT, GL_FALSE,
                          5 * sizeof(float), (void*)(2 * sizeof(float)));

    glGenBuffers(1, &ebo);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER,
                 (GLsizeiptr)N_VERTS * sizeof(GLushort), idx, GL_STATIC_DRAW);

    for (int frame = 0; frame < 5; frame++) {
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        glUseProgram(prog);
        glBindVertexArray(vao);
        glDrawElements(GL_POINTS, N_VERTS, GL_UNSIGNED_SHORT, (void*)0);

        glXSwapBuffers(dpy, win);
    }

    free(verts);
    free(idx);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, glc);
    XDestroyWindow(dpy, win);
    XFreeColormap(dpy, swa.colormap);
    XFree(vi);
    XCloseDisplay(dpy);

    printf("r5_bug_in_rendering_glb_models: completed 5 frames\n");
    return 0;
}