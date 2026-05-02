// SOURCE: https://github.com/mrdoob/three.js/issues/13857

#define GL_GLEXT_PROTOTYPES 1
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef GLXContext (*glXCreateContextAttribsARBProc)(
    Display*, GLXFBConfig, GLXContext, Bool, const int*);

static const char *VERT_SRC =
    "#version 330 core\n"
    "layout(location=0) in vec3 aPos;\n"
    "uniform vec3 uOrigin;\n"
    "void main() {\n"
    "    vec3 world = aPos + uOrigin;\n"
    "    gl_Position = vec4(world.xy * 0.5, world.z * 0.1, 1.0);\n"
    "}\n";

static const char *FRAG_SRC =
    "#version 330 core\n"
    "uniform vec4 uColor;\n"
    "out vec4 fragColor;\n"
    "void main() { fragColor = uColor; }\n";

static GLuint compile_shader(GLenum type, const char *src) {
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[2048];
        glGetShaderInfoLog(s, sizeof(log), NULL, log);
        fprintf(stderr, "shader compile error: %s\n", log);
        exit(1);
    }
    return s;
}

static GLuint link_program(GLuint vs, GLuint fs) {
    GLuint p = glCreateProgram();
    glAttachShader(p, vs);
    glAttachShader(p, fs);
    glLinkProgram(p);
    return p;
}

// One unit quad in local coords, centered at (0,0,zLocal).
static GLuint make_quad(float zLocal) {
    float v[] = {
        -0.8f, -0.8f, zLocal,
         0.8f, -0.8f, zLocal,
         0.8f,  0.8f, zLocal,
        -0.8f, -0.8f, zLocal,
         0.8f,  0.8f, zLocal,
        -0.8f,  0.8f, zLocal,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glGenBuffers(1, &vbo);
    glBindVertexArray(vao);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(v), v, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), 0);
    return vao;
}

int main(void) {
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int scr = DefaultScreen(dpy);

    int fbAttr[] = {
        GLX_RENDER_TYPE,   GLX_RGBA_BIT,
        GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_DOUBLEBUFFER,  True,
        GLX_RED_SIZE,   8, GLX_GREEN_SIZE, 8,
        GLX_BLUE_SIZE,  8, GLX_ALPHA_SIZE, 8,
        GLX_DEPTH_SIZE, 24,
        None
    };
    int nfb = 0;
    GLXFBConfig *fbc = glXChooseFBConfig(dpy, scr, fbAttr, &nfb);
    if (!fbc || nfb == 0) { fprintf(stderr, "no fbconfig\n"); return 1; }
    XVisualInfo *vi = glXGetVisualFromFBConfig(dpy, fbc[0]);

    XSetWindowAttributes swa;
    memset(&swa, 0, sizeof(swa));
    swa.colormap = XCreateColormap(dpy, RootWindow(dpy, scr), vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(
        dpy, RootWindow(dpy, scr), 0, 0, 512, 512, 0,
        vi->depth, InputOutput, vi->visual,
        CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    glXCreateContextAttribsARBProc glXCreateContextAttribsARB =
        (glXCreateContextAttribsARBProc)glXGetProcAddress(
            (const GLubyte *)"glXCreateContextAttribsARB");
    int ctxAttr[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB,  GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        None
    };
    GLXContext ctx = glXCreateContextAttribsARB(dpy, fbc[0], 0, True, ctxAttr);
    glXMakeCurrent(dpy, win, ctx);

    GLuint vs = compile_shader(GL_VERTEX_SHADER,   VERT_SRC);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, FRAG_SRC);
    GLuint prog = link_program(vs, fs);
    glUseProgram(prog);
    GLint uOrigin = glGetUniformLocation(prog, "uOrigin");
    GLint uColor  = glGetUniformLocation(prog, "uColor");

    // Quad A: local z = +3, "origin" at z = -2. World z = +1 (nearer viewer).
    // Quad B: local z = -3, "origin" at z = +2. World z = -1 (farther viewer).
    GLuint quadA = make_quad(+3.0f);
    GLuint quadB = make_quad(-3.0f);

    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glDisable(GL_DEPTH_TEST);

    glBindVertexArray(quadA);
    glUniform3f(uOrigin, 0.0f, 0.0f, -2.0f);
    glUniform4f(uColor,  1.0f, 0.0f, 0.0f, 0.5f); // red, 50%
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glBindVertexArray(quadB);
    glUniform3f(uOrigin, 0.0f, 0.0f, +2.0f);
    glUniform4f(uColor,  0.0f, 0.0f, 1.0f, 0.5f); // blue, 50%
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glXSwapBuffers(dpy, win);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}