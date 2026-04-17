// tests/eval/e2_nan_propagation.c
//
// E2: NaN Propagation
//
// Draws 1 lit quad with a normal matrix uniform.
//
// Bug: Model matrix has scale(1, 1, 0) -- zero Z scale -- making it singular.
//      The normal matrix = transpose(inverse(model)) produces Inf/NaN.
//      The fragment shader computes diffuse lighting using the corrupted normal,
//      and max(NaN, 0.0) evaluates to 0, making the lit object appear black.
//
// Expected (if bug were fixed):
//   - Object area shows a lit color ~(0.7, 0.5, 0.2) (warm orange-ish lit by baseColor)
//
// Actual (with bug):
//   - Object area is black (0,0,0) -- lighting produces zero due to NaN
//
// GLA reveals: inspect_drawcall(0).params shows normalMatrix with Inf values.
// Pixel check: object center is black instead of a lit warm color.
//
// Clear color: dark blue (0.1, 0.1, 0.3, 1.0) -- 400x300 window, 5 frames.

#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

typedef GLuint (*PFNGLCREATESHADERPROC)(GLenum);
typedef void   (*PFNGLSHADERSOURCEPROC)(GLuint, GLsizei, const GLchar *const*, const GLint *);
typedef void   (*PFNGLCOMPILESHADERPROC)(GLuint);
typedef void   (*PFNGLGETSHADERIVPROC)(GLuint, GLenum, GLint *);
typedef void   (*PFNGLGETSHADERINFOLOGPROC)(GLuint, GLsizei, GLsizei *, GLchar *);
typedef GLuint (*PFNGLCREATEPROGRAMPROC)(void);
typedef void   (*PFNGLATTACHSHADERPROC)(GLuint, GLuint);
typedef void   (*PFNGLLINKPROGRAMPROC)(GLuint);
typedef void   (*PFNGLGETPROGRAMIVPROC)(GLuint, GLenum, GLint *);
typedef void   (*PFNGLGETPROGRAMINFOLOGPROC)(GLuint, GLsizei, GLsizei *, GLchar *);
typedef void   (*PFNGLUSEPROGRAMPROC)(GLuint);
typedef GLint  (*PFNGLGETUNIFORMLOCATIONPROC)(GLuint, const GLchar *);
typedef void   (*PFNGLUNIFORM3FPROC)(GLint, GLfloat, GLfloat, GLfloat);
typedef void   (*PFNGLUNIFORMMATRIX3FVPROC)(GLint, GLsizei, GLboolean, const GLfloat *);
typedef void   (*PFNGLGENBUFFERSPROC)(GLsizei, GLuint *);
typedef void   (*PFNGLBINDBUFFERPROC)(GLenum, GLuint);
typedef void   (*PFNGLBUFFERDATAPROC)(GLenum, GLsizeiptr, const void *, GLenum);
typedef void   (*PFNGLGENVERTEXARRAYSPROC)(GLsizei, GLuint *);
typedef void   (*PFNGLBINDVERTEXARRAYPROC)(GLuint);
typedef void   (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef void   (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void *);
typedef GLint  (*PFNGLGETATTRIBLOCATIONPROC)(GLuint, const GLchar *);
typedef void   (*PFNGLDELETESHADERPROC)(GLuint);
typedef void   (*PFNGLDELETEPROGRAMPROC)(GLuint);
typedef void   (*PFNGLDELETEBUFFERSPROC)(GLsizei, const GLuint *);
typedef void   (*PFNGLDELETEVERTEXARRAYSPROC)(GLsizei, const GLuint *);

#define LOAD_PROC(type, name) \
    type name = (type)glXGetProcAddress((const GLubyte *)#name); \
    if (!name) { fprintf(stderr, "Cannot resolve " #name "\n"); return 1; }

// Vertex shader: pass-through with normal transform
static const char *vert_src =
    "#version 120\n"
    "attribute vec3 aPos;\n"
    "attribute vec3 aNormal;\n"
    "uniform mat3 uNormalMatrix;\n"
    "varying vec3 vNormal;\n"
    "void main() {\n"
    "    gl_Position = vec4(aPos, 1.0);\n"
    "    vNormal = uNormalMatrix * aNormal;\n"  // NaN propagates here
    "}\n";

// Fragment shader: diffuse lighting with base color
// color = max(dot(normal, lightDir), 0.0) * baseColor
// When normalMatrix has Inf/NaN, the normal becomes NaN,
// dot(NaN, lightDir) = NaN, max(NaN, 0.0) = 0.0 -> black
static const char *frag_src =
    "#version 120\n"
    "uniform vec3 uBaseColor;\n"
    "varying vec3 vNormal;\n"
    "void main() {\n"
    "    vec3 lightDir = normalize(vec3(0.5, 0.7, 1.0));\n"
    "    vec3 n = normalize(vNormal);\n"
    "    float diff = max(dot(n, lightDir), 0.0);\n"  // NaN -> 0 -> black
    "    gl_FragColor = vec4(uBaseColor * diff, 1.0);\n"
    "}\n";

static GLuint compile_shader(
    PFNGLCREATESHADERPROC     glCreateShader,
    PFNGLSHADERSOURCEPROC     glShaderSource,
    PFNGLCOMPILESHADERPROC    glCompileShader,
    PFNGLGETSHADERIVPROC      glGetShaderiv,
    PFNGLGETSHADERINFOLOGPROC glGetShaderInfoLog,
    GLenum type, const char *src)
{
    GLuint id = glCreateShader(type);
    glShaderSource(id, 1, &src, NULL);
    glCompileShader(id);
    GLint ok = 0;
    glGetShaderiv(id, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[512];
        glGetShaderInfoLog(id, sizeof(log), NULL, log);
        fprintf(stderr, "Shader compile error: %s\n", log);
        return 0;
    }
    return id;
}

// Compute normal matrix (transpose of inverse of upper-left 3x3 of model).
// Model is stored column-major. With scale Z=0, det=0, inv_det=Inf -> NaN values.
static void compute_normal_matrix(const GLfloat m[16], GLfloat nm[9])
{
    float a = m[0], b = m[4], c = m[8];
    float d = m[1], e = m[5], f = m[9];
    float g = m[2], h = m[6], k = m[10];

    float det = a*(e*k - f*h) - b*(d*k - f*g) + c*(d*h - e*g);
    // With scale Z=0: k=0, det=0, inv_det=Inf -> Inf * 0 = NaN
    float inv_det = 1.0f / det;

    // Cofactor matrix (transposed = inverse * det), column-major
    nm[0] = (e*k - f*h) * inv_det;
    nm[1] = (c*h - b*k) * inv_det;
    nm[2] = (b*f - c*e) * inv_det;

    nm[3] = (f*g - d*k) * inv_det;
    nm[4] = (a*k - c*g) * inv_det;
    nm[5] = (c*d - a*f) * inv_det;

    nm[6] = (d*h - e*g) * inv_det;
    nm[7] = (b*g - a*h) * inv_det;
    nm[8] = (a*e - b*d) * inv_det;
}

int main(void)
{
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "Cannot open X display\n"); return 1; }

    int attrs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo *vi = glXChooseVisual(dpy, 0, attrs);
    if (!vi) { fprintf(stderr, "No suitable GLX visual\n"); XCloseDisplay(dpy); return 1; }

    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    memset(&swa, 0, sizeof(swa));
    swa.colormap   = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 400, 300, 0, vi->depth,
                               InputOutput, vi->visual, CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    XStoreName(dpy, win, "E2: NaN Propagation");

    GLXContext glc = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    if (!glc) { fprintf(stderr, "Cannot create GL context\n"); return 1; }
    glXMakeCurrent(dpy, win, glc);

    LOAD_PROC(PFNGLCREATESHADERPROC,          glCreateShader)
    LOAD_PROC(PFNGLSHADERSOURCEPROC,          glShaderSource)
    LOAD_PROC(PFNGLCOMPILESHADERPROC,         glCompileShader)
    LOAD_PROC(PFNGLGETSHADERIVPROC,           glGetShaderiv)
    LOAD_PROC(PFNGLGETSHADERINFOLOGPROC,      glGetShaderInfoLog)
    LOAD_PROC(PFNGLCREATEPROGRAMPROC,         glCreateProgram)
    LOAD_PROC(PFNGLATTACHSHADERPROC,          glAttachShader)
    LOAD_PROC(PFNGLLINKPROGRAMPROC,           glLinkProgram)
    LOAD_PROC(PFNGLGETPROGRAMIVPROC,          glGetProgramiv)
    LOAD_PROC(PFNGLGETPROGRAMINFOLOGPROC,     glGetProgramInfoLog)
    LOAD_PROC(PFNGLUSEPROGRAMPROC,            glUseProgram)
    LOAD_PROC(PFNGLGETUNIFORMLOCATIONPROC,    glGetUniformLocation)
    LOAD_PROC(PFNGLUNIFORM3FPROC,             glUniform3f)
    LOAD_PROC(PFNGLUNIFORMMATRIX3FVPROC,      glUniformMatrix3fv)
    LOAD_PROC(PFNGLGENBUFFERSPROC,            glGenBuffers)
    LOAD_PROC(PFNGLBINDBUFFERPROC,            glBindBuffer)
    LOAD_PROC(PFNGLBUFFERDATAPROC,            glBufferData)
    LOAD_PROC(PFNGLGENVERTEXARRAYSPROC,       glGenVertexArrays)
    LOAD_PROC(PFNGLBINDVERTEXARRAYPROC,       glBindVertexArray)
    LOAD_PROC(PFNGLENABLEVERTEXATTRIBARRAYPROC, glEnableVertexAttribArray)
    LOAD_PROC(PFNGLVERTEXATTRIBPOINTERPROC,   glVertexAttribPointer)
    LOAD_PROC(PFNGLGETATTRIBLOCATIONPROC,     glGetAttribLocation)
    LOAD_PROC(PFNGLDELETESHADERPROC,          glDeleteShader)
    LOAD_PROC(PFNGLDELETEPROGRAMPROC,         glDeleteProgram)
    LOAD_PROC(PFNGLDELETEBUFFERSPROC,         glDeleteBuffers)
    LOAD_PROC(PFNGLDELETEVERTEXARRAYSPROC,    glDeleteVertexArrays)

    glViewport(0, 0, 400, 300);
    glEnable(GL_DEPTH_TEST);

    GLuint vs = compile_shader(glCreateShader, glShaderSource, glCompileShader,
                               glGetShaderiv, glGetShaderInfoLog,
                               GL_VERTEX_SHADER, vert_src);
    GLuint fs = compile_shader(glCreateShader, glShaderSource, glCompileShader,
                               glGetShaderiv, glGetShaderInfoLog,
                               GL_FRAGMENT_SHADER, frag_src);
    if (!vs || !fs) return 1;

    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);
    {
        GLint ok = 0;
        glGetProgramiv(prog, GL_LINK_STATUS, &ok);
        if (!ok) {
            char log[512];
            glGetProgramInfoLog(prog, sizeof(log), NULL, log);
            fprintf(stderr, "Program link error: %s\n", log);
            return 1;
        }
    }
    glDeleteShader(vs);
    glDeleteShader(fs);

    GLint locNM        = glGetUniformLocation(prog, "uNormalMatrix");
    GLint locBaseColor = glGetUniformLocation(prog, "uBaseColor");
    GLint locPos       = glGetAttribLocation(prog,  "aPos");
    GLint locNormal    = glGetAttribLocation(prog,  "aNormal");

    // Front-facing quad at z=0 with +Z normals, spanning most of the viewport
    // 6 vertices (2 triangles), interleaved pos(3) + normal(3)
    static const GLfloat verts[] = {
        // pos                 normal (+Z)
        -0.7f, -0.7f, 0.0f,   0.0f, 0.0f, 1.0f,
         0.7f, -0.7f, 0.0f,   0.0f, 0.0f, 1.0f,
         0.7f,  0.7f, 0.0f,   0.0f, 0.0f, 1.0f,
        -0.7f, -0.7f, 0.0f,   0.0f, 0.0f, 1.0f,
         0.7f,  0.7f, 0.0f,   0.0f, 0.0f, 1.0f,
        -0.7f,  0.7f, 0.0f,   0.0f, 0.0f, 1.0f,
    };

    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);

    GLsizei stride = 6 * sizeof(GLfloat);
    glEnableVertexAttribArray((GLuint)locPos);
    glVertexAttribPointer((GLuint)locPos, 3, GL_FLOAT, GL_FALSE, stride, (void *)0);
    glEnableVertexAttribArray((GLuint)locNormal);
    glVertexAttribPointer((GLuint)locNormal, 3, GL_FLOAT, GL_FALSE, stride,
                          (void *)(3 * sizeof(GLfloat)));

    // BUG: model matrix with scale(1, 1, 0) -- Z scale = 0 makes matrix singular.
    // Normal matrix = transpose(inverse(model)) -> Inf/NaN in Z-related entries.
    // Column-major identity with m[10] = 0
    GLfloat model[16];
    memset(model, 0, sizeof(model));
    model[0] = 1.0f;
    model[5] = 1.0f;
    model[10] = 0.0f;  // <-- BUG: Z scale = 0 (should be 1.0f)
    model[15] = 1.0f;

    GLfloat nm[9];
    compute_normal_matrix(model, nm);

    for (int frame = 0; frame < 5; frame++) {
        glClearColor(0.1f, 0.1f, 0.3f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        glUseProgram(prog);
        // Base color: warm orange -- should be visible if lighting worked
        glUniform3f(locBaseColor, 0.9f, 0.6f, 0.2f);
        // Upload normal matrix with Inf/NaN due to singular model
        glUniformMatrix3fv(locNM, 1, GL_FALSE, nm);

        glBindVertexArray(vao);
        glDrawArrays(GL_TRIANGLES, 0, 6);

        glXSwapBuffers(dpy, win);
    }

    glDeleteVertexArrays(1, &vao);
    glDeleteBuffers(1, &vbo);
    glDeleteProgram(prog);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, glc);
    XDestroyWindow(dpy, win);
    XFreeColormap(dpy, swa.colormap);
    XFree(vi);
    XCloseDisplay(dpy);

    printf("e2_nan_propagation: completed 5 frames\n");
    return 0;
}
