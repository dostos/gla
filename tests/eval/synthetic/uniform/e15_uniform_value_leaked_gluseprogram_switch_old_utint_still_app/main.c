// SOURCE: synthetic (no upstream)
// glUseProgram switches programs; the caller assumes uTint "carries over"
// because both programs declare the same uniform. In reality, uniform state
// is per-program, so program B's uTint stays at its default (0,0,0,0).
//
// Minimal OpenGL 2.1 / GLSL 120 program. Uses GLX for context.
// Link: -lGL -lX11 -lm only. Compiles with:
//   gcc -Wall -std=gnu11 main.c -lGL -lX11 -lm
// Runs under Xvfb; renders 3 frames, reads center pixel, exits.

#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <GL/glext.h>
#include <stdio.h>
#include <stdlib.h>

static PFNGLCREATESHADERPROC            pglCreateShader;
static PFNGLSHADERSOURCEPROC            pglShaderSource;
static PFNGLCOMPILESHADERPROC           pglCompileShader;
static PFNGLGETSHADERIVPROC             pglGetShaderiv;
static PFNGLGETSHADERINFOLOGPROC        pglGetShaderInfoLog;
static PFNGLCREATEPROGRAMPROC           pglCreateProgram;
static PFNGLATTACHSHADERPROC            pglAttachShader;
static PFNGLLINKPROGRAMPROC             pglLinkProgram;
static PFNGLGETPROGRAMIVPROC            pglGetProgramiv;
static PFNGLUSEPROGRAMPROC              pglUseProgram;
static PFNGLGETUNIFORMLOCATIONPROC      pglGetUniformLocation;
static PFNGLUNIFORM4FPROC               pglUniform4f;
static PFNGLGENBUFFERSPROC              pglGenBuffers;
static PFNGLBINDBUFFERPROC              pglBindBuffer;
static PFNGLBUFFERDATAPROC              pglBufferData;
static PFNGLGETATTRIBLOCATIONPROC       pglGetAttribLocation;
static PFNGLENABLEVERTEXATTRIBARRAYPROC pglEnableVertexAttribArray;
static PFNGLVERTEXATTRIBPOINTERPROC     pglVertexAttribPointer;

#define LOAD(T, n) p##n = (T)glXGetProcAddress((const GLubyte*)#n)

static void load_gl(void) {
    LOAD(PFNGLCREATESHADERPROC,            glCreateShader);
    LOAD(PFNGLSHADERSOURCEPROC,            glShaderSource);
    LOAD(PFNGLCOMPILESHADERPROC,           glCompileShader);
    LOAD(PFNGLGETSHADERIVPROC,             glGetShaderiv);
    LOAD(PFNGLGETSHADERINFOLOGPROC,        glGetShaderInfoLog);
    LOAD(PFNGLCREATEPROGRAMPROC,           glCreateProgram);
    LOAD(PFNGLATTACHSHADERPROC,            glAttachShader);
    LOAD(PFNGLLINKPROGRAMPROC,             glLinkProgram);
    LOAD(PFNGLGETPROGRAMIVPROC,            glGetProgramiv);
    LOAD(PFNGLUSEPROGRAMPROC,              glUseProgram);
    LOAD(PFNGLGETUNIFORMLOCATIONPROC,      glGetUniformLocation);
    LOAD(PFNGLUNIFORM4FPROC,               glUniform4f);
    LOAD(PFNGLGENBUFFERSPROC,              glGenBuffers);
    LOAD(PFNGLBINDBUFFERPROC,              glBindBuffer);
    LOAD(PFNGLBUFFERDATAPROC,              glBufferData);
    LOAD(PFNGLGETATTRIBLOCATIONPROC,       glGetAttribLocation);
    LOAD(PFNGLENABLEVERTEXATTRIBARRAYPROC, glEnableVertexAttribArray);
    LOAD(PFNGLVERTEXATTRIBPOINTERPROC,     glVertexAttribPointer);
}

static const char* VS =
    "#version 120\n"
    "attribute vec2 aPos;\n"
    "void main() { gl_Position = vec4(aPos, 0.0, 1.0); }\n";

