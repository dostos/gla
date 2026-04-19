// SOURCE: https://stackoverflow.com/questions/37858464/material-shines-through-when-zooming-out-three-js-r78
// Minimal repro: two thin, non-coplanar boxes rendered with a perspective projection.

#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef GLuint (*PFN_glCreateShaderProc)(GLenum);
typedef void (*PFN_glShaderSourceProc)(GLuint, GLsizei, const char *const *, const GLint *);
typedef void (*PFN_glCompileShaderProc)(GLuint);
typedef GLuint (*PFN_glCreateProgramProc)(void);
typedef void (*PFN_glAttachShaderProc)(GLuint, GLuint);
typedef void (*PFN_glLinkProgramProc)(GLuint);
typedef void (*PFN_glUseProgramProc)(GLuint);
typedef GLint (*PFN_glGetUniformLocationProc)(GLuint, const char *);
typedef void (*PFN_glUniformMatrix4fvProc)(GLint, GLsizei, GLboolean, const GLfloat *);
typedef void (*PFN_glUniform3fProc)(GLint, GLfloat, GLfloat, GLfloat);
typedef void (*PFN_glGenVertexArraysProc)(GLsizei, GLuint *);
typedef void (*PFN_glBindVertexArrayProc)(GLuint);
typedef void (*PFN_glGenBuffersProc)(GLsizei, GLuint *);
typedef void (*PFN_glBindBufferProc)(GLenum, GLuint);
typedef void (*PFN_glBufferDataProc)(GLenum, GLsizeiptr, const void *, GLenum);
typedef void (*PFN_glVertexAttribPointerProc)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void *);
typedef void (*PFN_glEnableVertexAttribArrayProc)(GLuint);

static PFN_glCreateShaderProc pglCreateShader;
static PFN_glShaderSourceProc pglShaderSource;
static PFN_glCompileShaderProc pglCompileShader;
static PFN_glCreateProgramProc pglCreateProgram;
static PFN_glAttachShaderProc pglAttachShader;
static PFN_glLinkProgramProc pglLinkProgram;
static PFN_glUseProgramProc pglUseProgram;
static PFN_glGetUniformLocationProc pglGetUniformLocation;
static PFN_glUniformMatrix4fvProc pglUniformMatrix4fv;
static PFN_glUniform3fProc pglUniform3f;
static PFN_glGenVertexArraysProc pglGenVertexArrays;
static PFN_glBindVertexArrayProc pglBindVertexArray;
static PFN_glGenBuffersProc pglGenBuffers;
static PFN_glBindBufferProc pglBindBuffer;
static PFN_glBufferDataProc pglBufferData;
static PFN_glVertexAttribPointerProc pglVertexAttribPointer;
static PFN_glEnableVertexAttribArrayProc pglEnableVertexAttribArray;

#define GL_ARRAY_BUFFER 0x8892
#define GL_STATIC_DRAW 0x88E4
#define GL_VERTEX_SHADER 0x8B31
#define GL_FRAGMENT_SHADER 0x8B30

#define LOAD(name) p##name = (PFN_##name##Proc)glXGetProcAddressARB((const GLubyte *)#name)

static void load_gl(void) {
    LOAD(glCreateShader); LOAD(glShaderSource); LOAD(glCompileShader);
    LOAD(glCreateProgram); LOAD(glAttachShader); LOAD(glLinkProgram);
    LOAD(glUseProgram); LOAD(glGetUniformLocation);
    LOAD(glUniformMatrix4fv); LOAD(glUniform3f);
    LOAD(glGenVertexArrays); LOAD(glBindVertexArray);
    LOAD(glGenBuffers); LOAD(glBindBuffer); LOAD(glBufferData);
    LOAD(glVertexAttribPointer); LOAD(glEnableVertexAttribArray);
}

static const char *vs_src =
    "#version 330 core\n"
    "layout(location=0) in vec3 aPos;\n"
    "uniform mat4 uMVP;\n"
    "void main(){ gl_Position = uMVP * vec4(aPos,1.0); }\n";

static const char *fs_src =
    "#version 330 core\n"
    "uniform vec3 uColor;\n"
    "out vec4 oFrag;\n"
    "void main(){ oFrag = vec4(uColor,1.0); }\n";

