// SOURCE: https://github.com/godotengine/godot/issues/115075
// Minimal repro of the pattern: a fragment shader declares
// `uniform sampler2D holes[3]` but only some array slots have an
// explicit glUniform1i() binding. The unassigned slots default to
// texture image unit 0, causing them to silently sample whatever
// texture is bound to unit 0 instead of raising a shader error.
// Godot's upstream bug exhibits a related symptom: unassigned
// sampler array entries appear to re-use a sibling texture rather
// than produce an error.

#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef GLuint (*PFNGLCREATESHADERPROC)(GLenum);
typedef void (*PFNGLSHADERSOURCEPROC)(GLuint, GLsizei, const char * const *, const GLint *);
typedef void (*PFNGLCOMPILESHADERPROC)(GLuint);
typedef GLuint (*PFNGLCREATEPROGRAMPROC)(void);
typedef void (*PFNGLATTACHSHADERPROC)(GLuint, GLuint);
typedef void (*PFNGLLINKPROGRAMPROC)(GLuint);
typedef void (*PFNGLUSEPROGRAMPROC)(GLuint);
typedef GLint (*PFNGLGETUNIFORMLOCATIONPROC)(GLuint, const char *);
typedef void (*PFNGLUNIFORM1IPROC)(GLint, GLint);
typedef void (*PFNGLGENVERTEXARRAYSPROC)(GLsizei, GLuint *);
typedef void (*PFNGLBINDVERTEXARRAYPROC)(GLuint);
typedef void (*PFNGLGENBUFFERSPROC)(GLsizei, GLuint *);
typedef void (*PFNGLBINDBUFFERPROC)(GLenum, GLuint);
typedef void (*PFNGLBUFFERDATAPROC)(GLenum, GLsizeiptr, const void *, GLenum);
typedef void (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void *);
typedef void (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef void (*PFNGLACTIVETEXTUREPROC)(GLenum);

#define GL_ARRAY_BUFFER 0x8892
#define GL_STATIC_DRAW 0x88E4
#define GL_VERTEX_SHADER 0x8B31
#define GL_FRAGMENT_SHADER 0x8B30
#define GL_TEXTURE0 0x84C0
#define GL_CLAMP_TO_EDGE 0x812F

static void *gl(const char *n) {
    return (void *)glXGetProcAddressARB((const GLubyte *)n);
}

static const char *VS =
    "#version 330 core\n"
    "layout(location=0) in vec2 p;\n"
    "out vec2 uv;\n"
    "void main(){ uv = p*0.5+0.5; gl_Position = vec4(p,0,1); }\n";

static const char *FS =
    "#version 330 core\n"
    "in vec2 uv; out vec4 frag;\n"
    "uniform sampler2D holes[3];\n"
    "void main(){\n"
    "  vec3 a = texture(holes[0], uv).rgb;\n"
    "  vec3 b = texture(holes[1], uv).rgb;\n"
    "  vec3 c = texture(holes[2], uv).rgb;\n"
    "  if (uv.x < 0.333)      frag = vec4(a,1);\n"
    "  else if (uv.x < 0.666) frag = vec4(b,1);\n"
    "  else                   frag = vec4(c,1);\n"
    "}\n";

int main(void) {
    Display *d = XOpenDisplay(NULL);
    if (!d) return 1;
    int attribs[] = {GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None};
    XVisualInfo *vi = glXChooseVisual(d, 0, attribs);
    Window root = DefaultRootWindow(d);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(d, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window w = XCreateWindow(d, root, 0, 0, 256, 256, 0, vi->depth,
                             InputOutput, vi->visual,
                             CWColormap | CWEventMask, &swa);
    XMapWindow(d, w);
    GLXContext ctx = glXCreateContext(d, vi, NULL, GL_TRUE);
    glXMakeCurrent(d, w, ctx);

    PFNGLCREATESHADERPROC glCreateShader = gl("glCreateShader");
    PFNGLSHADERSOURCEPROC glShaderSource = gl("glShaderSource");
    PFNGLCOMPILESHADERPROC glCompileShader = gl("glCompileShader");
    PFNGLCREATEPROGRAMPROC glCreateProgram = gl("glCreateProgram");
    PFNGLATTACHSHADERPROC glAttachShader = gl("glAttachShader");
    PFNGLLINKPROGRAMPROC glLinkProgram = gl("glLinkProgram");
    PFNGLUSEPROGRAMPROC glUseProgram = gl("glUseProgram");
    PFNGLGETUNIFORMLOCATIONPROC glGetUniformLocation = gl("glGetUniformLocation");
    PFNGLUNIFORM1IPROC glUniform1i = gl("glUniform1i");
    PFNGLGENVERTEXARRAYSPROC glGenVertexArrays = gl("glGenVertexArrays");
    PFNGLBINDVERTEXARRAYPROC glBindVertexArray = gl("glBindVertexArray");
    PFNGLGENBUFFERSPROC glGenBuffers = gl("glGenBuffers");
    PFNGLBINDBUFFERPROC glBindBuffer = gl("glBindBuffer");
    PFNGLBUFFERDATAPROC glBufferData = gl("glBufferData");
    PFNGLVERTEXATTRIBPOINTERPROC glVertexAttribPointer = gl("glVertexAttribPointer");
    PFNGLENABLEVERTEXATTRIBARRAYPROC glEnableVertexAttribArray = gl("glEnableVertexAttribArray");
    PFNGLACTIVETEXTUREPROC glActiveTexture = gl("glActiveTexture");

    GLuint vs = glCreateShader(GL_VERTEX_SHADER);
    glShaderSource(vs, 1, &VS, NULL); glCompileShader(vs);
    GLuint fs = glCreateShader(GL_FRAGMENT_SHADER);
    glShaderSource(fs, 1, &FS, NULL); glCompileShader(fs);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs); glAttachShader(prog, fs); glLinkProgram(prog);

    GLuint vao, vbo;
    glGenVertexArrays(1, &vao); glBindVertexArray(vao);
    glGenBuffers(1, &vbo); glBindBuffer(GL_ARRAY_BUFFER, vbo);
    float quad[] = {-1,-1, 1,-1, -1,1, 1,1};
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, 0);
    glEnableVertexAttribArray(0);

    GLuint tex[3];
    glGenTextures(3, tex);
    unsigned char red[4]   = {255, 0,   0,   255};
    unsigned char green[4] = {0,   255, 0,   255};
    unsigned char blue[4]  = {0,   0,   255, 255};
    unsigned char *pix[3] = {red, green, blue};
    for (int i = 0; i < 3; i++) {
        glActiveTexture(GL_TEXTURE0 + i);
        glBindTexture(GL_TEXTURE_2D, tex[i]);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA,
                     GL_UNSIGNED_BYTE, pix[i]);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    }

    glUseProgram(prog);
    /* Intentionally assign only holes[0] and holes[1]; holes[2] is
     * left at its default uniform value of 0, so the shader samples
     * texture unit 0 (red) for that slot instead of unit 2 (blue). */
    glUniform1i(glGetUniformLocation(prog, "holes[0]"), 0);
    glUniform1i(glGetUniformLocation(prog, "holes[1]"), 1);
    /* holes[2] deliberately NOT assigned */

    glViewport(0, 0, 256, 256);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    glXSwapBuffers(d, w);

    glXMakeCurrent(d, None, NULL);
    glXDestroyContext(d, ctx);
    XCloseDisplay(d);
    return 0;
}