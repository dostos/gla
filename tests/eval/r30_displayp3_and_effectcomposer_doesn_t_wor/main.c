// SOURCE: https://github.com/mrdoob/three.js/issues/33030
//
// Two rendering paths write the same "red" fragment.
//   Left  (direct path):   scene -> default framebuffer, GL_FRAMEBUFFER_SRGB
//                          enabled (linear->sRGB conversion on write).
//   Right (composed path): scene -> intermediate RGBA8 FBO,
//                          then blit to default framebuffer.
#define GL_GLEXT_PROTOTYPES 1
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char* VS =
    "#version 330 core\n"
    "layout(location=0) in vec2 p;\n"
    "void main(){ gl_Position = vec4(p,0,1); }\n";

static const char* FS =
    "#version 330 core\n"
    "out vec4 c;\n"
    "void main(){ c = vec4(0.5, 0.0, 0.0, 1.0); }\n";

static const char* VS_BLIT =
    "#version 330 core\n"
    "layout(location=0) in vec2 p;\n"
    "out vec2 uv;\n"
    "void main(){ uv = p*0.5+0.5; gl_Position = vec4(p,0,1); }\n";

static const char* FS_BLIT =
    "#version 330 core\n"
    "in vec2 uv;\n"
    "uniform sampler2D tex;\n"
    "out vec4 c;\n"
    "void main(){ c = texture(tex, uv); }\n";

static GLuint make_prog(const char* vs, const char* fs) {
    GLuint v = glCreateShader(GL_VERTEX_SHADER);
    glShaderSource(v, 1, &vs, NULL); glCompileShader(v);
    GLuint f = glCreateShader(GL_FRAGMENT_SHADER);
    glShaderSource(f, 1, &fs, NULL); glCompileShader(f);
    GLuint p = glCreateProgram();
    glAttachShader(p, v); glAttachShader(p, f); glLinkProgram(p);
    glDeleteShader(v); glDeleteShader(f);
    return p;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    int attr[] = {
        GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER,
        GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8, None
    };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, attr);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 800, 600, 0, vi->depth,
        InputOutput, vi->visual, CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    GLuint prog = make_prog(VS, FS);
    GLuint blit = make_prog(VS_BLIT, FS_BLIT);

    // Fullscreen-quad VAO
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    float quad[] = { -1,-1, 1,-1, -1,1, 1,1 };
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL);
    glEnableVertexAttribArray(0);

    // Intermediate FBO for the "composed" path: RGBA8.
    GLuint fbo, tex;
    glGenFramebuffers(1, &fbo);
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 400, 600, 0,
                 GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_2D, tex, 0);

    // --- LEFT HALF: direct path ---
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, 400, 600);
    glEnable(GL_SCISSOR_TEST);
    glScissor(0, 0, 400, 600);
    glEnable(GL_FRAMEBUFFER_SRGB);
    glUseProgram(prog);
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

    // --- RIGHT HALF: composed path ---
    glDisable(GL_FRAMEBUFFER_SRGB);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glViewport(0, 0, 400, 600);
    glDisable(GL_SCISSOR_TEST);
    glUseProgram(prog);
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

    // Blit FBO to right half of default framebuffer.
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(400, 0, 400, 600);
    glEnable(GL_SCISSOR_TEST);
    glScissor(400, 0, 400, 600);
    glUseProgram(blit);
    glBindTexture(GL_TEXTURE_2D, tex);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

    glXSwapBuffers(dpy, win);
    glFinish();
    return 0;
}