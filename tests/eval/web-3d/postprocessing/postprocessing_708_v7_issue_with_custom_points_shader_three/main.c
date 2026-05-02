// SOURCE: https://github.com/pmndrs/postprocessing/issues/708
#define GL_GLEXT_PROTOTYPES 1
#include <GL/gl.h>
#include <GL/glx.h>
#include <GL/glext.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>

static Display *dpy;
static Window win;
static GLXContext ctx;

static void init_gl(void) {
    dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); exit(1); }
    int attrs[] = {
        GLX_RGBA, GLX_DOUBLEBUFFER,
        GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8,
        GLX_DEPTH_SIZE, 24, None
    };
    XVisualInfo *vi = glXChooseVisual(dpy, DefaultScreen(dpy), attrs);
    if (!vi) { fprintf(stderr, "no visual\n"); exit(1); }
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, RootWindow(dpy, vi->screen),
                                   vi->visual, AllocNone);
    win = XCreateWindow(dpy, RootWindow(dpy, vi->screen), 0, 0, 256, 256, 0,
                        vi->depth, InputOutput, vi->visual, CWColormap, &swa);
    XMapWindow(dpy, win);
    ctx = glXCreateContext(dpy, vi, NULL, True);
    glXMakeCurrent(dpy, win, ctx);
}

static GLuint compile_shader(GLenum type, const char *src) {
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok; glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024]; glGetShaderInfoLog(s, sizeof log, NULL, log);
        fprintf(stderr, "shader: %s\n", log); exit(1);
    }
    return s;
}

static GLuint link_program(const char *vsrc, const char *fsrc) {
    GLuint vs = compile_shader(GL_VERTEX_SHADER, vsrc);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, fsrc);
    GLuint p = glCreateProgram();
    glAttachShader(p, vs); glAttachShader(p, fs); glLinkProgram(p);
    GLint ok; glGetProgramiv(p, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[1024]; glGetProgramInfoLog(p, sizeof log, NULL, log);
        fprintf(stderr, "link: %s\n", log); exit(1);
    }
    glDeleteShader(vs); glDeleteShader(fs);
    return p;
}

static const char *VS =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "out vec3 vWorldNormal;\n"
    "void main(){\n"
    "  vWorldNormal = vec3(0.0,0.0,1.0);\n"
    "  gl_Position = vec4(aPos,0.0,1.0);\n"
    "}\n";

// Mirrors PointsMaterial in pmndrs/postprocessing v7.0.0-beta.11:
// the FBO is bound with two draw buffers (color + gBufferNormal),
// but this fragment shader declares only the color output.
// Attachment 1 receives undefined values wherever the primitive rasterizes.
static const char *FS =
    "#version 330 core\n"
    "in vec3 vWorldNormal;\n"
    "layout(location=0) out vec4 out_Color;\n"
    "void main(){\n"
    "  out_Color = vec4(1.0, 0.5, 0.2, 1.0);\n"
    "}\n";

int main(void) {
    init_gl();

    GLuint fbo, tex_color, tex_normal;
    glGenFramebuffers(1, &fbo);
    glGenTextures(1, &tex_color);
    glGenTextures(1, &tex_normal);

    glBindTexture(GL_TEXTURE_2D, tex_color);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 256, 256, 0,
                 GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);

    glBindTexture(GL_TEXTURE_2D, tex_normal);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 256, 256, 0,
                 GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);

    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_2D, tex_color, 0);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT1,
                           GL_TEXTURE_2D, tex_normal, 0);
    GLenum bufs[2] = { GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1 };
    glDrawBuffers(2, bufs);

    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
        fprintf(stderr, "FBO incomplete\n"); return 1;
    }

    // Clear attachment 1 to the encoded "up" normal (0.5, 0.5, 1.0).
    // A correct shader should overwrite these pixels with the same value;
    // the buggy shader leaves them undefined inside the triangle footprint.
    float c0[4] = {0.0f, 0.0f, 0.0f, 1.0f};
    float c1[4] = {0.5f, 0.5f, 1.0f, 1.0f};
    glClearBufferfv(GL_COLOR, 0, c0);
    glClearBufferfv(GL_COLOR, 1, c1);

    glViewport(0, 0, 256, 256);

    float verts[] = {
        -0.7f, -0.7f,
         0.7f, -0.7f,
         0.0f,  0.7f,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glGenBuffers(1, &vbo);
    glBindVertexArray(vao);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof verts, verts, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);
    glEnableVertexAttribArray(0);

    GLuint prog = link_program(VS, FS);
    glUseProgram(prog);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    // Blit attachment 1 (normal buffer) to the default framebuffer so the
    // swapped frame visibly reflects the undefined-output corruption.
    glBindFramebuffer(GL_READ_FRAMEBUFFER, fbo);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
    glReadBuffer(GL_COLOR_ATTACHMENT1);
    glDrawBuffer(GL_BACK);
    glBlitFramebuffer(0, 0, 256, 256, 0, 0, 256, 256,
                      GL_COLOR_BUFFER_BIT, GL_NEAREST);

    glXSwapBuffers(dpy, win);
    return 0;
}