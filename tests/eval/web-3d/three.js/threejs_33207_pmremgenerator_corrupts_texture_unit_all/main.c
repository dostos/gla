// SOURCE: https://github.com/mrdoob/three.js/issues/33207

#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <GL/glxext.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char* VS =
    "#version 330 core\n"
    "void main() {\n"
    "  vec2 p = vec2(((gl_VertexID & 1) == 0) ? -1.0 :  1.0,\n"
    "                ((gl_VertexID & 2) == 0) ? -1.0 :  1.0);\n"
    "  gl_Position = vec4(p, 0.0, 1.0);\n"
    "}\n";

static const char* FS =
    "#version 330 core\n"
    "uniform sampler2DShadow uShadow;\n"
    "out vec4 oColor;\n"
    "void main() {\n"
    "  float s = texture(uShadow, vec3(0.5, 0.5, 0.5));\n"
    "  oColor = vec4(s, s, s, 1.0);\n"
    "}\n";

static GLuint compile_shader(GLenum type, const char* src) {
    GLuint sh = glCreateShader(type);
    glShaderSource(sh, 1, &src, NULL);
    glCompileShader(sh);
    GLint ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog(sh, sizeof(log), NULL, log);
        fprintf(stderr, "shader compile failed: %s\n", log);
        exit(1);
    }
    return sh;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int scr = DefaultScreen(dpy);

    int fb_attrs[] = {
        GLX_X_RENDERABLE,  True,
        GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_RENDER_TYPE,   GLX_RGBA_BIT,
        GLX_RED_SIZE,   8, GLX_GREEN_SIZE, 8,
        GLX_BLUE_SIZE,  8, GLX_ALPHA_SIZE, 8,
        GLX_DOUBLEBUFFER, True,
        None
    };
    int nfbc = 0;
    GLXFBConfig* fbcs = glXChooseFBConfig(dpy, scr, fb_attrs, &nfbc);
    if (!fbcs || nfbc == 0) { fprintf(stderr, "no fbconfig\n"); return 1; }
    GLXFBConfig fbc = fbcs[0];
    XVisualInfo* vi  = glXGetVisualFromFBConfig(dpy, fbc);

    XSetWindowAttributes swa;
    swa.colormap   = XCreateColormap(dpy, RootWindow(dpy, scr), vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, RootWindow(dpy, scr), 0, 0, 256, 256, 0,
        vi->depth, InputOutput, vi->visual, CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    PFNGLXCREATECONTEXTATTRIBSARBPROC glXCreateContextAttribsARB =
        (PFNGLXCREATECONTEXTATTRIBSARBPROC)
        glXGetProcAddressARB((const GLubyte*)"glXCreateContextAttribsARB");
    int ctx_attrs[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB,  GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        None
    };
    GLXContext ctx = glXCreateContextAttribsARB(dpy, fbc, NULL, True, ctx_attrs);
    if (!ctx) { fprintf(stderr, "context creation failed\n"); return 1; }
    glXMakeCurrent(dpy, win, ctx);

    GLuint vao;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);

    GLuint vs   = compile_shader(GL_VERTEX_SHADER,   VS);
    GLuint fs   = compile_shader(GL_FRAGMENT_SHADER, FS);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);
    GLint linked = 0;
    glGetProgramiv(prog, GL_LINK_STATUS, &linked);
    if (!linked) { fprintf(stderr, "link failed\n"); return 1; }
    glUseProgram(prog);
    GLint loc = glGetUniformLocation(prog, "uShadow");

    // Unit 0: RGBA16F color texture.
    GLuint colorTex;
    glGenTextures(1, &colorTex);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, colorTex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, 4, 4, 0,
                 GL_RGBA, GL_HALF_FLOAT, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);

    // Unit 1: shadow depth texture.
    GLuint depthTex;
    glGenTextures(1, &depthTex);
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, depthTex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT24, 16, 16, 0,
                 GL_DEPTH_COMPONENT, GL_FLOAT, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_COMPARE_MODE, GL_COMPARE_REF_TO_TEXTURE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_COMPARE_FUNC, GL_LEQUAL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);

    glUniform1i(loc, 0);

    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

    GLenum err = glGetError();
    const char* name = (err == GL_INVALID_OPERATION) ? "GL_INVALID_OPERATION"
                     : (err == GL_NO_ERROR)          ? "GL_NO_ERROR"
                                                     : "other";
    printf("glGetError after draw: 0x%04x (%s)\n", err, name);

    glXSwapBuffers(dpy, win);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}