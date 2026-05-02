// tests/eval/e10_compensating_vp.c
//
// E10: Compensating View/Projection Bugs
//
// Draws two quads using a view matrix and perspective projection.
//
// Clear color: dark yellow (0.15, 0.12, 0.0)

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

static const char *vert_src =
    "#version 120\n"
    "attribute vec3 aPos;\n"
    "uniform mat4 uView;\n"
    "uniform mat4 uProj;\n"
    "void main() {\n"
    "    gl_Position = uProj * uView * vec4(aPos, 1.0);\n"
    "}\n";

static const char *frag_src =
    "#version 120\n"
    "uniform vec4 uColor;\n"
    "void main() { gl_FragColor = uColor; }\n";

/* Helper math */
static void norm3(float *v)
{
    float len = sqrtf(v[0]*v[0] + v[1]*v[1] + v[2]*v[2]);
    if (len > 1e-6f) { v[0] /= len; v[1] /= len; v[2] /= len; }
}
static float dot3(const float *a, const float *b)
{
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
}
static void cross3(float *out, const float *a, const float *b)
{
    out[0] = a[1]*b[2] - a[2]*b[1];
    out[1] = a[2]*b[0] - a[0]*b[2];
    out[2] = a[0]*b[1] - a[1]*b[0];
}

/* Column-major lookat matrix. */
static void buggy_lookat(float *m,
                         float ex, float ey, float ez,
                         float cx, float cy, float cz,
                         float ux, float uy, float uz)
{
    float fwd[3] = { ex - cx, ey - cy, ez - cz };
    norm3(fwd);
    float up[3] = { ux, uy, uz };
    float right[3];
    cross3(right, fwd, up);
    norm3(right);
    float newUp[3];
    cross3(newUp, right, fwd);

    memset(m, 0, 16 * sizeof(float));
    m[0]  =  right[0]; m[4]  =  right[1]; m[8]   =  right[2];
    m[12] = -dot3(right, (float[]){ex, ey, ez});
    m[1]  =  newUp[0]; m[5]  =  newUp[1]; m[9]   =  newUp[2];
    m[13] = -dot3(newUp, (float[]){ex, ey, ez});
    m[2]  =  fwd[0];   m[6]  =  fwd[1];   m[10]  =  fwd[2];
    m[14] = -dot3(fwd,  (float[]){ex, ey, ez});
    m[15] = 1.0f;
}

/* Column-major perspective matrix. */
static void buggy_perspective(float *m, float fovy_deg, float aspect,
                               float near_z, float far_z)
{
    float f  = 1.0f / tanf(fovy_deg * 3.14159265f / 360.0f);
    float nf = 1.0f / (near_z - far_z);
    memset(m, 0, 16 * sizeof(float));
    m[0]  =  f / aspect;
    m[5]  =  f;
    m[10] = -(far_z + near_z) * nf;
    m[11] = -1.0f;
    m[14] = -(2.0f * far_z * near_z * nf);
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
    XStoreName(dpy, win, "E10: Compensating V/P Bugs");

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

    GLint viewLoc  = glGetUniformLocation(prog, "uView");
    GLint projLoc  = glGetUniformLocation(prog, "uProj");
    GLint colorLoc = glGetUniformLocation(prog, "uColor");
    GLint posLoc   = glGetAttribLocation(prog,  "aPos");

    /* Two quads (each as 2 triangles):
     *   Quad A — centred at X=0, Z=-3.
     *   Quad B — centred at X=+0.8, Z=-3.
     */
    static const GLfloat verts[] = {
        /* Quad A: centred (green) at world (0, 0, -3) */
        -0.25f, -0.25f, -3.0f,
         0.25f, -0.25f, -3.0f,
         0.25f,  0.25f, -3.0f,
        -0.25f, -0.25f, -3.0f,
         0.25f,  0.25f, -3.0f,
        -0.25f,  0.25f, -3.0f,
        /* Quad B: off-centre (orange) at world (0.8, 0, -3) — will appear mirrored */
         0.55f, -0.25f, -3.0f,
         1.05f, -0.25f, -3.0f,
         1.05f,  0.25f, -3.0f,
         0.55f, -0.25f, -3.0f,
         1.05f,  0.25f, -3.0f,
         0.55f,  0.25f, -3.0f,
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

    /* View: camera at (0,0,3) looking at origin. */
    float view[16];
    buggy_lookat(view,
                 0.0f, 0.0f, 3.0f,  /* eye */
                 0.0f, 0.0f, 0.0f,  /* center */
                 0.0f, 1.0f, 0.0f); /* up */

    float proj[16];
    buggy_perspective(proj, 60.0f, 400.0f / 300.0f, 0.1f, 100.0f);

    for (int i = 0; i < 5; i++) {
        /* Clear to dark yellow */
        glClearColor(0.15f, 0.12f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        glUseProgram(prog);
        glUniformMatrix4fv(viewLoc, 1, GL_FALSE, view);
        glUniformMatrix4fv(projLoc, 1, GL_FALSE, proj);
        glBindVertexArray(vao);

        /* Quad A: green, centred */
        glUniform4f(colorLoc, 0.2f, 0.9f, 0.2f, 1.0f);
        glDrawArrays(GL_TRIANGLES, 0, 6);

        /* Quad B: orange, off-centre right */
        glUniform4f(colorLoc, 1.0f, 0.5f, 0.0f, 1.0f);
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

    printf("e10_compensating_vp: completed 5 frames\n");
    return 0;
}