// Both fragment shaders declare uTint with the same name and type. The
// application treats them as if they shared a single backing slot.
static const char* FS_SOLID =
    "#version 120\n"
    "uniform vec4 uTint;\n"
    "void main() { gl_FragColor = uTint; }\n";

static GLuint compile_shader(GLenum type, const char* src) {
    GLuint s = pglCreateShader(type);
    pglShaderSource(s, 1, &src, NULL);
    pglCompileShader(s);
    GLint ok = 0;
    pglGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024] = {0};
        pglGetShaderInfoLog(s, sizeof(log), NULL, log);
        fprintf(stderr, "shader compile failed: %s\n", log);
        exit(1);
    }
    return s;
}

static GLuint link_prog(const char* vs, const char* fs) {
    GLuint p = pglCreateProgram();
    pglAttachShader(p, compile_shader(GL_VERTEX_SHADER, vs));
    pglAttachShader(p, compile_shader(GL_FRAGMENT_SHADER, fs));
    pglLinkProgram(p);
    GLint ok = 0;
    pglGetProgramiv(p, GL_LINK_STATUS, &ok);
    if (!ok) { fprintf(stderr, "link failed\n"); exit(1); }
    return p;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }

    int attribs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attribs);
    if (!vi) { fprintf(stderr, "no visual\n"); return 1; }

    Window root = RootWindow(dpy, vi->screen);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 400, 300, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    GLXContext ctx = glXCreateContext(dpy, vi, NULL, True);
    glXMakeCurrent(dpy, win, ctx);

    load_gl();

    GLuint progA = link_prog(VS, FS_SOLID);
    GLuint progB = link_prog(VS, FS_SOLID);

    float sideQuad[] = {
        -1.0f, -1.0f,  -0.6f, -1.0f,  -0.6f,  1.0f,
        -1.0f, -1.0f,  -0.6f,  1.0f,  -1.0f,  1.0f,
    };
    float centerQuad[] = {
        -0.5f, -0.8f,   0.9f, -0.8f,   0.9f,  0.8f,
        -0.5f, -0.8f,   0.9f,  0.8f,  -0.5f,  0.8f,
    };

    GLuint vboA, vboB;
    pglGenBuffers(1, &vboA);
    pglBindBuffer(GL_ARRAY_BUFFER, vboA);
    pglBufferData(GL_ARRAY_BUFFER, sizeof(sideQuad), sideQuad, GL_STATIC_DRAW);
    pglGenBuffers(1, &vboB);
    pglBindBuffer(GL_ARRAY_BUFFER, vboB);
    pglBufferData(GL_ARRAY_BUFFER, sizeof(centerQuad), centerQuad, GL_STATIC_DRAW);

    GLint locTintA = pglGetUniformLocation(progA, "uTint");
    GLint aPosA    = pglGetAttribLocation(progA, "aPos");
    GLint aPosB    = pglGetAttribLocation(progB, "aPos");

    for (int frame = 0; frame < 3; ++frame) {
        glViewport(0, 0, 400, 300);
        glClearColor(0.1f, 0.1f, 0.1f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);

        // Pass 1: program A, uTint = red. Left-side bar.
        pglUseProgram(progA);
        pglUniform4f(locTintA, 1.0f, 0.0f, 0.0f, 1.0f);
        pglBindBuffer(GL_ARRAY_BUFFER, vboA);
        pglEnableVertexAttribArray(aPosA);
        pglVertexAttribPointer(aPosA, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);
        glDrawArrays(GL_TRIANGLES, 0, 6);

        // Pass 2: switch to program B. The author believes uTint is still
        // red because the uniform has the same name. No Uniform4f is issued.
        pglUseProgram(progB);
        pglBindBuffer(GL_ARRAY_BUFFER, vboB);
        pglEnableVertexAttribArray(aPosB);
        pglVertexAttribPointer(aPosB, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);
        glDrawArrays(GL_TRIANGLES, 0, 6);

        if (frame == 2) {
            unsigned char px[4] = {0};
            glReadPixels(200, 150, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
            printf("center RGBA = %u %u %u %u\n", px[0], px[1], px[2], px[3]);
        }

        glXSwapBuffers(dpy, win);
    }

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}