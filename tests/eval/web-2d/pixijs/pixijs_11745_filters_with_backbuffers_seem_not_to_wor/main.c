// SOURCE: https://github.com/pixijs/pixijs/issues/11745
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>

typedef char GLchar;
typedef ptrdiff_t GLsizeiptr;

static GLuint (*p_glCreateShader)(GLenum);
static void   (*p_glShaderSource)(GLuint, GLsizei, const GLchar* const*, const GLint*);
static void   (*p_glCompileShader)(GLuint);
static GLuint (*p_glCreateProgram)(void);
static void   (*p_glAttachShader)(GLuint, GLuint);
static void   (*p_glLinkProgram)(GLuint);
static void   (*p_glUseProgram)(GLuint);
static GLint  (*p_glGetUniformLocation)(GLuint, const GLchar*);
static void   (*p_glUniform1i)(GLint, GLint);
static void   (*p_glGenVertexArrays)(GLsizei, GLuint*);
static void   (*p_glBindVertexArray)(GLuint);
static void   (*p_glGenBuffers)(GLsizei, GLuint*);
static void   (*p_glBindBuffer)(GLenum, GLuint);
static void   (*p_glBufferData)(GLenum, GLsizeiptr, const void*, GLenum);
static void   (*p_glVertexAttribPointer)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
static void   (*p_glEnableVertexAttribArray)(GLuint);
static void   (*p_glActiveTexture)(GLenum);

#define GL_ARRAY_BUFFER    0x8892
#define GL_STATIC_DRAW     0x88E4
#define GL_VERTEX_SHADER   0x8B31
#define GL_FRAGMENT_SHADER 0x8B30
#define GL_TEXTURE0        0x84C0
#define GL_TEXTURE3        0x84C3

static void load_gl(void) {
    #define LD(n) p_##n = (void*)glXGetProcAddress((const GLubyte*)#n)
    LD(glCreateShader); LD(glShaderSource); LD(glCompileShader);
    LD(glCreateProgram); LD(glAttachShader); LD(glLinkProgram); LD(glUseProgram);
    LD(glGetUniformLocation); LD(glUniform1i);
    LD(glGenVertexArrays); LD(glBindVertexArray);
    LD(glGenBuffers); LD(glBindBuffer); LD(glBufferData);
    LD(glVertexAttribPointer); LD(glEnableVertexAttribArray);
    LD(glActiveTexture);
    #undef LD
}

static const char *vs_src =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "out vec2 vUV;\n"
    "void main() { vUV = aPos * 0.5 + 0.5; gl_Position = vec4(aPos, 0.0, 1.0); }\n";

static const char *fs_src =
    "#version 330 core\n"
    "in vec2 vUV;\n"
    "uniform sampler2D uTexture;\n"
    "uniform sampler2D uBackTexture;\n"
    "out vec4 fragColor;\n"
    "void main() { fragColor = texture(uBackTexture, vUV); }\n";

static GLuint make_solid_tex(unsigned char r, unsigned char g, unsigned char b) {
    GLuint t;
    glGenTextures(1, &t);
    glBindTexture(GL_TEXTURE_2D, t);
    unsigned char px[4] = { r, g, b, 255 };
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    return t;
}

int main(void) {
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    int att[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo *vi = glXChooseVisual(dpy, 0, att);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    Window win = XCreateWindow(dpy, root, 0, 0, 256, 256, 0, vi->depth,
                               InputOutput, vi->visual, CWColormap, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);
    load_gl();

    p_glActiveTexture(GL_TEXTURE0);
    GLuint texFront = make_solid_tex(255, 0, 0);
    p_glActiveTexture(GL_TEXTURE3);
    GLuint texBack  = make_solid_tex(0, 0, 255);
    (void)texFront; (void)texBack;

    GLuint vs = p_glCreateShader(GL_VERTEX_SHADER);
    p_glShaderSource(vs, 1, &vs_src, NULL);
    p_glCompileShader(vs);
    GLuint fs = p_glCreateShader(GL_FRAGMENT_SHADER);
    p_glShaderSource(fs, 1, &fs_src, NULL);
    p_glCompileShader(fs);
    GLuint prog = p_glCreateProgram();
    p_glAttachShader(prog, vs);
    p_glAttachShader(prog, fs);
    p_glLinkProgram(prog);
    p_glUseProgram(prog);

    GLuint vao, vbo;
    p_glGenVertexArrays(1, &vao);
    p_glBindVertexArray(vao);
    p_glGenBuffers(1, &vbo);
    p_glBindBuffer(GL_ARRAY_BUFFER, vbo);
    float verts[] = { -1,-1,  1,-1, -1,1,   1,-1,  1,1, -1,1 };
    p_glBufferData(GL_ARRAY_BUFFER, sizeof verts, verts, GL_STATIC_DRAW);
    p_glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);
    p_glEnableVertexAttribArray(0);

    GLint loc_uTex     = p_glGetUniformLocation(prog, "uTexture");
    GLint loc_uBackTex = p_glGetUniformLocation(prog, "uBackTexture");
    p_glUniform1i(loc_uTex, 0);
    p_glUniform1i(loc_uBackTex, 0);

    glViewport(0, 0, 256, 256);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glXSwapBuffers(dpy, win);
    return 0;
}