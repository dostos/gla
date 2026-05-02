// SOURCE: https://github.com/godotengine/godot/issues/114069
//
// NOTE: This scenario targets a Metal-specific bug in Godot 4.6 on macOS.
// It does NOT reproduce on Linux / OpenGL / Vulkan (including MoltenVK).
// This file is a minimal stub that demonstrates the *pattern* the upstream
// maintainer identified ("dynamic uniform buffers... appear to be
// corrupted" when rendering transparent meshes with per-frame rotation).
// The real repro lives in the upstream snapshot — see scenario.md.
//
// The stub: a transparent quad drawn with a per-frame-updated dynamic UBO
// containing a rotating MVP and an alpha. On conformant GL implementations
// this renders cleanly; the bug is Metal-driver-specific.

#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

typedef void (*PFNGLGENBUFFERSPROC)(GLsizei, GLuint*);
typedef void (*PFNGLBINDBUFFERPROC)(GLenum, GLuint);
typedef void (*PFNGLBUFFERDATAPROC)(GLenum, GLsizeiptr, const void*, GLenum);
typedef void (*PFNGLBUFFERSUBDATAPROC)(GLenum, GLintptr, GLsizeiptr, const void*);
typedef void (*PFNGLBINDBUFFERBASEPROC)(GLenum, GLuint, GLuint);
typedef GLuint (*PFNGLCREATESHADERPROC)(GLenum);
typedef void (*PFNGLSHADERSOURCEPROC)(GLuint, GLsizei, const char* const*, const GLint*);
typedef void (*PFNGLCOMPILESHADERPROC)(GLuint);
typedef GLuint (*PFNGLCREATEPROGRAMPROC)(void);
typedef void (*PFNGLATTACHSHADERPROC)(GLuint, GLuint);
typedef void (*PFNGLLINKPROGRAMPROC)(GLuint);
typedef void (*PFNGLUSEPROGRAMPROC)(GLuint);
typedef void (*PFNGLGENVERTEXARRAYSPROC)(GLsizei, GLuint*);
typedef void (*PFNGLBINDVERTEXARRAYPROC)(GLuint);
typedef void (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef GLuint (*PFNGLGETUNIFORMBLOCKINDEXPROC)(GLuint, const char*);
typedef void (*PFNGLUNIFORMBLOCKBINDINGPROC)(GLuint, GLuint, GLuint);

#define GL_ARRAY_BUFFER 0x8892
#define GL_UNIFORM_BUFFER 0x8A11
#define GL_DYNAMIC_DRAW 0x88E8
#define GL_VERTEX_SHADER 0x8B31
#define GL_FRAGMENT_SHADER 0x8B30

static const char* VS =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "layout(std140) uniform PerFrame { mat4 mvp; vec4 color; };\n"
    "void main(){ gl_Position = mvp * vec4(aPos,0.0,1.0); }\n";
static const char* FS =
    "#version 330 core\n"
    "layout(std140) uniform PerFrame { mat4 mvp; vec4 color; };\n"
    "out vec4 FragColor;\n"
    "void main(){ FragColor = color; }\n";

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int attribs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, attribs);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 512, 512, 0, vi->depth,
        InputOutput, vi->visual, CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    #define L(T,N) T N = (T)glXGetProcAddress((const GLubyte*)#N)
    L(PFNGLGENBUFFERSPROC, glGenBuffers);
    L(PFNGLBINDBUFFERPROC, glBindBuffer);
    L(PFNGLBUFFERDATAPROC, glBufferData);
    L(PFNGLBUFFERSUBDATAPROC, glBufferSubData);
    L(PFNGLBINDBUFFERBASEPROC, glBindBufferBase);
    L(PFNGLCREATESHADERPROC, glCreateShader);
    L(PFNGLSHADERSOURCEPROC, glShaderSource);
    L(PFNGLCOMPILESHADERPROC, glCompileShader);
    L(PFNGLCREATEPROGRAMPROC, glCreateProgram);
    L(PFNGLATTACHSHADERPROC, glAttachShader);
    L(PFNGLLINKPROGRAMPROC, glLinkProgram);
    L(PFNGLUSEPROGRAMPROC, glUseProgram);
    L(PFNGLGENVERTEXARRAYSPROC, glGenVertexArrays);
    L(PFNGLBINDVERTEXARRAYPROC, glBindVertexArray);
    L(PFNGLVERTEXATTRIBPOINTERPROC, glVertexAttribPointer);
    L(PFNGLENABLEVERTEXATTRIBARRAYPROC, glEnableVertexAttribArray);
    L(PFNGLGETUNIFORMBLOCKINDEXPROC, glGetUniformBlockIndex);
    L(PFNGLUNIFORMBLOCKBINDINGPROC, glUniformBlockBinding);

    GLuint vs = glCreateShader(GL_VERTEX_SHADER);
    glShaderSource(vs, 1, &VS, NULL); glCompileShader(vs);
    GLuint fs = glCreateShader(GL_FRAGMENT_SHADER);
    glShaderSource(fs, 1, &FS, NULL); glCompileShader(fs);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs); glAttachShader(prog, fs); glLinkProgram(prog);
    GLuint block = glGetUniformBlockIndex(prog, "PerFrame");
    glUniformBlockBinding(prog, block, 0);

    float quad[] = { -0.5f,-0.5f, 0.5f,-0.5f, 0.5f,0.5f, -0.5f,0.5f };
    GLuint vao, vbo; glGenVertexArrays(1,&vao); glBindVertexArray(vao);
    glGenBuffers(1,&vbo); glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_DYNAMIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 8, 0);
    glEnableVertexAttribArray(0);

    // Dynamic UBO ring (3 buffers, mimicking Metal triple-buffering).
    GLuint ubo[3]; glGenBuffers(3, ubo);
    float data[20] = {0};
    for (int i = 0; i < 3; i++) {
        glBindBuffer(GL_UNIFORM_BUFFER, ubo[i]);
        glBufferData(GL_UNIFORM_BUFFER, sizeof(data), data, GL_DYNAMIC_DRAW);
    }

    glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glClearColor(0.1f, 0.1f, 0.2f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(prog);

    float t = 0.3f, c = cosf(t), s = sinf(t);
    float mvp[16] = { c,-s,0,0,  s,c,0,0,  0,0,1,0,  0,0,0,1 };
    memcpy(&data[0], mvp, sizeof(mvp));
    data[16]=0.2f; data[17]=0.8f; data[18]=0.3f; data[19]=0.4f; // RGBA alpha=0.4

    int idx = 0; // ring index; in the bug, this index's buffer gets clobbered
    glBindBuffer(GL_UNIFORM_BUFFER, ubo[idx]);
    glBufferSubData(GL_UNIFORM_BUFFER, 0, sizeof(data), data);
    glBindBufferBase(GL_UNIFORM_BUFFER, 0, ubo[idx]);
    glDrawArrays(GL_TRIANGLE_FAN, 0, 4);

    glXSwapBuffers(dpy, win);
    return 0;
}