// tests/eval/e4_double_negation_cull.c
//
// E4: Double-Negation Culling
//
// Draws 2 quads with face culling enabled.
//
// Setup:
//   - glEnable(GL_CULL_FACE) + glCullFace(GL_BACK) + glFrontFace(GL_CW)
//   - Both quads have CCW-wound vertices in NDC
//
// Quad A (left): has a negative X scale in its model matrix (mirror).
//   - Negative scale flips winding: CCW -> CW in clip space.
//   - glFrontFace(GL_CW) says CW is front, so Quad A IS rendered (two errors cancel).
//
// Quad B (right): no model matrix scaling (identity).
//   - Vertices are CCW in NDC, but glFrontFace(GL_CW) says CW is front.
//   - CCW quad is treated as back-facing -> CULLED (invisible).
//
// Bug: The double-negation makes Quad A accidentally visible, while Quad B
//      (correctly-wound without any mirror) is incorrectly culled.
//
// Expected (if bug were fixed with GL_CCW front face):
//   - Both quads visible, Quad A green, Quad B magenta
//
// Actual (with bug):
//   - Quad A visible (green) -- correct-looking but for wrong reasons
//   - Quad B invisible -- culled because CCW is treated as back-facing
//
// GLA reveals: pipeline state shows cull_enabled=true, front_face=GL_CW.
// Pixel check: left half shows green quad, right half shows only background.
//
// Clear color: dark green-tinted (0.05, 0.15, 0.05, 1.0) -- 400x300 window, 5 frames.

#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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
typedef void   (*PFNGLUNIFORM4FPROC)(GLint, GLfloat, GLfloat, GLfloat, GLfloat);
typedef void   (*PFNGLUNIFORMMATRIX4FVPROC)(GLint, GLsizei, GLboolean, const GLfloat *);
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

// Vertex shader with model matrix for winding manipulation
static const char *vert_src =
    "#version 120\n"
    "attribute vec2 aPos;\n"
    "uniform mat4 uModel;\n"
    "void main() { gl_Position = uModel * vec4(aPos, 0.0, 1.0); }\n";

// Fragment shader: solid color via uniform
static const char *frag_src =
    "#version 120\n"
    "uniform vec4 uColor;\n"
    "void main() { gl_FragColor = uColor; }\n";

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
    XStoreName(dpy, win, "E4: Double-Negation Culling");

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
    LOAD_PROC(PFNGLUNIFORM4FPROC,             glUniform4f)
    LOAD_PROC(PFNGLUNIFORMMATRIX4FVPROC,      glUniformMatrix4fv)
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

    // Enable culling
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    // BUG: GL_CW front face with a mirrored quad creates a double-negation.
    // A CCW quad under GL_CW front face is BACK -> culled.
    // A CCW quad mirrored (-X scale) becomes CW -> front -> visible.
    // But the non-mirrored quad (Quad B) is incorrectly culled.
    glFrontFace(GL_CW);  // <-- BUG (should be GL_CCW for standard CCW-wound quads)

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

    GLint locModel = glGetUniformLocation(prog, "uModel");
    GLint locColor = glGetUniformLocation(prog, "uColor");
    GLint locPos   = glGetAttribLocation(prog,  "aPos");

    // A single quad geometry centered at origin, spanning [-0.8,0.8]x[-0.8,0.8]
    // Vertices wound CCW (standard): BL, BR, TR, BL, TR, TL
    static const GLfloat quad_verts[] = {
        -0.8f, -0.8f,
         0.8f, -0.8f,
         0.8f,  0.8f,
        -0.8f, -0.8f,
         0.8f,  0.8f,
        -0.8f,  0.8f,
    };

    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad_verts), quad_verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray((GLuint)locPos);
    glVertexAttribPointer((GLuint)locPos, 2, GL_FLOAT, GL_FALSE,
                          2 * sizeof(GLfloat), (void *)0);

    // Model A: translate left and apply negative X scale (mirror) -- column-major identity
    // Scale X by -1 to mirror: flips CCW -> CW in clip space.
    // With GL_CW as front, mirrored CW quad IS front-facing -> rendered.
    GLfloat model_a[16];
    memset(model_a, 0, sizeof(model_a));
    model_a[0]  = -0.45f;  // negative X scale: mirror + half-width to fit left half
    model_a[5]  =  0.9f;
    model_a[10] =  1.0f;
    model_a[12] = -0.5f;   // translate left
    model_a[15] =  1.0f;

    // Model B: translate right, no mirroring (positive X scale).
    // CCW vertices in NDC with GL_CW front face -> treated as back -> CULLED.
    GLfloat model_b[16];
    memset(model_b, 0, sizeof(model_b));
    model_b[0]  =  0.45f;  // positive X scale: no mirror
    model_b[5]  =  0.9f;
    model_b[10] =  1.0f;
    model_b[12] =  0.5f;   // translate right
    model_b[15] =  1.0f;

    for (int frame = 0; frame < 5; frame++) {
        glClearColor(0.05f, 0.15f, 0.05f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        glUseProgram(prog);
        glBindVertexArray(vao);

        // Quad A (left): mirrored (-X scale) -> CW in clip space -> front face visible
        // Two bugs cancel: neg scale makes it CW, GL_CW says CW is front -> renders
        glUniformMatrix4fv(locModel, 1, GL_FALSE, model_a);
        glUniform4f(locColor, 0.1f, 0.9f, 0.2f, 1.0f);  // green
        glDrawArrays(GL_TRIANGLES, 0, 6);

        // Quad B (right): not mirrored, CCW in NDC.
        // GL_CW front face: CCW is treated as back-facing -> CULLED (invisible).
        glUniformMatrix4fv(locModel, 1, GL_FALSE, model_b);
        glUniform4f(locColor, 0.9f, 0.1f, 0.9f, 1.0f);  // magenta
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

    printf("e4_double_negation_cull: completed 5 frames\n");
    return 0;
}
