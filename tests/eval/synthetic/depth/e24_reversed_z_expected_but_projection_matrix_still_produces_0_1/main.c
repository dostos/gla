// SOURCE: synthetic (no upstream)
// Reversed-Z conventions (glClearDepth(0) + GL_GREATER) paired with a
// standard [-1,1] NDC perspective matrix — draw order is silently inverted.
//
// Minimal OpenGL 2.1 / GLSL 120 program using GLX.
//   gcc -Wall -std=gnu11 main.c -lGL -lX11 -lm
// Runs under Xvfb; renders 4 frames, prints center pixel, exits.
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

typedef char GLchar;
typedef ptrdiff_t GLsizeiptr;

#define GL_ARRAY_BUFFER         0x8892
#define GL_STATIC_DRAW          0x88E4
#define GL_VERTEX_SHADER        0x8B31
#define GL_FRAGMENT_SHADER      0x8B30
#define GL_COMPILE_STATUS       0x8B81

typedef void   (*P_GenBuffers)(GLsizei, GLuint*);
typedef void   (*P_BindBuffer)(GLenum, GLuint);
typedef void   (*P_BufferData)(GLenum, GLsizeiptr, const void*, GLenum);
typedef GLuint (*P_CreateShader)(GLenum);
typedef void   (*P_ShaderSource)(GLuint, GLsizei, const GLchar* const*, const GLint*);
typedef void   (*P_CompileShader)(GLuint);
typedef void   (*P_GetShaderiv)(GLuint, GLenum, GLint*);
typedef void   (*P_GetShaderInfoLog)(GLuint, GLsizei, GLsizei*, GLchar*);
typedef GLuint (*P_CreateProgram)(void);
typedef void   (*P_AttachShader)(GLuint, GLuint);
typedef void   (*P_LinkProgram)(GLuint);
typedef void   (*P_UseProgram)(GLuint);
typedef GLint  (*P_GetAttribLocation)(GLuint, const GLchar*);
typedef GLint  (*P_GetUniformLocation)(GLuint, const GLchar*);
typedef void   (*P_UniformMatrix4fv)(GLint, GLsizei, GLboolean, const GLfloat*);
typedef void   (*P_Uniform3fv)(GLint, GLsizei, const GLfloat*);
typedef void   (*P_EnableVertexAttribArray)(GLuint);
typedef void   (*P_VertexAttribPointer)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);

static P_GenBuffers              glGenBuffers_;
static P_BindBuffer              glBindBuffer_;
static P_BufferData              glBufferData_;
static P_CreateShader            glCreateShader_;
static P_ShaderSource            glShaderSource_;
static P_CompileShader           glCompileShader_;
static P_GetShaderiv             glGetShaderiv_;
static P_GetShaderInfoLog        glGetShaderInfoLog_;
static P_CreateProgram           glCreateProgram_;
static P_AttachShader            glAttachShader_;
static P_LinkProgram             glLinkProgram_;
static P_UseProgram              glUseProgram_;
static P_GetAttribLocation       glGetAttribLocation_;
static P_GetUniformLocation      glGetUniformLocation_;
static P_UniformMatrix4fv        glUniformMatrix4fv_;
static P_Uniform3fv              glUniform3fv_;
static P_EnableVertexAttribArray glEnableVertexAttribArray_;
static P_VertexAttribPointer     glVertexAttribPointer_;

#define L(T, fn) fn##_ = (T)glXGetProcAddress((const GLubyte*)#fn)

static void load_gl(void) {
    L(P_GenBuffers, glGenBuffers);
    L(P_BindBuffer, glBindBuffer);
    L(P_BufferData, glBufferData);
    L(P_CreateShader, glCreateShader);
    L(P_ShaderSource, glShaderSource);
    L(P_CompileShader, glCompileShader);
    L(P_GetShaderiv, glGetShaderiv);
    L(P_GetShaderInfoLog, glGetShaderInfoLog);
    L(P_CreateProgram, glCreateProgram);
    L(P_AttachShader, glAttachShader);
    L(P_LinkProgram, glLinkProgram);
    L(P_UseProgram, glUseProgram);
    L(P_GetAttribLocation, glGetAttribLocation);
    L(P_GetUniformLocation, glGetUniformLocation);
    L(P_UniformMatrix4fv, glUniformMatrix4fv);
    L(P_Uniform3fv, glUniform3fv);
    L(P_EnableVertexAttribArray, glEnableVertexAttribArray);
    L(P_VertexAttribPointer, glVertexAttribPointer);
}

static const char* VS =
    "#version 120\n"
    "attribute vec3 aPos;\n"
    "uniform mat4 uProj;\n"
    "uniform mat4 uView;\n"
    "void main(){ gl_Position = uProj * uView * vec4(aPos,1.0); }\n";

static const char* FS =
    "#version 120\n"
    "uniform vec3 uColor;\n"
    "void main(){ gl_FragColor = vec4(uColor,1.0); }\n";

