// SOURCE: https://github.com/mrdoob/three.js/issues/26762

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
typedef void   (*PFNGLUSEPROGRAMPROC)(GLuint);
typedef GLint  (*PFNGLGETUNIFORMLOCATIONPROC)(GLuint, const GLchar *);
typedef void   (*PFNGLUNIFORM4FPROC)(GLint, GLfloat, GLfloat, GLfloat, GLfloat);
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
    "void main() { gl_Position = vec4(aPos, 1.0); }\n";

static const char *frag_src =
    "#version 120\n"
    "uniform vec4 uColor;\n"
    "void main() { gl_FragColor = uColor; }\n";

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
    XStoreName(dpy, win, "R3: depthMask disabled causes z-fighting");

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
    LOAD_PROC(PFNGLUSEPROGRAMPROC,              glUseProgram)
    LOAD_PROC(PFNGLGETUNIFORMLOCATIONPROC,      glGetUniformLocation)
    LOAD_PROC(PFNGLUNIFORM4FPROC,               glUniform4f)
    LOAD_PROC(PFNGLGENBUFFERSPROC,              glGenBuffers)
    LOAD_PROC(PFNGLBINDBUFFERPROC,              glBindBuffer)
    LOAD_PROC(PFNGLBUFFERDATAPROC,              glBufferData)
    LOAD_PROC(PFNGLGENVERTEXARRAYSPROC,         glGenVertexArrays)
    LOAD_PROC(PFNGLBINDVERTEXARRAYPROC,         glBindVertexArray)
    LOAD_PROC(PFNGLENABLEVERTEXATTRIBARRAYPROC, glEnableVertexAttribArray)
    LOAD_PROC(PFNGLVERTEXATTRIBPOINTERPROC,     glVertexAttribPointer)
    LOAD_PROC(PFNGLGETATTRIBLOCATIONPROC,       glGetAttribLocation)
    LOAD_PROC(PFNGLDELETESHADERPROC,            glDeleteShader)
    LOAD_PROC(PFNGLDELETEPROGRAMPROC,           glDeleteProgram)
    LOAD_PROC(PFNGLDELETEBUFFERSPROC,           glDeleteBuffers)
    LOAD_PROC(PFNGLDELETEVERTEXARRAYSPROC,      glDeleteVertexArrays)

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
    glDeleteShader(vs);
    glDeleteShader(fs);

    GLint colorLoc = glGetUniformLocation(prog, "uColor");
    GLint posLoc   = glGetAttribLocation(prog,  "aPos");

    /* T1 FRONT (z=-0.4), T2 BEHIND (z=+0.4), overlap in central region. */
    static const GLfloat verts[] = {
        /* T1: front, covers left+center */
        -0.8f, -0.6f, -0.4f,
         0.2f, -0.6f, -0.4f,
        -0.3f,  0.7f, -0.4f,
        /* T2: behind, covers right+center (overlaps T1 in center) */
        -0.2f, -0.6f,  0.4f,
         0.8f, -0.6f,  0.4f,
         0.3f,  0.7f,  0.4f,
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

    for (int i = 0; i < 5; i++) {
        glClearColor(0.15f, 0.0f, 0.15f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        glUseProgram(prog);
        glBindVertexArray(vao);

        glDepthMask(GL_FALSE);

        /* Draw T1 (front, green) first. */
        glUniform4f(colorLoc, 0.0f, 0.9f, 0.0f, 1.0f);
        glDrawArrays(GL_TRIANGLES, 0, 3);

        /* Draw T2 (behind, red) second. */
        glUniform4f(colorLoc, 0.9f, 0.0f, 0.0f, 1.0f);
        glDrawArrays(GL_TRIANGLES, 3, 3);

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

    printf("r3_depthmask_disabled: completed 5 frames\n");
    return 0;
}