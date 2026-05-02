// SOURCE: synthetic (no upstream)
// Two textured quads rendered side by side (red left, blue right).
//
// Minimal OpenGL 2.1 / 3.3 compatible program. Uses GLX for context.
// Link: -lGL -lX11 -lm only. Compiles with:
//   gcc -Wall -std=gnu11 main.c -lGL -lX11 -lm
// Runs under Xvfb; exits cleanly after rendering 3-5 frames.
// The bug manifests on the first rendered frame.
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define GL_VERTEX_SHADER    0x8B31
#define GL_FRAGMENT_SHADER  0x8B30
#define GL_COMPILE_STATUS   0x8B81
#define GL_LINK_STATUS      0x8B82
#define GL_ARRAY_BUFFER     0x8892
#define GL_STATIC_DRAW      0x88E4

typedef GLuint (*fn_CreateShader)(GLenum);
typedef void   (*fn_ShaderSource)(GLuint, GLsizei, const char* const*, const GLint*);
typedef void   (*fn_CompileShader)(GLuint);
typedef void   (*fn_GetShaderiv)(GLuint, GLenum, GLint*);
typedef void   (*fn_GetShaderInfoLog)(GLuint, GLsizei, GLsizei*, char*);
typedef GLuint (*fn_CreateProgram)(void);
typedef void   (*fn_AttachShader)(GLuint, GLuint);
typedef void   (*fn_LinkProgram)(GLuint);
typedef void   (*fn_UseProgram)(GLuint);
typedef GLint  (*fn_GetAttribLocation)(GLuint, const char*);
typedef GLint  (*fn_GetUniformLocation)(GLuint, const char*);
typedef void   (*fn_Uniform1i)(GLint, GLint);
typedef void   (*fn_GenBuffers)(GLsizei, GLuint*);
typedef void   (*fn_BindBuffer)(GLenum, GLuint);
typedef void   (*fn_BufferData)(GLenum, GLsizeiptr, const void*, GLenum);
typedef void   (*fn_EnableVertexAttribArray)(GLuint);
typedef void   (*fn_VertexAttribPointer)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);

static fn_CreateShader            p_glCreateShader;
static fn_ShaderSource            p_glShaderSource;
static fn_CompileShader           p_glCompileShader;
static fn_GetShaderiv             p_glGetShaderiv;
static fn_GetShaderInfoLog        p_glGetShaderInfoLog;
static fn_CreateProgram           p_glCreateProgram;
static fn_AttachShader            p_glAttachShader;
static fn_LinkProgram             p_glLinkProgram;
static fn_UseProgram              p_glUseProgram;
static fn_GetAttribLocation       p_glGetAttribLocation;
static fn_GetUniformLocation      p_glGetUniformLocation;
static fn_Uniform1i               p_glUniform1i;
static fn_GenBuffers              p_glGenBuffers;
static fn_BindBuffer              p_glBindBuffer;
static fn_BufferData              p_glBufferData;
static fn_EnableVertexAttribArray p_glEnableVertexAttribArray;
static fn_VertexAttribPointer     p_glVertexAttribPointer;

#define LOAD(T, name) p_##name = (T)glXGetProcAddress((const GLubyte*)#name)

static void load_gl(void) {
    LOAD(fn_CreateShader,            glCreateShader);
    LOAD(fn_ShaderSource,            glShaderSource);
    LOAD(fn_CompileShader,           glCompileShader);
    LOAD(fn_GetShaderiv,             glGetShaderiv);
    LOAD(fn_GetShaderInfoLog,        glGetShaderInfoLog);
    LOAD(fn_CreateProgram,           glCreateProgram);
    LOAD(fn_AttachShader,            glAttachShader);
    LOAD(fn_LinkProgram,             glLinkProgram);
    LOAD(fn_UseProgram,              glUseProgram);
    LOAD(fn_GetAttribLocation,       glGetAttribLocation);
    LOAD(fn_GetUniformLocation,      glGetUniformLocation);
    LOAD(fn_Uniform1i,               glUniform1i);
    LOAD(fn_GenBuffers,              glGenBuffers);
    LOAD(fn_BindBuffer,              glBindBuffer);
    LOAD(fn_BufferData,              glBufferData);
    LOAD(fn_EnableVertexAttribArray, glEnableVertexAttribArray);
    LOAD(fn_VertexAttribPointer,     glVertexAttribPointer);
}

