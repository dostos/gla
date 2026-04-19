// SOURCE: https://stackoverflow.com/questions/13221328/artifacts-when-rendering-both-sides-of-a-transparent-object-with-three-js
//
// Reproduces the "double-sided transparent sphere" artifact pattern from the
// linked StackOverflow question. We render ONE draw call of a tessellated
// sphere with:
//   - blending enabled (SrcAlpha, OneMinusSrcAlpha)
//   - depth test enabled, depth writes enabled
//   - face culling disabled (both sides rendered in a single pass)
// The triangles are emitted in geometry-construction order, not sorted by
// depth. Back-facing triangles that happen to be drawn before front-facing
// ones write depth that later occludes correctly-composited front fragments,
// producing the characteristic "sphere wireframe artifacts" visible through
// the transparent surface.

#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

typedef GLuint (*glCreateShader_t)(GLenum);
typedef void   (*glShaderSource_t)(GLuint, GLsizei, const char* const*, const GLint*);
typedef void   (*glCompileShader_t)(GLuint);
typedef GLuint (*glCreateProgram_t)(void);
typedef void   (*glAttachShader_t)(GLuint, GLuint);
typedef void   (*glLinkProgram_t)(GLuint);
typedef void   (*glUseProgram_t)(GLuint);
typedef void   (*glGenBuffers_t)(GLsizei, GLuint*);
typedef void   (*glBindBuffer_t)(GLenum, GLuint);
typedef void   (*glBufferData_t)(GLenum, long, const void*, GLenum);
typedef void   (*glGenVertexArrays_t)(GLsizei, GLuint*);
typedef void   (*glBindVertexArray_t)(GLuint);
typedef void   (*glVertexAttribPointer_t)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void   (*glEnableVertexAttribArray_t)(GLuint);
typedef GLint  (*glGetUniformLocation_t)(GLuint, const char*);
typedef void   (*glUniformMatrix4fv_t)(GLint, GLsizei, GLboolean, const GLfloat*);
typedef void   (*glUniform4fv_t)(GLint, GLsizei, const GLfloat*);

#define GL_ARRAY_BUFFER         0x8892
#define GL_ELEMENT_ARRAY_BUFFER 0x8893
#define GL_STATIC_DRAW          0x88E4
#define GL_VERTEX_SHADER        0x8B31
#define GL_FRAGMENT_SHADER      0x8B30

static glCreateShader_t glCreateShader_;
static glShaderSource_t glShaderSource_;
static glCompileShader_t glCompileShader_;
static glCreateProgram_t glCreateProgram_;
static glAttachShader_t glAttachShader_;
static glLinkProgram_t glLinkProgram_;
static glUseProgram_t glUseProgram_;
static glGenBuffers_t glGenBuffers_;
static glBindBuffer_t glBindBuffer_;
static glBufferData_t glBufferData_;
static glGenVertexArrays_t glGenVertexArrays_;
static glBindVertexArray_t glBindVertexArray_;
static glVertexAttribPointer_t glVertexAttribPointer_;
static glEnableVertexAttribArray_t glEnableVertexAttribArray_;
static glGetUniformLocation_t glGetUniformLocation_;
static glUniformMatrix4fv_t glUniformMatrix4fv_;
static glUniform4fv_t glUniform4fv_;

static void load_gl(void) {
    glCreateShader_  = (glCreateShader_t)glXGetProcAddress((const GLubyte*)"glCreateShader");
    glShaderSource_  = (glShaderSource_t)glXGetProcAddress((const GLubyte*)"glShaderSource");
    glCompileShader_ = (glCompileShader_t)glXGetProcAddress((const GLubyte*)"glCompileShader");
    glCreateProgram_ = (glCreateProgram_t)glXGetProcAddress((const GLubyte*)"glCreateProgram");
    glAttachShader_  = (glAttachShader_t)glXGetProcAddress((const GLubyte*)"glAttachShader");
    glLinkProgram_   = (glLinkProgram_t)glXGetProcAddress((const GLubyte*)"glLinkProgram");
    glUseProgram_    = (glUseProgram_t)glXGetProcAddress((const GLubyte*)"glUseProgram");
    glGenBuffers_    = (glGenBuffers_t)glXGetProcAddress((const GLubyte*)"glGenBuffers");
    glBindBuffer_    = (glBindBuffer_t)glXGetProcAddress((const GLubyte*)"glBindBuffer");
    glBufferData_    = (glBufferData_t)glXGetProcAddress((const GLubyte*)"glBufferData");
    glGenVertexArrays_ = (glGenVertexArrays_t)glXGetProcAddress((const GLubyte*)"glGenVertexArrays");
    glBindVertexArray_ = (glBindVertexArray_t)glXGetProcAddress((const GLubyte*)"glBindVertexArray");
    glVertexAttribPointer_ = (glVertexAttribPointer_t)glXGetProcAddress((const GLubyte*)"glVertexAttribPointer");
    glEnableVertexAttribArray_ = (glEnableVertexAttribArray_t)glXGetProcAddress((const GLubyte*)"glEnableVertexAttribArray");
    glGetUniformLocation_ = (glGetUniformLocation_t)glXGetProcAddress((const GLubyte*)"glGetUniformLocation");
    glUniformMatrix4fv_ = (glUniformMatrix4fv_t)glXGetProcAddress((const GLubyte*)"glUniformMatrix4fv");
    glUniform4fv_       = (glUniform4fv_t)glXGetProcAddress((const GLubyte*)"glUniform4fv");
}

