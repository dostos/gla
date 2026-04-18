// tests/eval/e6_depth_precision.c
//
// E6: Depth Buffer Precision
//
// Two overlapping quads at z=-0.5 and z=-0.500001 rendered with a perspective
// projection.
//
// Clear color: dark purple (0.15, 0.0, 0.15)

#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

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
typedef void   (*PFNGLUNIFORM4FPROC)(GLint, GLfloat, GLfloat, GLfloat, GLfloat);
typedef void   (*PFNGLUNIFORMMATRIX4FVPROC)(GLint, GLsizei, GLboolean, const GLfloat *);
typedef void   (*PFNGLGENBUFFERSPROC)(GLsizei, GLuint *);
typedef void   (*PFNGLBINDBUFFERPROC)(GLenum, GLuint);
typedef void   (*PFNGLBUFFERDATAPROC)(GLenum, GLsizeiptr, const void *, GLenum);
typedef void   (*PFNGLGENVERTEXARRAYSPROC)(GLsizei, GLuint *);
typedef void   (*PFNGLBINDVERTEXARRAYPROC)(GLuint);
typedef void   (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef void   (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void *);
typedef GLint  (*PFNGLGETATTRIBLOCATIONPROC)(GLuint, const GLchar *);
typedef void   (*PFNGLDELETESHADERPROC)(GLuint);
typedef void   (*PFNGLDELETEPROGRAMPROC)(GLuint);
typedef void   (*PFNGLDELETEBUFFERSPROC)(GLsizei, const GLuint *);
typedef void   (*PFNGLDELETEVERTEXARRAYSPROC)(GLsizei, const GLuint *);

#define LOAD_PROC(type, name) \
    type name = (type)glXGetProcAddress((const GLubyte *)#name); \
    if (!name) { fprintf(stderr, "Cannot resolve " #name "\n"); return 1; }

/* Vertex shader: transforms aPos with uMVP, passes uColor through */
static const char *vert_src =
    "#version 120\n"
    "attribute vec3 aPos;\n"
    "uniform mat4 uMVP;\n"
    "void main() { gl_Position = uMVP * vec4(aPos, 1.0); }\n";

static const char *frag_src =
    "#version 120\n"
    "uniform vec4 uColor;\n"
    "void main() { gl_FragColor = uColor; }\n";

/* Build column-major perspective matrix. */
static void make_perspective(float *m, float fovy_deg, float aspect,
                              float near_z, float far_z)
{
    float f  = 1.0f / tanf(fovy_deg * 3.14159265f / 360.0f);
    float nf = 1.0f / (near_z - far_z);
    memset(m, 0, 16 * sizeof(float));
    m[0]  =  f / aspect;
    m[5]  =  f;
    m[10] = (far_z + near_z) * nf;
    m[11] = -1.0f;
    m[14] =  2.0f * far_z * near_z * nf;
}

static GLuint compile_shader(
    PFNGLCREATESHADERPROC glCreateShader,
    PFNGLSHADERSOURCEPROC glShaderSource,
    PFNGLCOMPILESHADERPROC glCompileShader,
    PFNGLGETSHADERIVPROC glGetShaderiv,
    PFNGLGETSHADERINFOLOGPROC glGetShaderInfoLog,
    GLenum type, const char *src)
{
    GLuint id = glCreateShader(type);
    glShaderSource(id, 1, &src, NULL);
    glCompileShader(id);
    GLint ok = 0;
    glGetShaderiv(id, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[512];
        glGetShaderInfoLog(id, sizeof(log), NULL, log);
        fprintf(stderr, "Shader compile error: %s\n", log);
        return 0;
    }
    return id;
}

int main(void)
{
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "Cannot open X display\n"); return 1; }

    int attrs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo *vi = glXChooseVisual(dpy, 0, attrs);
    if (!vi) { fprintf(stderr, "No suitable GLX visual\n"); XCloseDisplay(dpy); return 1; }

    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    memset(&swa, 0, sizeof(swa));
    swa.colormap   = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 400, 300, 0, vi->depth,
                               InputOutput, vi->visual, CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    XStoreName(dpy, win, "E6: Depth Precision Bug");

    GLXContext glc = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    if (!glc) { fprintf(stderr, "Cannot create GL context\n"); return 1; }
    glXMakeCurrent(dpy, win, glc);

    LOAD_PROC(PFNGLCREATESHADERPROC,          glCreateShader)
    LOAD_PROC(PFNGLSHADERSOURCEPROC,          glShaderSource)
    LOAD_PROC(PFNGLCOMPILESHADERPROC,         glCompileShader)
    LOAD_PROC(PFNGLGETSHADERIVPROC,           glGetShaderiv)
    LOAD_PROC(PFNGLGETSHADERINFOLOGPROC,      glGetShaderInfoLog)
    LOAD_PROC(PFNGLCREATEPROGRAMPROC,         glCreateProgram)
    LOAD_PROC(PFNGLATTACHSHADERPROC,          glAttachShader)
    LOAD_PROC(PFNGLLINKPROGRAMPROC,           glLinkProgram)
    LOAD_PROC(PFNGLGETPROGRAMIVPROC,          glGetProgramiv)
    LOAD_PROC(PFNGLGETPROGRAMINFOLOGPROC,     glGetProgramInfoLog)
    LOAD_PROC(PFNGLUSEPROGRAMPROC,            glUseProgram)
    LOAD_PROC(PFNGLGETUNIFORMLOCATIONPROC,    glGetUniformLocation)
    LOAD_PROC(PFNGLUNIFORM4FPROC,             glUniform4f)
    LOAD_PROC(PFNGLUNIFORMMATRIX4FVPROC,      glUniformMatrix4fv)
    LOAD_PROC(PFNGLGENBUFFERSPROC,            glGenBuffers)
    LOAD_PROC(PFNGLBINDBUFFERPROC,            glBindBuffer)
    LOAD_PROC(PFNGLBUFFERDATAPROC,            glBufferData)
    LOAD_PROC(PFNGLGENVERTEXARRAYSPROC,       glGenVertexArrays)
    LOAD_PROC(PFNGLBINDVERTEXARRAYPROC,       glBindVertexArray)
    LOAD_PROC(PFNGLENABLEVERTEXATTRIBARRAYPROC, glEnableVertexAttribArray)
    LOAD_PROC(PFNGLVERTEXATTRIBPOINTERPROC,   glVertexAttribPointer)
    LOAD_PROC(PFNGLGETATTRIBLOCATIONPROC,     glGetAttribLocation)
    LOAD_PROC(PFNGLDELETESHADERPROC,          glDeleteShader)
    LOAD_PROC(PFNGLDELETEPROGRAMPROC,         glDeleteProgram)
    LOAD_PROC(PFNGLDELETEBUFFERSPROC,         glDeleteBuffers)
    LOAD_PROC(PFNGLDELETEVERTEXARRAYSPROC,    glDeleteVertexArrays)

    glViewport(0, 0, 400, 300);
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);

    GLuint vs = compile_shader(glCreateShader, glShaderSource, glCompileShader,
                               glGetShaderiv, glGetShaderInfoLog,
                               GL_VERTEX_SHADER, vert_src);
    GLuint fs = compile_shader(glCreateShader, glShaderSource, glCompileShader,
                               glGetShaderiv, glGetShaderInfoLog,
                               GL_FRAGMENT_SHADER, frag_src);
    if (!vs || !fs) return 1;

    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);
    {
        GLint ok = 0;
        glGetProgramiv(prog, GL_LINK_STATUS, &ok);
        if (!ok) { fprintf(stderr, "Program link error\n"); return 1; }
    }
    glDeleteShader(vs);
    glDeleteShader(fs);

    GLint mvpLoc   = glGetUniformLocation(prog, "uMVP");
    GLint colorLoc = glGetUniformLocation(prog, "uColor");
    GLint posLoc   = glGetAttribLocation(prog,  "aPos");

    /* Quad A (green) at z=-0.5, Quad B (red) at z=-0.500001. */
    static const GLfloat verts[] = {
        /* Quad A at z = -0.5 (green) */
        -0.6f, -0.6f, -0.5f,
         0.6f, -0.6f, -0.5f,
         0.6f,  0.6f, -0.5f,
        -0.6f, -0.6f, -0.5f,
         0.6f,  0.6f, -0.5f,
        -0.6f,  0.6f, -0.5f,
        /* Quad B at z = -0.500001 (red) */
        -0.6f, -0.6f, -0.500001f,
         0.6f, -0.6f, -0.500001f,
         0.6f,  0.6f, -0.500001f,
        -0.6f, -0.6f, -0.500001f,
         0.6f,  0.6f, -0.500001f,
        -0.6f,  0.6f, -0.500001f,
    };

    GLuint vao = 0, vbo = 0;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray((GLuint)posLoc);
    glVertexAttribPointer((GLuint)posLoc, 3, GL_FLOAT, GL_FALSE,
                          3 * sizeof(GLfloat), (void *)0);

    float mvp[16];
    make_perspective(mvp, 90.0f, 400.0f / 300.0f, 0.001f, 100000.0f);

    for (int i = 0; i < 5; i++) {
        /* Clear to dark purple */
        glClearColor(0.15f, 0.0f, 0.15f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        glUseProgram(prog);
        glUniformMatrix4fv(mvpLoc, 1, GL_FALSE, mvp);
        glBindVertexArray(vao);

        /* Draw Quad A (green) */
        glUniform4f(colorLoc, 0.0f, 0.9f, 0.0f, 1.0f);
        glDrawArrays(GL_TRIANGLES, 0, 6);

        /* Draw Quad B (red) */
        glUniform4f(colorLoc, 0.9f, 0.0f, 0.0f, 1.0f);
        glDrawArrays(GL_TRIANGLES, 6, 6);

        glXSwapBuffers(dpy, win);
    }

    glDeleteVertexArrays(1, &vao);
    glDeleteBuffers(1, &vbo);
    glDeleteProgram(prog);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, glc);
    XDestroyWindow(dpy, win);
    XFreeColormap(dpy, swa.colormap);
    XFree(vi);
    XCloseDisplay(dpy);

    printf("e6_depth_precision: completed 5 frames\n");
    return 0;
}