static GLuint compile_shader(GLenum type, const char* src) {
    GLuint s = p_glCreateShader(type);
    p_glShaderSource(s, 1, &src, NULL);
    p_glCompileShader(s);
    GLint ok = 0;
    p_glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        p_glGetShaderInfoLog(s, sizeof(log), NULL, log);
        fprintf(stderr, "shader compile failed: %s\n", log);
        exit(2);
    }
    return s;
}

static GLuint make_solid_texture(unsigned char r, unsigned char g, unsigned char b) {
    GLuint tex;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    unsigned char px[4] = { r, g, b, 255 };
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    return tex;
}

static GLuint make_quad_vbo(float x0, float y0, float x1, float y1) {
    float v[] = {
        x0, y0, 0.0f, 0.0f,
        x1, y0, 1.0f, 0.0f,
        x1, y1, 1.0f, 1.0f,
        x0, y1, 0.0f, 1.0f,
    };
    GLuint vbo;
    p_glGenBuffers(1, &vbo);
    p_glBindBuffer(GL_ARRAY_BUFFER, vbo);
    p_glBufferData(GL_ARRAY_BUFFER, sizeof(v), v, GL_STATIC_DRAW);
    return vbo;
}

static const char* VS_SRC =
    "#version 120\n"
    "attribute vec2 aPos;\n"
    "attribute vec2 aUV;\n"
    "varying vec2 vUV;\n"
    "void main() {\n"
    "    vUV = aUV;\n"
    "    gl_Position = vec4(aPos, 0.0, 1.0);\n"
    "}\n";

static const char* FS_SRC =
    "#version 120\n"
    "varying vec2 vUV;\n"
    "uniform sampler2D uTex;\n"
    "void main() {\n"
    "    gl_FragColor = texture2D(uTex, vUV);\n"
    "}\n";

static void bind_quad_attribs(GLint posLoc, GLint uvLoc, GLuint vbo) {
    p_glBindBuffer(GL_ARRAY_BUFFER, vbo);
    p_glEnableVertexAttribArray(posLoc);
    p_glVertexAttribPointer(posLoc, 2, GL_FLOAT, GL_FALSE,
                            4 * sizeof(float), (void*)0);
    p_glEnableVertexAttribArray(uvLoc);
    p_glVertexAttribPointer(uvLoc, 2, GL_FLOAT, GL_FALSE,
                            4 * sizeof(float), (void*)(2 * sizeof(float)));
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "cannot open display\n"); return 1; }

    int attrs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, attrs);
    if (!vi) { fprintf(stderr, "no visual\n"); return 1; }

    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    memset(&swa, 0, sizeof(swa));
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 400, 300, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    if (!ctx) { fprintf(stderr, "no context\n"); return 1; }
    glXMakeCurrent(dpy, win, ctx);

    load_gl();

    GLuint texRed  = make_solid_texture(230,  40,  40);
    GLuint texBlue = make_solid_texture( 40,  60, 230);

    GLuint vs = compile_shader(GL_VERTEX_SHADER, VS_SRC);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, FS_SRC);
    GLuint prog = p_glCreateProgram();
    p_glAttachShader(prog, vs);
    p_glAttachShader(prog, fs);
    p_glLinkProgram(prog);
    p_glUseProgram(prog);

    GLint posLoc = p_glGetAttribLocation(prog, "aPos");
    GLint uvLoc  = p_glGetAttribLocation(prog, "aUV");
    GLint texLoc = p_glGetUniformLocation(prog, "uTex");
    p_glUniform1i(texLoc, 0);

    GLuint vboLeft  = make_quad_vbo(-0.85f, -0.5f, -0.15f, 0.5f);
    GLuint vboRight = make_quad_vbo(-0.10f, -0.5f,  0.85f, 0.5f);

    (void)texBlue;

    for (int frame = 0; frame < 3; ++frame) {
        glViewport(0, 0, 400, 300);
        glClearColor(0.08f, 0.08f, 0.10f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);

        glBindTexture(GL_TEXTURE_2D, texRed);
        bind_quad_attribs(posLoc, uvLoc, vboLeft);
        glDrawArrays(GL_TRIANGLE_FAN, 0, 4);

        bind_quad_attribs(posLoc, uvLoc, vboRight);
        glDrawArrays(GL_TRIANGLE_FAN, 0, 4);

        glXSwapBuffers(dpy, win);
    }

    unsigned char px[4] = {0};
    glReadPixels(200, 150, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center RGBA: %u %u %u %u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XFree(vi);
    XCloseDisplay(dpy);
    return 0;
}