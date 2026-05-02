// SOURCE: synthetic (no upstream)
// Terrain renders black because a sampler2D uniform points at unit 0 where
// a stale GL_TEXTURE_3D volume (leaked from a fog module) is still bound;
// the 2D terrain texture sits on unit 1 but the shader reads unit 0.
//
// Minimal OpenGL 2.1 / GLSL 120 program. GLX context, Xlib window.
// Link: -lGL -lX11 -lm. Compiles with:
//   gcc -Wall -std=gnu11 main.c -lGL -lX11 -lm
// Runs under Xvfb; exits cleanly after rendering 3 frames.
// The bug manifests on every rendered frame.
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>

typedef char GLcharX;
typedef ptrdiff_t GLsizeiptrX;

typedef GLuint (*PFN_CreateShader)(GLenum);
typedef void   (*PFN_ShaderSource)(GLuint, GLsizei, const GLcharX* const*, const GLint*);
typedef void   (*PFN_CompileShader)(GLuint);
typedef void   (*PFN_GetShaderiv)(GLuint, GLenum, GLint*);
typedef void   (*PFN_GetShaderInfoLog)(GLuint, GLsizei, GLsizei*, GLcharX*);
typedef GLuint (*PFN_CreateProgram)(void);
typedef void   (*PFN_AttachShader)(GLuint, GLuint);
typedef void   (*PFN_LinkProgram)(GLuint);
typedef void   (*PFN_UseProgram)(GLuint);
typedef void   (*PFN_GenBuffers)(GLsizei, GLuint*);
typedef void   (*PFN_BindBuffer)(GLenum, GLuint);
typedef void   (*PFN_BufferData)(GLenum, GLsizeiptrX, const void*, GLenum);
typedef void   (*PFN_VertexAttribPointer)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void   (*PFN_EnableVertexAttribArray)(GLuint);
typedef GLint  (*PFN_GetUniformLocation)(GLuint, const GLcharX*);
typedef void   (*PFN_Uniform1i)(GLint, GLint);
typedef void   (*PFN_ActiveTexture)(GLenum);
typedef void   (*PFN_TexImage3D)(GLenum, GLint, GLint, GLsizei, GLsizei, GLsizei, GLint, GLenum, GLenum, const void*);
typedef void   (*PFN_BindAttribLocation)(GLuint, GLuint, const GLcharX*);

#define GL_TEXTURE_3D      0x806F
#define GL_TEXTURE0        0x84C0
#define GL_TEXTURE1        0x84C1
#define GL_ARRAY_BUFFER    0x8892
#define GL_STATIC_DRAW     0x88E4
#define GL_VERTEX_SHADER   0x8B31
#define GL_FRAGMENT_SHADER 0x8B30
#define GL_COMPILE_STATUS  0x8B81

static PFN_CreateShader           pglCreateShader;
static PFN_ShaderSource           pglShaderSource;
static PFN_CompileShader          pglCompileShader;
static PFN_GetShaderiv            pglGetShaderiv;
static PFN_GetShaderInfoLog       pglGetShaderInfoLog;
static PFN_CreateProgram          pglCreateProgram;
static PFN_AttachShader           pglAttachShader;
static PFN_LinkProgram            pglLinkProgram;
static PFN_UseProgram             pglUseProgram;
static PFN_GenBuffers             pglGenBuffers;
static PFN_BindBuffer             pglBindBuffer;
static PFN_BufferData             pglBufferData;
static PFN_VertexAttribPointer    pglVertexAttribPointer;
static PFN_EnableVertexAttribArray pglEnableVertexAttribArray;
static PFN_GetUniformLocation     pglGetUniformLocation;
static PFN_Uniform1i              pglUniform1i;
static PFN_ActiveTexture          pglActiveTexture;
static PFN_TexImage3D             pglTexImage3D;
static PFN_BindAttribLocation     pglBindAttribLocation;

#define LOAD(v, n) v = (void*)glXGetProcAddress((const GLubyte*)n)

static const char* VS =
    "#version 120\n"
    "attribute vec2 aPos;\n"
    "attribute vec2 aUV;\n"
    "varying vec2 vUV;\n"
    "void main(){ vUV = aUV; gl_Position = vec4(aPos, 0.0, 1.0); }\n";

static const char* FS =
    "#version 120\n"
    "uniform sampler2D terrain_tex;\n"
    "varying vec2 vUV;\n"
    "void main(){ gl_FragColor = texture2D(terrain_tex, vUV); }\n";