static GLuint compile_shader(GLenum type, const char* src) {
    GLuint s = glCreateShader_(type);
    glShaderSource_(s, 1, &src, NULL);
    glCompileShader_(s);
    GLint ok = 0;
    glGetShaderiv_(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog_(s, 1024, NULL, log);
        fprintf(stderr, "shader compile failed: %s\n", log);
        exit(1);
    }
    return s;
}

static void perspective_std(float* m, float fovY, float aspect, float n, float f) {
    float t = 1.0f / tanf(fovY * 0.5f);
    memset(m, 0, 16 * sizeof(float));
    m[0]  = t / aspect;
    m[5]  = t;
    m[10] = (f + n) / (n - f);
    m[11] = -1.0f;
    m[14] = (2.0f * f * n) / (n - f);
}

static void identity4(float* m) {
    memset(m, 0, 16 * sizeof(float));
    m[0] = m[5] = m[10] = m[15] = 1.0f;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int attr[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attr);
    Colormap cmap = XCreateColormap(dpy, RootWindow(dpy, vi->screen), vi->visual, AllocNone);
    XSetWindowAttributes swa = { .colormap = cmap, .event_mask = ExposureMask };
    Window win = XCreateWindow(dpy, RootWindow(dpy, vi->screen),
                               0, 0, 400, 300, 0, vi->depth, InputOutput,
                               vi->visual, CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, True);
    glXMakeCurrent(dpy, win, ctx);
    load_gl();

    GLuint vs = compile_shader(GL_VERTEX_SHADER, VS);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, FS);
    GLuint prog = glCreateProgram_();
    glAttachShader_(prog, vs);
    glAttachShader_(prog, fs);
    glLinkProgram_(prog);
    glUseProgram_(prog);

    float near_tri[] = {
        -0.9f,-0.9f,-1.0f,   0.9f,-0.9f,-1.0f,   0.0f, 0.9f,-1.0f,
    };
    float far_tri[] = {
        -3.0f,-3.0f,-5.0f,   3.0f,-3.0f,-5.0f,   0.0f, 3.0f,-5.0f,
    };

    GLuint vbo_near, vbo_far;
    glGenBuffers_(1, &vbo_near);
    glBindBuffer_(GL_ARRAY_BUFFER, vbo_near);
    glBufferData_(GL_ARRAY_BUFFER, sizeof(near_tri), near_tri, GL_STATIC_DRAW);
    glGenBuffers_(1, &vbo_far);
    glBindBuffer_(GL_ARRAY_BUFFER, vbo_far);
    glBufferData_(GL_ARRAY_BUFFER, sizeof(far_tri), far_tri, GL_STATIC_DRAW);

    GLint loc_pos   = glGetAttribLocation_(prog, "aPos");
    GLint loc_proj  = glGetUniformLocation_(prog, "uProj");
    GLint loc_view  = glGetUniformLocation_(prog, "uView");
    GLint loc_color = glGetUniformLocation_(prog, "uColor");

    float P[16], V[16];
    perspective_std(P, 60.0f * (float)M_PI / 180.0f, 400.0f / 300.0f, 0.1f, 100.0f);
    identity4(V);

    // Reversed-Z conventions: clear depth to 0, pass-if-greater.
    // Intent: near fragments (which in reversed-Z map to ~1) overwrite far (~0).
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_GREATER);
    glClearDepth(0.0);

    for (int frame = 0; frame < 4; ++frame) {
        glViewport(0, 0, 400, 300);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        glUseProgram_(prog);
        glUniformMatrix4fv_(loc_proj, 1, GL_FALSE, P);
        glUniformMatrix4fv_(loc_view, 1, GL_FALSE, V);
        glEnableVertexAttribArray_(loc_pos);

        // Draw order: near (red) first, then far (blue).
        // In proper reversed-Z this yields red at center (far rejected).
        float red[3]  = { 0.9f, 0.2f, 0.2f };
        glBindBuffer_(GL_ARRAY_BUFFER, vbo_near);
        glVertexAttribPointer_(loc_pos, 3, GL_FLOAT, GL_FALSE, 0, (void*)0);
        glUniform3fv_(loc_color, 1, red);
        glDrawArrays(GL_TRIANGLES, 0, 3);

        float blue[3] = { 0.2f, 0.2f, 0.9f };
        glBindBuffer_(GL_ARRAY_BUFFER, vbo_far);
        glVertexAttribPointer_(loc_pos, 3, GL_FLOAT, GL_FALSE, 0, (void*)0);
        glUniform3fv_(loc_color, 1, blue);
        glDrawArrays(GL_TRIANGLES, 0, 3);

        glXSwapBuffers(dpy, win);
    }

    unsigned char px[4] = {0};
    glReadPixels(200, 150, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center pixel: R=%u G=%u B=%u A=%u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XFreeColormap(dpy, cmap);
    XFree(vi);
    XCloseDisplay(dpy);
    return 0;
}