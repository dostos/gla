// SOURCE: https://github.com/mrdoob/three.js/issues/30168
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <X11/Xlib.h>
#define GL_GLEXT_PROTOTYPES 1
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>

static const char *VS =
"#version 330 core\n"
"layout(location=0) in vec2 p;\n"
"layout(location=1) in vec2 offset;\n"
"void main(){ gl_Position = vec4(p + offset, 0.0, 1.0); }\n";

static const char *FS =
"#version 330 core\n"
"out vec4 o;\n"
"void main(){ o = vec4(0.9, 0.2, 0.2, 1.0); }\n";

typedef GLXContext (*glXCreateContextAttribsARBProc)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

static GLuint compile(GLenum t, const char *s) {
    GLuint sh = glCreateShader(t);
    glShaderSource(sh, 1, &s, NULL);
    glCompileShader(sh);
    GLint ok = 0; glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) { char log[2048]; glGetShaderInfoLog(sh, 2048, NULL, log); fprintf(stderr, "shader: %s\n", log); }
    return sh;
}

int main(void) {
    Display *d = XOpenDisplay(NULL);
    if (!d) { fprintf(stderr, "no display\n"); return 1; }

    static int visattr[] = {
        GLX_X_RENDERABLE, True, GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_RENDER_TYPE, GLX_RGBA_BIT, GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8,
        GLX_BLUE_SIZE, 8, GLX_DOUBLEBUFFER, True, None
    };
    int nfbc = 0;
    GLXFBConfig *fbcs = glXChooseFBConfig(d, DefaultScreen(d), visattr, &nfbc);
    GLXFBConfig fbc = fbcs[0];
    XVisualInfo *vi = glXGetVisualFromFBConfig(d, fbc);

    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(d, RootWindow(d, vi->screen), vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window w = XCreateWindow(d, RootWindow(d, vi->screen), 0, 0, 400, 300, 0,
        vi->depth, InputOutput, vi->visual, CWColormap | CWEventMask, &swa);
    XMapWindow(d, w);

    glXCreateContextAttribsARBProc gca = (glXCreateContextAttribsARBProc)
        glXGetProcAddressARB((const GLubyte*)"glXCreateContextAttribsARB");
    int ctx_attr[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3, GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB, None
    };
    GLXContext ctx = gca(d, fbc, NULL, True, ctx_attr);
    glXMakeCurrent(d, w, ctx);

    GLuint prog = glCreateProgram();
    glAttachShader(prog, compile(GL_VERTEX_SHADER, VS));
    glAttachShader(prog, compile(GL_FRAGMENT_SHADER, FS));
    glLinkProgram(prog);

    // per-vertex quad (two triangles)
    float quad[] = {
        -0.05f, -0.05f,
         0.05f, -0.05f,
         0.05f,  0.05f,
        -0.05f, -0.05f,
         0.05f,  0.05f,
        -0.05f,  0.05f,
    };
    GLuint vao, vboQuad;
    glGenVertexArrays(1, &vao); glBindVertexArray(vao);
    glGenBuffers(1, &vboQuad); glBindBuffer(GL_ARRAY_BUFFER, vboQuad);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL);
    glEnableVertexAttribArray(0);

    // initial per-instance offset buffer: 8 entries along the bottom row
    float offsetsInitial[] = {
        -0.7f, -0.7f, -0.5f, -0.7f, -0.3f, -0.7f, -0.1f, -0.7f,
         0.1f, -0.7f,  0.3f, -0.7f,  0.5f, -0.7f,  0.7f, -0.7f,
    };
    GLuint vboOffsetOld;
    glGenBuffers(1, &vboOffsetOld);
    glBindBuffer(GL_ARRAY_BUFFER, vboOffsetOld);
    glBufferData(GL_ARRAY_BUFFER, sizeof(offsetsInitial), offsetsInitial, GL_DYNAMIC_DRAW);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 0, NULL);
    glEnableVertexAttribArray(1);
    glVertexAttribDivisor(1, 1);

    // application swaps the offset attribute for a freshly allocated buffer
    // whose entries place the 8 instances along the top row
    float offsetsNew[] = {
        -0.7f,  0.7f, -0.5f,  0.7f, -0.3f,  0.7f, -0.1f,  0.7f,
         0.1f,  0.7f,  0.3f,  0.7f,  0.5f,  0.7f,  0.7f,  0.7f,
    };
    GLuint vboOffsetNew;
    glGenBuffers(1, &vboOffsetNew);
    glBindBuffer(GL_ARRAY_BUFFER, vboOffsetNew);
    glBufferData(GL_ARRAY_BUFFER, sizeof(offsetsNew), offsetsNew, GL_DYNAMIC_DRAW);

    int instanceCount = 8;

    glViewport(0, 0, 400, 300);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(prog);
    glBindVertexArray(vao);
    glDrawArraysInstanced(GL_TRIANGLES, 0, 6, instanceCount);

    glXSwapBuffers(d, w);

    unsigned char top[4], bot[4];
    glReadPixels(60, 255, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, top);
    glReadPixels(60,  45, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, bot);
    printf("top  sample (60,255) rgba = %d,%d,%d,%d\n", top[0], top[1], top[2], top[3]);
    printf("bot  sample (60, 45) rgba = %d,%d,%d,%d\n", bot[0], bot[1], bot[2], bot[3]);

    GLenum err = glGetError();
    printf("glGetError = 0x%x\n", err);
    return 0;
}