static GLuint compile_shader(GLenum type, const char* src) {
    GLuint s = pglCreateShader(type);
    pglShaderSource(s, 1, &src, NULL);
    pglCompileShader(s);
    GLint ok = 0;
    pglGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024] = {0};
        pglGetShaderInfoLog(s, sizeof(log), NULL, log);
        fprintf(stderr, "shader compile: %s\n", log);
        exit(1);
    }
    return s;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int attribs[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attribs);
    if (!vi) { fprintf(stderr, "glXChooseVisual failed\n"); return 1; }
    Window root = RootWindow(dpy, vi->screen);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 400, 300, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    LOAD(pglCreateShader,           "glCreateShader");
    LOAD(pglShaderSource,           "glShaderSource");
    LOAD(pglCompileShader,          "glCompileShader");
    LOAD(pglGetShaderiv,            "glGetShaderiv");
    LOAD(pglGetShaderInfoLog,       "glGetShaderInfoLog");
    LOAD(pglCreateProgram,          "glCreateProgram");
    LOAD(pglAttachShader,           "glAttachShader");
    LOAD(pglLinkProgram,            "glLinkProgram");
    LOAD(pglUseProgram,             "glUseProgram");
    LOAD(pglGenBuffers,             "glGenBuffers");
    LOAD(pglBindBuffer,             "glBindBuffer");
    LOAD(pglBufferData,             "glBufferData");
    LOAD(pglVertexAttribPointer,    "glVertexAttribPointer");
    LOAD(pglEnableVertexAttribArray,"glEnableVertexAttribArray");
    LOAD(pglGetUniformLocation,     "glGetUniformLocation");
    LOAD(pglUniform1i,              "glUniform1i");
    LOAD(pglActiveTexture,          "glActiveTexture");
    LOAD(pglTexImage3D,             "glTexImage3D");
    LOAD(pglBindAttribLocation,     "glBindAttribLocation");

    // --- volumetric fog module (prior-pass work) ---
    // Uploads a 4x4x4 RGB fog volume onto unit 0 and does NOT unbind.
    GLuint vol_tex;
    glGenTextures(1, &vol_tex);
    pglActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_3D, vol_tex);
    unsigned char vol_data[4*4*4*3];
    for (int i = 0; i < 4*4*4; ++i) {
        vol_data[i*3+0] = 200; vol_data[i*3+1] = 200; vol_data[i*3+2] = 220;
    }
    pglTexImage3D(GL_TEXTURE_3D, 0, GL_RGB, 4, 4, 4, 0, GL_RGB,
                  GL_UNSIGNED_BYTE, vol_data);
    // fog module "finishes" — unit 0 still holds GL_TEXTURE_3D=vol_tex.

    // --- terrain module ---
    // 2x2 solid-brown texture, uploaded onto unit 1.
    GLuint terrain_tex;
    glGenTextures(1, &terrain_tex);
    pglActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, terrain_tex);
    unsigned char px[2*2*3];
    for (int i = 0; i < 4; ++i) {
        px[i*3+0] = 153; px[i*3+1] = 115; px[i*3+2] = 51;
    }
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, 2, 2, 0, GL_RGB,
                 GL_UNSIGNED_BYTE, px);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);

    GLuint vs = compile_shader(GL_VERTEX_SHADER, VS);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, FS);
    GLuint prog = pglCreateProgram();
    pglAttachShader(prog, vs);
    pglAttachShader(prog, fs);
    pglBindAttribLocation(prog, 0, "aPos");
    pglBindAttribLocation(prog, 1, "aUV");
    pglLinkProgram(prog);
    pglUseProgram(prog);

    float quad[] = {
        -1.0f, -1.0f, 0.0f, 0.0f,
         1.0f, -1.0f, 1.0f, 0.0f,
         1.0f,  1.0f, 1.0f, 1.0f,
        -1.0f,  1.0f, 0.0f, 1.0f,
    };
    GLuint vbo;
    pglGenBuffers(1, &vbo);
    pglBindBuffer(GL_ARRAY_BUFFER, vbo);
    pglBufferData(GL_ARRAY_BUFFER, (GLsizeiptrX)sizeof(quad), quad, GL_STATIC_DRAW);
    pglEnableVertexAttribArray(0);
    pglVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 16, (void*)0);
    pglEnableVertexAttribArray(1);
    pglVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 16, (void*)(uintptr_t)8);

    GLint loc = pglGetUniformLocation(prog, "terrain_tex");
    // Off-by-one: terrain_tex is bound on unit 1, but the sampler is told
    // to read unit 0 — where the fog module's GL_TEXTURE_3D is still bound.
    // sampler2D on unit 0 falls through to the default 2D binding (texture 0),
    // returning black rather than the brown terrain texel.
    pglUniform1i(loc, 0);

    pglActiveTexture(GL_TEXTURE0);

    for (int i = 0; i < 3; ++i) {
        glViewport(0, 0, 400, 300);
        glClearColor(0.5f, 0.5f, 0.5f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        glDrawArrays(GL_TRIANGLE_FAN, 0, 4);
        glXSwapBuffers(dpy, win);
    }

    unsigned char rgba[4] = {0};
    glReadPixels(200, 150, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
    printf("center=%u,%u,%u,%u\n", rgba[0], rgba[1], rgba[2], rgba[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}