static void mat4_identity(float *m) { memset(m, 0, 64); m[0]=m[5]=m[10]=m[15]=1.0f; }
static void mat4_translate(float *m, float x, float y, float z) {
    mat4_identity(m); m[12]=x; m[13]=y; m[14]=z;
}
static void mat4_mul(float *r, const float *a, const float *b) {
    float t[16];
    for (int i=0;i<4;i++) for (int j=0;j<4;j++) {
        t[i*4+j] = a[0*4+j]*b[i*4+0] + a[1*4+j]*b[i*4+1] + a[2*4+j]*b[i*4+2] + a[3*4+j]*b[i*4+3];
    }
    memcpy(r, t, 64);
}
static void mat4_perspective(float *m, float fovy, float aspect, float zn, float zf) {
    float f = 1.0f / tanf(fovy*0.5f);
    memset(m, 0, 64);
    m[0] = f/aspect; m[5] = f;
    m[10] = (zf+zn)/(zn-zf); m[11] = -1.0f;
    m[14] = (2.0f*zf*zn)/(zn-zf);
}

int main(void) {
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    int attribs[] = {GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None};
    XVisualInfo *vi = glXChooseVisual(dpy, DefaultScreen(dpy), attribs);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 800, 600, 0, vi->depth,
        InputOutput, vi->visual, CWColormap|CWEventMask, &swa);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);
    load_gl();

    GLuint vs = pglCreateShader(GL_VERTEX_SHADER);
    pglShaderSource(vs, 1, &vs_src, NULL); pglCompileShader(vs);
    GLuint fs = pglCreateShader(GL_FRAGMENT_SHADER);
    pglShaderSource(fs, 1, &fs_src, NULL); pglCompileShader(fs);
    GLuint prog = pglCreateProgram();
    pglAttachShader(prog, vs); pglAttachShader(prog, fs); pglLinkProgram(prog);
    pglUseProgram(prog);

    // Thin box (20000 x 20000 x 1) centered at origin.
    float half = 10000.0f;
    float verts[] = {
        -half,-half,-0.5f,  half,-half,-0.5f,  half, half,-0.5f,
        -half,-half,-0.5f,  half, half,-0.5f, -half, half,-0.5f,
        -half,-half, 0.5f,  half, half, 0.5f,  half,-half, 0.5f,
        -half,-half, 0.5f, -half, half, 0.5f,  half, half, 0.5f,
    };
    GLuint vao, vbo;
    pglGenVertexArrays(1, &vao); pglBindVertexArray(vao);
    pglGenBuffers(1, &vbo); pglBindBuffer(GL_ARRAY_BUFFER, vbo);
    pglBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    pglVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 12, 0);
    pglEnableVertexAttribArray(0);

    float proj[16], view[16], model_near[16], model_far[16], mv[16], mvp[16];
    mat4_perspective(proj, 45.0f * 3.14159265f / 180.0f, 800.0f/600.0f,
                     0.1f,
                     60000.0f);

    mat4_translate(view, 0.0f, 0.0f, -30000.0f);

    glViewport(0, 0, 800, 600);
    glEnable(GL_DEPTH_TEST);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    GLint uMVP = pglGetUniformLocation(prog, "uMVP");
    GLint uCol = pglGetUniformLocation(prog, "uColor");

    // Far (red) box: at z = -1 in view space (relative to view translate).
    mat4_translate(model_far, 0.0f, 0.0f, -1.0f);
    mat4_mul(mv, view, model_far); mat4_mul(mvp, proj, mv);
    pglUniformMatrix4fv(uMVP, 1, GL_FALSE, mvp);
    pglUniform3f(uCol, 1.0f, 0.0f, 0.0f);
    glDrawArrays(GL_TRIANGLES, 0, 12);

    // Near (green) box: 1 unit in front of the red box, gap of 1 unit.
    mat4_translate(model_near, 0.0f, 0.0f, 1.0f);
    mat4_mul(mv, view, model_near); mat4_mul(mvp, proj, mv);
    pglUniformMatrix4fv(uMVP, 1, GL_FALSE, mvp);
    pglUniform3f(uCol, 0.0f, 1.0f, 0.0f);
    glDrawArrays(GL_TRIANGLES, 0, 12);

    glXSwapBuffers(dpy, win);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}