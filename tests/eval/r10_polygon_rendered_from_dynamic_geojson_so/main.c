// SOURCE: https://github.com/mapbox/mapbox-gl-js/issues/13299
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

typedef void (*PFNGLGENBUFFERSPROC)(GLsizei, GLuint*);
typedef void (*PFNGLBINDBUFFERPROC)(GLenum, GLuint);
typedef void (*PFNGLBUFFERDATAPROC)(GLenum, GLsizeiptr, const void*, GLenum);
typedef void (*PFNGLGENVERTEXARRAYSPROC)(GLsizei, GLuint*);
typedef void (*PFNGLBINDVERTEXARRAYPROC)(GLuint);
typedef void (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef GLuint (*PFNGLCREATESHADERPROC)(GLenum);
typedef void (*PFNGLSHADERSOURCEPROC)(GLuint, GLsizei, const char* const*, const GLint*);
typedef void (*PFNGLCOMPILESHADERPROC)(GLuint);
typedef GLuint (*PFNGLCREATEPROGRAMPROC)(void);
typedef void (*PFNGLATTACHSHADERPROC)(GLuint, GLuint);
typedef void (*PFNGLLINKPROGRAMPROC)(GLuint);
typedef void (*PFNGLUSEPROGRAMPROC)(GLuint);
typedef GLint (*PFNGLGETUNIFORMLOCATIONPROC)(GLuint, const char*);
typedef void (*PFNGLUNIFORM4FPROC)(GLint, GLfloat, GLfloat, GLfloat, GLfloat);

#define L(T,N) T N = (T)glXGetProcAddress((const GLubyte*)#N)

static const char* VS =
    "#version 330 core\n"
    "layout(location=0) in vec2 p;\n"
    "void main(){ gl_Position = vec4(p,0.0,1.0); }\n";
static const char* FS =
    "#version 330 core\n"
    "uniform vec4 uColor;\n"
    "out vec4 o;\n"
    "void main(){ o = uColor; }\n";

// Simulates a polygon that has been split across two tile regions, where
// each tile independently re-projects its vertices. A tiny per-tile
// coordinate offset (like the one a dynamic GeoJSON source would introduce
// when re-tiling at a different zoom quantization) produces a visible seam
// where the fills should have met.
static const float TILE_A[] = {
    -0.8f, -0.6f,
     0.0f, -0.6f,
     0.0f,  0.6f,
    -0.8f, -0.6f,
     0.0f,  0.6f,
    -0.8f,  0.6f,
};

// Same border X=0.0 in principle, but the "dynamic" tile arrives with a
// slightly shifted left edge.
static const float TILE_B[] = {
     0.01f, -0.6f,
     0.8f,  -0.6f,
     0.8f,   0.6f,
     0.01f, -0.6f,
     0.8f,   0.6f,
     0.01f,  0.6f,
};

int main(void){
    Display* dpy = XOpenDisplay(NULL);
    if(!dpy){ fprintf(stderr,"no display\n"); return 1; }
    int attr[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE,24, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attr);
    Colormap cmap = XCreateColormap(dpy, RootWindow(dpy, vi->screen), vi->visual, AllocNone);
    XSetWindowAttributes swa; swa.colormap = cmap; swa.event_mask = ExposureMask;
    Window w = XCreateWindow(dpy, RootWindow(dpy, vi->screen), 0,0,512,512,0,
        vi->depth, InputOutput, vi->visual, CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, w);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, w, ctx);

    L(PFNGLGENBUFFERSPROC, glGenBuffers);
    L(PFNGLBINDBUFFERPROC, glBindBuffer);
    L(PFNGLBUFFERDATAPROC, glBufferData);
    L(PFNGLGENVERTEXARRAYSPROC, glGenVertexArrays);
    L(PFNGLBINDVERTEXARRAYPROC, glBindVertexArray);
    L(PFNGLVERTEXATTRIBPOINTERPROC, glVertexAttribPointer);
    L(PFNGLENABLEVERTEXATTRIBARRAYPROC, glEnableVertexAttribArray);
    L(PFNGLCREATESHADERPROC, glCreateShader);
    L(PFNGLSHADERSOURCEPROC, glShaderSource);
    L(PFNGLCOMPILESHADERPROC, glCompileShader);
    L(PFNGLCREATEPROGRAMPROC, glCreateProgram);
    L(PFNGLATTACHSHADERPROC, glAttachShader);
    L(PFNGLLINKPROGRAMPROC, glLinkProgram);
    L(PFNGLUSEPROGRAMPROC, glUseProgram);
    L(PFNGLGETUNIFORMLOCATIONPROC, glGetUniformLocation);
    L(PFNGLUNIFORM4FPROC, glUniform4f);

    GLuint vs = glCreateShader(GL_VERTEX_SHADER);
    glShaderSource(vs,1,&VS,NULL); glCompileShader(vs);
    GLuint fs = glCreateShader(GL_FRAGMENT_SHADER);
    glShaderSource(fs,1,&FS,NULL); glCompileShader(fs);
    GLuint prog = glCreateProgram();
    glAttachShader(prog,vs); glAttachShader(prog,fs); glLinkProgram(prog);
    glUseProgram(prog);
    GLint uColor = glGetUniformLocation(prog,"uColor");

    GLuint vao[2], vbo[2];
    glGenVertexArrays(2, vao);
    glGenBuffers(2, vbo);

    glBindVertexArray(vao[0]);
    glBindBuffer(GL_ARRAY_BUFFER, vbo[0]);
    glBufferData(GL_ARRAY_BUFFER, sizeof(TILE_A), TILE_A, GL_STATIC_DRAW);
    glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,0,0);
    glEnableVertexAttribArray(0);

    glBindVertexArray(vao[1]);
    glBindBuffer(GL_ARRAY_BUFFER, vbo[1]);
    glBufferData(GL_ARRAY_BUFFER, sizeof(TILE_B), TILE_B, GL_STATIC_DRAW);
    glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,0,0);
    glEnableVertexAttribArray(0);

    glClearColor(1.0f,1.0f,1.0f,1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    glUniform4f(uColor, 0.1f, 0.4f, 0.9f, 1.0f);
    glBindVertexArray(vao[0]);
    glDrawArrays(GL_TRIANGLES, 0, 6);
    glBindVertexArray(vao[1]);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glFinish();

    unsigned char px[4];
    glReadPixels(256, 256, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center pixel rgba=%d,%d,%d,%d\n", px[0], px[1], px[2], px[3]);

    glXSwapBuffers(dpy, w);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, w);
    XCloseDisplay(dpy);
    return 0;
}