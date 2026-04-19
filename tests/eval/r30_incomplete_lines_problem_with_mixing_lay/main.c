// SOURCE: https://github.com/mapbox/mapbox-gl-js/issues/13206
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
        "layout(location=0) in vec2 p;\n"
        "void main(){ gl_Position = vec4(p,0.0,1.0); }\n";
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

static GLuint make_quad(float x0, float y0, float x1, float y1) {
    float v[] = { x0,y0, x1,y0, x1,y1,  x0,y0, x1,y1, x0,y1 };
    GLuint vao, vbo;
    glGenVertexArrays_(1, &vao); glBindVertexArray_(vao);
    glGenBuffers_(1, &vbo); glBindBuffer_(GL_ARRAY_BUFFER, vbo);
    glBufferData_(GL_ARRAY_BUFFER, sizeof(v), v, GL_STATIC_DRAW);
    glVertexAttribPointer_(0, 2, GL_FLOAT, GL_FALSE, 0, 0);
    glEnableVertexAttribArray_(0);
    return vao;
}

// Slot system: layers carry a slot tag (top/middle).
enum { SLOT_MIDDLE = 0, SLOT_TOP = 1 };
typedef struct { int slot; GLuint vao; float r,g,b; } Layer;

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

    // "top" line: thin horizontal blue strip spanning most of the view.
    GLuint vao_top_line = make_quad(-0.8f, -0.03f, 0.8f, 0.03f);
    // "middle" building shadow: dim gray square centered at origin.
    GLuint vao_mid_bldg = make_quad(-0.25f, -0.25f, 0.25f, 0.25f);

    glDisable(GL_DEPTH_TEST);                    // 2D map compositing
    glClearColor(1.0f, 1.0f, 1.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    glUseProgram_(prog);
    GLint ul = glGetUniformLocation_(prog, "u_color");

    // Registration order: top first, middle second. The scheduler
    // iterates the registry directly.
    Layer registry[] = {
        { SLOT_TOP,    vao_top_line, 0.10f, 0.20f, 1.00f },  // blue
        { SLOT_MIDDLE, vao_mid_bldg, 0.25f, 0.25f, 0.25f },  // gray
    };
    for (size_t i = 0; i < sizeof(registry)/sizeof(registry[0]); ++i) {
        glUniform4f_(ul, registry[i].r, registry[i].g, registry[i].b, 1.0f);
        glBindVertexArray_(registry[i].vao);
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }

    glFlush();
    glXSwapBuffers(dpy, win);

    // Probe the center pixel.
    unsigned char px[4] = {0};
    glReadPixels(200, 200, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    fprintf(stderr, "center pixel rgba: %u %u %u %u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}