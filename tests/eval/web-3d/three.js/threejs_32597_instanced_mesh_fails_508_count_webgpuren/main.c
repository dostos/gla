// SOURCE: https://github.com/mrdoob/three.js/issues/32597
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <X11/Xlib.h>
#define GL_GLEXT_PROTOTYPES 1
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>

#define COUNT 2048

static const char *VS =
"#version 330 core\n"
"layout(location=0) in vec2 p;\n"
"layout(std140) uniform Instances { mat4 M[2048]; };\n"
"void main(){ gl_Position = M[gl_InstanceID] * vec4(p, 0.0, 1.0); }\n";

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
    if (!ok) { char log[2048]; glGetShaderInfoLog(sh, 2048, NULL, log); fprintf(stderr, "shader compile: %s\n", log); }
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
    Window w = XCreateWindow(d, RootWindow(d, vi->screen), 0, 0, 256, 256, 0,
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

    GLint maxUbo = 0;
    glGetIntegerv(GL_MAX_UNIFORM_BLOCK_SIZE, &maxUbo);
    printf("MAX_UNIFORM_BLOCK_SIZE = %d bytes\n", maxUbo);
    printf("requested UBO size    = %zu bytes\n", (size_t)(sizeof(float) * 16 * COUNT));

    GLuint prog = glCreateProgram();
    GLuint vs = compile(GL_VERTEX_SHADER, VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    glAttachShader(prog, vs); glAttachShader(prog, fs);
    glLinkProgram(prog);
    GLint linked = 0; glGetProgramiv(prog, GL_LINK_STATUS, &linked);
    if (!linked) { char log[2048]; glGetProgramInfoLog(prog, 2048, NULL, log); fprintf(stderr, "link: %s\n", log); }

    size_t bytes = sizeof(float) * 16 * COUNT;
    float *data = (float*)calloc(1, bytes);
    for (int i = 0; i < COUNT; i++) {
        float *m = data + i * 16;
        float sx = 0.04f, sy = 0.04f;
        float tx = ((i % 64) / 63.0f) * 1.9f - 0.95f;
        float ty = ((i / 64) / 31.0f) * 1.9f - 0.95f;
        m[0] = sx; m[5] = sy; m[10] = 1.0f; m[15] = 1.0f;
        m[12] = tx; m[13] = ty;
    }

    GLuint ubo;
    glGenBuffers(1, &ubo);
    glBindBuffer(GL_UNIFORM_BUFFER, ubo);
    glBufferData(GL_UNIFORM_BUFFER, bytes, data, GL_STATIC_DRAW);
    GLuint idx = glGetUniformBlockIndex(prog, "Instances");
    glUniformBlockBinding(prog, idx, 0);
    glBindBufferBase(GL_UNIFORM_BUFFER, 0, ubo);
    free(data);

    float verts[] = { 0.0f, 1.0f, -1.0f, -1.0f, 1.0f, -1.0f };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao); glBindVertexArray(vao);
    glGenBuffers(1, &vbo); glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL);
    glEnableVertexAttribArray(0);

    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(prog);
    glDrawArraysInstanced(GL_TRIANGLES, 0, 3, COUNT);

    glXSwapBuffers(d, w);

    unsigned char px[4];
    glReadPixels(128, 128, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center pixel rgba = %d,%d,%d,%d\n", px[0], px[1], px[2], px[3]);

    GLenum err = glGetError();
    printf("glGetError = 0x%x\n", err);
    return 0;
}