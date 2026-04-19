// SOURCE: https://github.com/godotengine/godot/issues/114606
// Pattern: a shader declares "uniform samplerCube radiance" intended to live
// on texture unit A, but the engine binds the cubemap on texture unit B.
// glUniform1i is never called (or is called with the wrong unit), so the
// sampler defaults to unit 0 / wrong unit, and texture(RADIANCE, dir) returns
// black even though a perfectly valid red cubemap is bound elsewhere.

#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef void (*PFNGLGENVERTEXARRAYSPROC)(GLsizei, GLuint*);
typedef void (*PFNGLBINDVERTEXARRAYPROC)(GLuint);
typedef void (*PFNGLGENBUFFERSPROC)(GLsizei, GLuint*);
typedef void (*PFNGLBINDBUFFERPROC)(GLenum, GLuint);
typedef void (*PFNGLBUFFERDATAPROC)(GLenum, long, const void*, GLenum);
typedef GLuint (*PFNGLCREATESHADERPROC)(GLenum);
typedef void (*PFNGLSHADERSOURCEPROC)(GLuint, GLsizei, const char* const*, const GLint*);
typedef void (*PFNGLCOMPILESHADERPROC)(GLuint);
typedef GLuint (*PFNGLCREATEPROGRAMPROC)(void);
typedef void (*PFNGLATTACHSHADERPROC)(GLuint, GLuint);
typedef void (*PFNGLLINKPROGRAMPROC)(GLuint);
typedef void (*PFNGLUSEPROGRAMPROC)(GLuint);
typedef GLint (*PFNGLGETUNIFORMLOCATIONPROC)(GLuint, const char*);
typedef void (*PFNGLUNIFORM1IPROC)(GLint, GLint);
typedef void (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef void (*PFNGLACTIVETEXTUREPROC)(GLenum);
typedef void (*PFNGLGETSHADERIVPROC)(GLuint, GLenum, GLint*);
typedef void (*PFNGLGETSHADERINFOLOGPROC)(GLuint, GLsizei, GLsizei*, char*);
typedef GLXContext (*PFNGLXCREATECTXATTRIBSARBPROC)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

#define LOAD(T, n) T n = (T)glXGetProcAddressARB((const GLubyte*)#n)

static const char* VS =
    "#version 330 core\n"
    "layout(location=0) in vec2 p;\n"
    "out vec3 dir;\n"
    "void main(){ gl_Position=vec4(p,0,1); dir=vec3(p,1.0); }\n";

// The shader expects RADIANCE on texture unit 0 by GLSL default; we will
// (mis)configure the uniform to point at unit MAX_IMAGE_UNITS-1 (an empty
// unit), mirroring the Godot //texunit:-1 vs glActiveTexture(... -2) split.
static const char* FS =
    "#version 330 core\n"
    "in vec3 dir;\n"
    "uniform samplerCube RADIANCE;\n"
    "out vec4 frag;\n"
    "void main(){ frag = vec4(texture(RADIANCE, normalize(dir)).rgb, 1.0); }\n";

static GLuint mk_shader(GLenum kind, const char* src,
                        PFNGLCREATESHADERPROC glCreateShader,
                        PFNGLSHADERSOURCEPROC glShaderSource,
                        PFNGLCOMPILESHADERPROC glCompileShader,
                        PFNGLGETSHADERIVPROC glGetShaderiv,
                        PFNGLGETSHADERINFOLOGPROC glGetShaderInfoLog) {
    GLuint s = glCreateShader(kind);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok = 0;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) { char log[1024]; glGetShaderInfoLog(s, 1024, NULL, log); fprintf(stderr, "shader: %s\n", log); }
    return s;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) return 1;
    int attribs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, attribs);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa; swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0,0, 256,256, 0, vi->depth, InputOutput,
                               vi->visual, CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, win);

    int fbc_count;
    int fbattr[] = { GLX_DOUBLEBUFFER, True, GLX_RED_SIZE, 8, GLX_DEPTH_SIZE, 24, None };
    GLXFBConfig* fbc = glXChooseFBConfig(dpy, DefaultScreen(dpy), fbattr, &fbc_count);
    LOAD(PFNGLXCREATECTXATTRIBSARBPROC, glXCreateContextAttribsARB);
    int ctx_attribs[] = { GLX_CONTEXT_MAJOR_VERSION_ARB, 3, GLX_CONTEXT_MINOR_VERSION_ARB, 3,
                          GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB, None };
    GLXContext ctx = glXCreateContextAttribsARB(dpy, fbc[0], NULL, True, ctx_attribs);
    glXMakeCurrent(dpy, win, ctx);

    LOAD(PFNGLGENVERTEXARRAYSPROC, glGenVertexArrays);
    LOAD(PFNGLBINDVERTEXARRAYPROC, glBindVertexArray);
    LOAD(PFNGLGENBUFFERSPROC, glGenBuffers);
    LOAD(PFNGLBINDBUFFERPROC, glBindBuffer);
    LOAD(PFNGLBUFFERDATAPROC, glBufferData);
    LOAD(PFNGLCREATESHADERPROC, glCreateShader);
    LOAD(PFNGLSHADERSOURCEPROC, glShaderSource);
    LOAD(PFNGLCOMPILESHADERPROC, glCompileShader);
    LOAD(PFNGLCREATEPROGRAMPROC, glCreateProgram);
    LOAD(PFNGLATTACHSHADERPROC, glAttachShader);
    LOAD(PFNGLLINKPROGRAMPROC, glLinkProgram);
    LOAD(PFNGLUSEPROGRAMPROC, glUseProgram);
    LOAD(PFNGLGETUNIFORMLOCATIONPROC, glGetUniformLocation);
    LOAD(PFNGLUNIFORM1IPROC, glUniform1i);
    LOAD(PFNGLVERTEXATTRIBPOINTERPROC, glVertexAttribPointer);
    LOAD(PFNGLENABLEVERTEXATTRIBARRAYPROC, glEnableVertexAttribArray);
    LOAD(PFNGLACTIVETEXTUREPROC, glActiveTexture);
    LOAD(PFNGLGETSHADERIVPROC, glGetShaderiv);
    LOAD(PFNGLGETSHADERINFOLOGPROC, glGetShaderInfoLog);

    GLuint vao; glGenVertexArrays(1, &vao); glBindVertexArray(vao);
    float quad[] = { -1,-1,  1,-1,  -1,1,  1,1 };
    GLuint vbo; glGenBuffers(1, &vbo); glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL);
    glEnableVertexAttribArray(0);

    GLuint vs = mk_shader(GL_VERTEX_SHADER,   VS, glCreateShader, glShaderSource, glCompileShader, glGetShaderiv, glGetShaderInfoLog);
    GLuint fs = mk_shader(GL_FRAGMENT_SHADER, FS, glCreateShader, glShaderSource, glCompileShader, glGetShaderiv, glGetShaderInfoLog);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs); glAttachShader(prog, fs); glLinkProgram(prog);
    glUseProgram(prog);

    // Build a solid-red cubemap.
    GLuint cube; glGenTextures(1, &cube);
    GLint max_units = 0; glGetIntegerv(GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS, &max_units);
    GLint bind_unit = max_units - 2;   // engine actually binds here
    glActiveTexture(GL_TEXTURE0 + bind_unit);
    glBindTexture(GL_TEXTURE_CUBE_MAP, cube);
    unsigned char red[] = { 255, 0, 0, 255 };
    for (int f = 0; f < 6; f++) {
        glTexImage2D(GL_TEXTURE_CUBE_MAP_POSITIVE_X + f, 0, GL_RGBA, 1, 1, 0,
                     GL_RGBA, GL_UNSIGNED_BYTE, red);
    }
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MAG_FILTER, GL_LINEAR);

    // The "shader declares texunit:-1" bug: tell the sampler the cubemap lives
    // on a different unit than where we actually bound it.  Here we pick
    // max_units-1 (which has nothing bound), modeling the off-by-one in Godot.
    GLint shader_unit = max_units - 1;
    glUniform1i(glGetUniformLocation(prog, "RADIANCE"), shader_unit);

    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    glXSwapBuffers(dpy, win);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}