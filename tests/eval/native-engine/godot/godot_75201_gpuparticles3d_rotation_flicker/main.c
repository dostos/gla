// SOURCE: https://github.com/godotengine/godot/issues/75201
// Renders a single particle (rectangle) with a u_rotation uniform on its first frame.

#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

typedef GLuint (*PFNCREATESHADERPROC)(GLenum);
typedef void (*PFNSHADERSOURCEPROC)(GLuint, GLsizei, const char* const*, const GLint*);
typedef void (*PFNCOMPILESHADERPROC)(GLuint);
typedef GLuint (*PFNCREATEPROGRAMPROC)(void);
typedef void (*PFNATTACHSHADERPROC)(GLuint, GLuint);
typedef void (*PFNLINKPROGRAMPROC)(GLuint);
typedef void (*PFNUSEPROGRAMPROC)(GLuint);
typedef GLint (*PFNGETUNIFORMLOCATIONPROC)(GLuint, const char*);
typedef void (*PFNUNIFORM1FPROC)(GLint, GLfloat);
typedef void (*PFNGENBUFFERSPROC)(GLsizei, GLuint*);
typedef void (*PFNBINDBUFFERPROC)(GLenum, GLuint);
typedef void (*PFNBUFFERDATAPROC)(GLenum, ptrdiff_t, const void*, GLenum);
typedef void (*PFNGENVERTEXARRAYSPROC)(GLsizei, GLuint*);
typedef void (*PFNBINDVERTEXARRAYPROC)(GLuint);
typedef void (*PFNENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef void (*PFNVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);

#define GL_ARRAY_BUFFER 0x8892
#define GL_STATIC_DRAW 0x88E4
#define GL_VERTEX_SHADER 0x8B31
#define GL_FRAGMENT_SHADER 0x8B30

#define LOAD(name, T) T name = (T)glXGetProcAddressARB((const GLubyte*)#name)

static const char* VS =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "uniform float u_rotation;\n"
    "void main(){\n"
    "  float c = cos(u_rotation);\n"
    "  float s = sin(u_rotation);\n"
    "  vec2 p = vec2(c*aPos.x - s*aPos.y, s*aPos.x + c*aPos.y);\n"
    "  gl_Position = vec4(p, 0.0, 1.0);\n"
    "}\n";

static const char* FS =
    "#version 330 core\n"
    "out vec4 o;\n"
    "void main(){ o = vec4(1.0, 0.3, 0.2, 1.0); }\n";

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }

    int attribs[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attribs);
    if (!vi) { fprintf(stderr, "glXChooseVisual failed\n"); return 1; }

    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, RootWindow(dpy, vi->screen), vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, RootWindow(dpy, vi->screen), 0, 0, 512, 512, 0,
                               vi->depth, InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    LOAD(glCreateShader, PFNCREATESHADERPROC);
    LOAD(glShaderSource, PFNSHADERSOURCEPROC);
    LOAD(glCompileShader, PFNCOMPILESHADERPROC);
    LOAD(glCreateProgram, PFNCREATEPROGRAMPROC);
    LOAD(glAttachShader, PFNATTACHSHADERPROC);
    LOAD(glLinkProgram, PFNLINKPROGRAMPROC);
    LOAD(glUseProgram, PFNUSEPROGRAMPROC);
    LOAD(glGetUniformLocation, PFNGETUNIFORMLOCATIONPROC);
    LOAD(glUniform1f, PFNUNIFORM1FPROC);
    LOAD(glGenBuffers, PFNGENBUFFERSPROC);
    LOAD(glBindBuffer, PFNBINDBUFFERPROC);
    LOAD(glBufferData, PFNBUFFERDATAPROC);
    LOAD(glGenVertexArrays, PFNGENVERTEXARRAYSPROC);
    LOAD(glBindVertexArray, PFNBINDVERTEXARRAYPROC);
    LOAD(glEnableVertexAttribArray, PFNENABLEVERTEXATTRIBARRAYPROC);
    LOAD(glVertexAttribPointer, PFNVERTEXATTRIBPOINTERPROC);

    GLuint vs = glCreateShader(GL_VERTEX_SHADER);
    glShaderSource(vs, 1, &VS, NULL); glCompileShader(vs);
    GLuint fs = glCreateShader(GL_FRAGMENT_SHADER);
    glShaderSource(fs, 1, &FS, NULL); glCompileShader(fs);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs); glAttachShader(prog, fs);
    glLinkProgram(prog); glUseProgram(prog);

    float quad[] = {
        -0.4f, -0.1f,  0.4f, -0.1f,  0.4f, 0.1f,
        -0.4f, -0.1f,  0.4f,  0.1f, -0.4f, 0.1f,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao); glBindVertexArray(vao);
    glGenBuffers(1, &vbo); glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);

    GLint uRot = glGetUniformLocation(prog, "u_rotation");
    float first_frame_rotation = 0.0f;

    glClearColor(0.1f, 0.1f, 0.1f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glUniform1f(uRot, first_frame_rotation);
    glDrawArrays(GL_TRIANGLES, 0, 6);
    glXSwapBuffers(dpy, win);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}