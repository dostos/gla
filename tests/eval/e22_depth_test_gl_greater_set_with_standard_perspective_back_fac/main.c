// SOURCE: synthetic (no upstream)
// Depth func GL_GREATER leaked from an earlier reversed-Z prepass setup;
// far quad occludes near quad when draws are issued back-to-front.
//
// Minimal OpenGL 2.1 / 3.3 compatible program. Uses GLX for context.
// Link: -lGL -lX11 -lm only. Compiles with:
//   gcc -Wall -std=gnu11 main.c -lGL -lX11 -lm
// Runs under Xvfb; exits cleanly after rendering 3-5 frames.
// The bug manifests on the first rendered frame.
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

static PFNGLCREATESHADERPROC glCreateShader_;
static PFNGLSHADERSOURCEPROC glShaderSource_;
static PFNGLCOMPILESHADERPROC glCompileShader_;
static PFNGLGETSHADERIVPROC glGetShaderiv_;
static PFNGLGETSHADERINFOLOGPROC glGetShaderInfoLog_;
static PFNGLCREATEPROGRAMPROC glCreateProgram_;
static PFNGLATTACHSHADERPROC glAttachShader_;
static PFNGLLINKPROGRAMPROC glLinkProgram_;
static PFNGLUSEPROGRAMPROC glUseProgram_;
static PFNGLGENBUFFERSPROC glGenBuffers_;
static PFNGLBINDBUFFERPROC glBindBuffer_;
static PFNGLBUFFERDATAPROC glBufferData_;
static PFNGLENABLEVERTEXATTRIBARRAYPROC glEnableVertexAttribArray_;
static PFNGLVERTEXATTRIBPOINTERPROC glVertexAttribPointer_;
static PFNGLGETATTRIBLOCATIONPROC glGetAttribLocation_;
static PFNGLGETUNIFORMLOCATIONPROC glGetUniformLocation_;
static PFNGLUNIFORM4FPROC glUniform4f_;
static PFNGLUNIFORMMATRIX4FVPROC glUniformMatrix4fv_;

#define LOAD(T, name) name##_ = (T)glXGetProcAddress((const GLubyte*)#name)

static void load_gl(void) {
    LOAD(PFNGLCREATESHADERPROC, glCreateShader);
    LOAD(PFNGLSHADERSOURCEPROC, glShaderSource);
    LOAD(PFNGLCOMPILESHADERPROC, glCompileShader);
    LOAD(PFNGLGETSHADERIVPROC, glGetShaderiv);
    LOAD(PFNGLGETSHADERINFOLOGPROC, glGetShaderInfoLog);
    LOAD(PFNGLCREATEPROGRAMPROC, glCreateProgram);
    LOAD(PFNGLATTACHSHADERPROC, glAttachShader);
    LOAD(PFNGLLINKPROGRAMPROC, glLinkProgram);
    LOAD(PFNGLUSEPROGRAMPROC, glUseProgram);
    LOAD(PFNGLGENBUFFERSPROC, glGenBuffers);
    LOAD(PFNGLBINDBUFFERPROC, glBindBuffer);
    LOAD(PFNGLBUFFERDATAPROC, glBufferData);
    LOAD(PFNGLENABLEVERTEXATTRIBARRAYPROC, glEnableVertexAttribArray);
    LOAD(PFNGLVERTEXATTRIBPOINTERPROC, glVertexAttribPointer);
    LOAD(PFNGLGETATTRIBLOCATIONPROC, glGetAttribLocation);
    LOAD(PFNGLGETUNIFORMLOCATIONPROC, glGetUniformLocation);
    LOAD(PFNGLUNIFORM4FPROC, glUniform4f);
    LOAD(PFNGLUNIFORMMATRIX4FVPROC, glUniformMatrix4fv);
}

static const char* VS =
    "#version 120\n"
    "attribute vec3 aPos;\n"
    "uniform mat4 uMVP;\n"
    "void main(){ gl_Position = uMVP * vec4(aPos,1.0); }\n";

static const char* FS =
    "#version 120\n"
    "uniform vec4 uColor;\n"
    "void main(){ gl_FragColor = uColor; }\n";

static GLuint compile_sh(GLenum type, const char* src) {
    GLuint s = glCreateShader_(type);
    glShaderSource_(s, 1, &src, NULL);
    glCompileShader_(s);
    GLint ok; glGetShaderiv_(s, GL_COMPILE_STATUS, &ok);
    if (!ok) { char log[1024]; glGetShaderInfoLog_(s, 1024, NULL, log); fprintf(stderr, "shader: %s\n", log); exit(1); }
    return s;
}

