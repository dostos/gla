// SOURCE: https://stackoverflow.com/questions/13888561/three-js-transparency-disparition
//
// R25: Translucent material rendered with GL_BLEND disabled.
//
// Pattern from three.js MeshNormalMaterial({opacity: 0.5}) without
// transparent:true. The material's uniform alpha is < 1.0, but the
// renderer never enables GL_BLEND for it, so depth-test culls the
// objects behind the "translucent" one instead of compositing them.
//
// Scene: a small opaque yellow quad behind a larger blue quad whose
// fragment alpha is 0.5. With GL_BLEND off and depth-test on, the blue
// quad writes opaque blue and occludes the yellow quad — exactly the
// "disparition" the SO question describes.

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
typedef void   (*PFNGLUSEPROGRAMPROC)(GLuint);
typedef GLint  (*PFNGLGETUNIFORMLOCATIONPROC)(GLuint, const GLchar *);
typedef void   (*PFNGLUNIFORM4FPROC)(GLint, GLfloat, GLfloat, GLfloat, GLfloat);
typedef void   (*PFNGLUNIFORM1FPROC)(GLint, GLfloat);
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
    "uniform float uZ;\n"
    "void main() { gl_Position = vec4(aPos, uZ, 1.0); }\n";

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
        fprintf(stderr, "Shader error: %s\n", log);
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
    if (!vi) return 1;

    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    memset(&swa, 0, sizeof(swa));
    swa.colormap   = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 400, 300, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    XStoreName(dpy, win, "R25: transparency disparition");

    GLXContext glc = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    if (!glc) return 1;
    glXMakeCurrent(dpy, win, glc);

    LOAD_PROC(PFNGLCREATESHADERPROC,            glCreateShader)
    LOAD_PROC(PFNGLSHADERSOURCEPROC,            glShaderSource)
    LOAD_PROC(PFNGLCOMPILESHADERPROC,           glCompileShader)
    LOAD_PROC(PFNGLGETSHADERIVPROC,             glGetShaderiv)
    LOAD_PROC(PFNGLGETSHADERINFOLOGPROC,        glGetShaderInfoLog)
    LOAD_PROC(PFNGLCREATEPROGRAMPROC,           glCreateProgram)
    LOAD_PROC(PFNGLATTACHSHADERPROC,            glAttachShader)
    LOAD_PROC(PFNGLLINKPROGRAMPROC,             glLinkProgram)
    LOAD_PROC(PFNGLUSEPROGRAMPROC,              glUseProgram)
    LOAD_PROC(PFNGLGETUNIFORMLOCATIONPROC,      glGetUniformLocation)
    LOAD_PROC(PFNGLUNIFORM4FPROC,               glUniform4f)
    LOAD_PROC(PFNGLUNIFORM1FPROC,               glUniform1f)
    LOAD_PROC(PFNGLGENBUFFERSPROC,              glGenBuffers)
    LOAD_PROC(PFNGLBINDBUFFERPROC,              glBindBuffer)
    LOAD_PROC(PFNGLBUFFERDATAPROC,              glBufferData)
    LOAD_PROC(PFNGLGENVERTEXARRAYSPROC,         glGenVertexArrays)
    LOAD_PROC(PFNGLBINDVERTEXARRAYPROC,         glBindVertexArray)
    LOAD_PROC(PFNGLENABLEVERTEXATTRIBARRAYPROC, glEnableVertexAttribArray)
    LOAD_PROC(PFNGLVERTEXATTRIBPOINTERPROC,     glVertexAttribPointer)
    LOAD_PROC(PFNGLGETATTRIBLOCATIONPROC,       glGetAttribLocation)

    glViewport(0, 0, 400, 300);

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

    GLint colorLoc = glGetUniformLocation(prog, "uColor");
    GLint zLoc     = glGetUniformLocation(prog, "uZ");
    GLint posLoc   = glGetAttribLocation(prog,  "aPos");

    static const GLfloat inner[] = {
        -0.3f, -0.3f,   0.3f, -0.3f,   0.3f, 0.3f,
        -0.3f, -0.3f,   0.3f,  0.3f,  -0.3f, 0.3f,
    };
    static const GLfloat outer[] = {
        -0.6f, -0.6f,   0.6f, -0.6f,   0.6f, 0.6f,
        -0.6f, -0.6f,   0.6f,  0.6f,  -0.6f, 0.6f,
    };

    GLuint vao_in, vbo_in, vao_out, vbo_out;
    glGenVertexArrays(1, &vao_in);
    glBindVertexArray(vao_in);
    glGenBuffers(1, &vbo_in);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_in);
    glBufferData(GL_ARRAY_BUFFER, sizeof(inner), inner, GL_STATIC_DRAW);
    glEnableVertexAttribArray((GLuint)posLoc);
    glVertexAttribPointer((GLuint)posLoc, 2, GL_FLOAT, GL_FALSE,
                          2 * sizeof(GLfloat), (void *)0);

    glGenVertexArrays(1, &vao_out);
    glBindVertexArray(vao_out);
    glGenBuffers(1, &vbo_out);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_out);
    glBufferData(GL_ARRAY_BUFFER, sizeof(outer), outer, GL_STATIC_DRAW);
    glEnableVertexAttribArray((GLuint)posLoc);
    glVertexAttribPointer((GLuint)posLoc, 2, GL_FLOAT, GL_FALSE,
                          2 * sizeof(GLfloat), (void *)0);

    glEnable(GL_DEPTH_TEST);
    // GL_BLEND is intentionally NOT enabled — this is the bug pattern.

    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    glUseProgram(prog);

    // Inner yellow quad, fully opaque, placed behind (larger depth).
    glBindVertexArray(vao_in);
    glUniform1f(zLoc, 0.5f);
    glUniform4f(colorLoc, 1.0f, 1.0f, 0.0f, 1.0f);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    // Outer blue quad, alpha=0.5 ("transparent" intent), placed in front.
    // GL_BLEND is OFF, so the alpha is discarded and blue writes opaquely,
    // occluding the yellow quad behind it.
    glBindVertexArray(vao_out);
    glUniform1f(zLoc, -0.5f);
    glUniform4f(colorLoc, 0.0f, 0.0f, 1.0f, 0.5f);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glXSwapBuffers(dpy, win);
    glFinish();

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, glc);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}