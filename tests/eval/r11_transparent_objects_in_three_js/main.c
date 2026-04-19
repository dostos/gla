// SOURCE: https://stackoverflow.com/questions/15994944/transparent-objects-in-three-js
#define GL_GLEXT_PROTOTYPES
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <GL/glext.h>
#include <stdio.h>
#include <stdlib.h>

static PFNGLCREATESHADERPROC        glCreateShader_;
static PFNGLSHADERSOURCEPROC        glShaderSource_;
static PFNGLCOMPILESHADERPROC       glCompileShader_;
static PFNGLCREATEPROGRAMPROC       glCreateProgram_;
static PFNGLATTACHSHADERPROC        glAttachShader_;
static PFNGLLINKPROGRAMPROC         glLinkProgram_;
static PFNGLUSEPROGRAMPROC          glUseProgram_;
static PFNGLGENVERTEXARRAYSPROC     glGenVertexArrays_;
static PFNGLBINDVERTEXARRAYPROC     glBindVertexArray_;
static PFNGLGENBUFFERSPROC          glGenBuffers_;
static PFNGLBINDBUFFERPROC          glBindBuffer_;
static PFNGLBUFFERDATAPROC          glBufferData_;
static PFNGLVERTEXATTRIBPOINTERPROC glVertexAttribPointer_;
static PFNGLENABLEVERTEXATTRIBARRAYPROC glEnableVertexAttribArray_;
static PFNGLGETUNIFORMLOCATIONPROC  glGetUniformLocation_;
static PFNGLUNIFORM4FPROC           glUniform4f_;

#define LOAD(NAME) NAME##_ = (typeof(NAME##_))glXGetProcAddressARB((const GLubyte*)#NAME)

static GLuint make_program(void) {
    const char *vs =
        "#version 330 core\n"
        "layout(location=0) in vec3 p;\n"
        "void main(){ gl_Position = vec4(p,1.0); }\n";
    const char *fs =
        "#version 330 core\n"
        "uniform vec4 u_color;\n"
        "out vec4 FragColor;\n"
        "void main(){ FragColor = u_color; }\n";
    GLuint v = glCreateShader_(GL_VERTEX_SHADER);
    glShaderSource_(v, 1, &vs, NULL); glCompileShader_(v);
    GLuint f = glCreateShader_(GL_FRAGMENT_SHADER);
    glShaderSource_(f, 1, &fs, NULL); glCompileShader_(f);
    GLuint p = glCreateProgram_();
    glAttachShader_(p, v); glAttachShader_(p, f); glLinkProgram_(p);
    return p;
}

static GLuint make_quad(const float *verts, size_t bytes) {
    GLuint vao, vbo;
    glGenVertexArrays_(1, &vao); glBindVertexArray_(vao);
    glGenBuffers_(1, &vbo); glBindBuffer_(GL_ARRAY_BUFFER, vbo);
    glBufferData_(GL_ARRAY_BUFFER, bytes, verts, GL_STATIC_DRAW);
    glVertexAttribPointer_(0, 3, GL_FLOAT, GL_FALSE, 0, 0);
    glEnableVertexAttribArray_(0);
    return vao;
}

int main(void) {
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int attribs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo *vi = glXChooseVisual(dpy, 0, attribs);
    if (!vi) { fprintf(stderr, "glXChooseVisual failed\n"); return 1; }
    Colormap cmap = XCreateColormap(dpy, RootWindow(dpy, vi->screen), vi->visual, AllocNone);
    XSetWindowAttributes swa; swa.colormap = cmap; swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, RootWindow(dpy, vi->screen), 0, 0, 400, 400,
                               0, vi->depth, InputOutput, vi->visual,
                               CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    LOAD(glCreateShader);  LOAD(glShaderSource);  LOAD(glCompileShader);
    LOAD(glCreateProgram); LOAD(glAttachShader);  LOAD(glLinkProgram);
    LOAD(glUseProgram);    LOAD(glGenVertexArrays); LOAD(glBindVertexArray);
    LOAD(glGenBuffers);    LOAD(glBindBuffer);    LOAD(glBufferData);
    LOAD(glVertexAttribPointer); LOAD(glEnableVertexAttribArray);
    LOAD(glGetUniformLocation);  LOAD(glUniform4f);

    GLuint prog = make_program();

    // Outer quad at z = 0.2.
    float outer[] = {
        -0.5f,-0.5f,0.2f,  0.5f,-0.5f,0.2f,  0.5f, 0.5f,0.2f,
        -0.5f,-0.5f,0.2f,  0.5f, 0.5f,0.2f, -0.5f, 0.5f,0.2f,
    };
    // Inner quad at z = 0.8.
    float inner[] = {
        -0.3f,-0.3f,0.8f,  0.3f,-0.3f,0.8f,  0.3f, 0.3f,0.8f,
        -0.3f,-0.3f,0.8f,  0.3f, 0.3f,0.8f, -0.3f, 0.3f,0.8f,
    };
    GLuint vaoOuter = make_quad(outer, sizeof(outer));
    GLuint vaoInner = make_quad(inner, sizeof(inner));

    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glClearColor(0.1f, 0.1f, 0.1f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    glUseProgram_(prog);
    GLint ul = glGetUniformLocation_(prog, "u_color");

    // Front first, then back.
    glUniform4f_(ul, 0.0f, 1.0f, 0.0f, 0.5f);   // green outer
    glBindVertexArray_(vaoOuter);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glUniform4f_(ul, 0.0f, 0.0f, 1.0f, 0.5f);   // blue inner
    glBindVertexArray_(vaoInner);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glFlush();
    glXSwapBuffers(dpy, win);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}