static void perspective(float* m, float fov, float aspect, float zn, float zf) {
    float f = 1.0f / tanf(fov * 0.5f);
    memset(m, 0, 16*sizeof(float));
    m[0] = f/aspect; m[5] = f;
    m[10] = (zf+zn)/(zn-zf); m[11] = -1.0f;
    m[14] = (2.0f*zf*zn)/(zn-zf);
}

static void translate(float* m, float x, float y, float z) {
    memset(m, 0, 16*sizeof(float));
    m[0]=m[5]=m[10]=m[15]=1.0f;
    m[12]=x; m[13]=y; m[14]=z;
}

static void mul4(float* out, const float* a, const float* b) {
    float r[16];
    for (int i=0;i<4;i++) for (int j=0;j<4;j++) {
        r[j*4+i]=0;
        for (int k=0;k<4;k++) r[j*4+i] += a[k*4+i]*b[j*4+k];
    }
    memcpy(out, r, sizeof(r));
}

// Pipeline bring-up for an early depth prepass (reversed-Z friendly).
// A subsequent refactor moved the actual prepass out, but this helper
// is still called from init and then "reset to standard" in main.
static void configure_depth_pipeline(void) {
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_GREATER);
    glClearDepth(0.0);
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    int attr[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, attr);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa = { .colormap = XCreateColormap(dpy, root, vi->visual, AllocNone), .event_mask = ExposureMask };
    Window win = XCreateWindow(dpy, root, 0, 0, 400, 300, 0, vi->depth, InputOutput, vi->visual, CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    load_gl();

    GLuint vs = compile_sh(GL_VERTEX_SHADER, VS);
    GLuint fs = compile_sh(GL_FRAGMENT_SHADER, FS);
    GLuint prog = glCreateProgram_();
    glAttachShader_(prog, vs);
    glAttachShader_(prog, fs);
    glLinkProgram_(prog);
    glUseProgram_(prog);

    float quad[] = {
        -0.5f,-0.5f,0.0f,  0.5f,-0.5f,0.0f,  0.5f, 0.5f,0.0f,
        -0.5f,-0.5f,0.0f,  0.5f, 0.5f,0.0f, -0.5f, 0.5f,0.0f,
    };
    GLuint vbo;
    glGenBuffers_(1, &vbo);
    glBindBuffer_(GL_ARRAY_BUFFER, vbo);
    glBufferData_(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    GLint aPos = glGetAttribLocation_(prog, "aPos");
    glEnableVertexAttribArray_(aPos);
    glVertexAttribPointer_(aPos, 3, GL_FLOAT, GL_FALSE, 3*sizeof(float), 0);
    GLint uMVP = glGetUniformLocation_(prog, "uMVP");
    GLint uColor = glGetUniformLocation_(prog, "uColor");

    // Initialize depth pipeline, then restore standard render state.
    configure_depth_pipeline();
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    // (depth func / clear depth assumed fine from defaults)

    float P[16], M1[16], M2[16], MVP_near[16], MVP_far[16];
    perspective(P, 1.0472f, 400.0f/300.0f, 0.1f, 100.0f);
    translate(M1, 0.0f, 0.0f, -2.0f);   // near quad (front)
    translate(M2, 0.0f, 0.0f, -5.0f);   // far quad (back)
    mul4(MVP_near, P, M1);
    mul4(MVP_far,  P, M2);

    for (int frame = 0; frame < 4; frame++) {
        glViewport(0, 0, 400, 300);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        // Standard painter's order: draw back first, front second.
        // Expectation: red (front) should cover blue (back).
        glUniformMatrix4fv_(uMVP, 1, GL_FALSE, MVP_far);
        glUniform4f_(uColor, 0.0f, 0.0f, 1.0f, 1.0f);  // blue (back)
        glDrawArrays(GL_TRIANGLES, 0, 6);

        glUniformMatrix4fv_(uMVP, 1, GL_FALSE, MVP_near);
        glUniform4f_(uColor, 1.0f, 0.0f, 0.0f, 1.0f);  // red (front)
        glDrawArrays(GL_TRIANGLES, 0, 6);

        glXSwapBuffers(dpy, win);
    }

    unsigned char px[4];
    glReadPixels(200, 150, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center pixel RGBA = %u %u %u %u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}