static const char* VS =
    "#version 330 core\n"
    "layout(location=0) in vec3 aPos;\n"
    "uniform mat4 uMVP;\n"
    "void main() { gl_Position = uMVP * vec4(aPos, 1.0); }\n";

static const char* FS =
    "#version 330 core\n"
    "out vec4 frag;\n"
    "uniform vec4 uColor;\n"
    "void main() { frag = uColor; }\n";

static void make_sphere(float r, int lat, int lon, float** verts, int* nv, unsigned** idx, int* ni) {
    *nv = (lat + 1) * (lon + 1);
    *verts = (float*)malloc(sizeof(float) * 3 * (*nv));
    int vi = 0;
    for (int i = 0; i <= lat; i++) {
        float th = (float)i / lat * (float)M_PI;
        for (int j = 0; j <= lon; j++) {
            float ph = (float)j / lon * 2.0f * (float)M_PI;
            (*verts)[vi++] = r * sinf(th) * cosf(ph);
            (*verts)[vi++] = r * cosf(th);
            (*verts)[vi++] = r * sinf(th) * sinf(ph);
        }
    }
    *ni = lat * lon * 6;
    *idx = (unsigned*)malloc(sizeof(unsigned) * (*ni));
    int ii = 0;
    for (int i = 0; i < lat; i++) {
        for (int j = 0; j < lon; j++) {
            unsigned a = i * (lon + 1) + j;
            unsigned b = a + lon + 1;
            (*idx)[ii++] = a; (*idx)[ii++] = b; (*idx)[ii++] = a + 1;
            (*idx)[ii++] = b; (*idx)[ii++] = b + 1; (*idx)[ii++] = a + 1;
        }
    }
}

static void perspective(float* m, float fov, float aspect, float n, float f) {
    float t = 1.0f / tanf(fov * 0.5f);
    memset(m, 0, 16 * sizeof(float));
    m[0] = t / aspect; m[5] = t; m[10] = (f + n) / (n - f);
    m[11] = -1.0f; m[14] = 2.0f * f * n / (n - f);
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    int attr[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, attr);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 512, 512, 0, vi->depth,
                               InputOutput, vi->visual, CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);
    load_gl();

    GLuint vs = glCreateShader_(GL_VERTEX_SHADER);
    glShaderSource_(vs, 1, &VS, NULL); glCompileShader_(vs);
    GLuint fs = glCreateShader_(GL_FRAGMENT_SHADER);
    glShaderSource_(fs, 1, &FS, NULL); glCompileShader_(fs);
    GLuint prog = glCreateProgram_();
    glAttachShader_(prog, vs); glAttachShader_(prog, fs); glLinkProgram_(prog);
    glUseProgram_(prog);

    float* verts; unsigned* idx; int nv, ni;
    make_sphere(0.7f, 24, 32, &verts, &nv, &idx, &ni);

    GLuint vao, vbo, ebo;
    glGenVertexArrays_(1, &vao); glBindVertexArray_(vao);
    glGenBuffers_(1, &vbo); glBindBuffer_(GL_ARRAY_BUFFER, vbo);
    glBufferData_(GL_ARRAY_BUFFER, (long)(sizeof(float) * 3 * nv), verts, GL_STATIC_DRAW);
    glGenBuffers_(1, &ebo); glBindBuffer_(GL_ELEMENT_ARRAY_BUFFER, ebo);
    glBufferData_(GL_ELEMENT_ARRAY_BUFFER, (long)(sizeof(unsigned) * ni), idx, GL_STATIC_DRAW);
    glVertexAttribPointer_(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), (void*)0);
    glEnableVertexAttribArray_(0);

    float mvp[16];
    perspective(mvp, 1.2f, 1.0f, 0.1f, 10.0f);
    mvp[14] -= 2.5f; // translate -Z
    GLint uMVP = glGetUniformLocation_(prog, "uMVP");
    GLint uCol = glGetUniformLocation_(prog, "uColor");
    glUniformMatrix4fv_(uMVP, 1, GL_FALSE, mvp);
    float color[4] = { 0.2f, 0.7f, 1.0f, 0.35f };
    glUniform4fv_(uCol, 1, color);

    glViewport(0, 0, 512, 512);
    glClearColor(0.1f, 0.1f, 0.1f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    // THE BUG PATTERN: enable blending, keep depth-write on, disable culling.
    // A single draw call emits both front- and back-facing triangles in
    // construction order, so depth writes cause self-occlusion artifacts.
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    glDisable(GL_CULL_FACE);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);

    glDrawElements(GL_TRIANGLES, ni, GL_UNSIGNED_INT, 0);
    glXSwapBuffers(dpy, win);

    free(verts); free(idx);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}