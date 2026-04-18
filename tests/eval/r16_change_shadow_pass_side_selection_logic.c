// SOURCE: https://github.com/mrdoob/three.js/issues/33172
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <X11/Xlib.h>
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>

#ifndef GLX_CONTEXT_MAJOR_VERSION_ARB
#define GLX_CONTEXT_MAJOR_VERSION_ARB 0x2091
#define GLX_CONTEXT_MINOR_VERSION_ARB 0x2092
#define GLX_CONTEXT_PROFILE_MASK_ARB  0x9126
#define GLX_CONTEXT_CORE_PROFILE_BIT_ARB 0x00000001
#endif

typedef GLXContext (*glXCreateContextAttribsARBProc)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

static const char* VS =
    "#version 330 core\n"
    "layout(location=0) in vec3 pos;\n"
    "void main(){ gl_Position = vec4(pos, 1.0); }\n";

static const char* FS =
    "#version 330 core\n"
    "out vec4 FragColor;\n"
    "void main(){ FragColor = vec4(1.0, 0.0, 0.0, 1.0); }\n";

static GLuint compile_shader(GLenum type, const char* src) {
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok; glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024]; glGetShaderInfoLog(s, sizeof log, NULL, log);
        fprintf(stderr, "shader compile error: %s\n", log);
        exit(1);
    }
    return s;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int screen = DefaultScreen(dpy);

    int fb_attrs[] = {
        GLX_X_RENDERABLE,  True,
        GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_RENDER_TYPE,   GLX_RGBA_BIT,
        GLX_X_VISUAL_TYPE, GLX_TRUE_COLOR,
        GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8,
        GLX_DEPTH_SIZE, 24,
        GLX_DOUBLEBUFFER, True,
        None
    };
    int nfb = 0;
    GLXFBConfig* fbc = glXChooseFBConfig(dpy, screen, fb_attrs, &nfb);
    if (!fbc || nfb == 0) { fprintf(stderr, "no FBConfig\n"); return 1; }
    GLXFBConfig fbconfig = fbc[0];
    XFree(fbc);

    XVisualInfo* vi = glXGetVisualFromFBConfig(dpy, fbconfig);
    XSetWindowAttributes swa;
    memset(&swa, 0, sizeof swa);
    swa.colormap = XCreateColormap(dpy, RootWindow(dpy, vi->screen), vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, RootWindow(dpy, vi->screen), 0, 0, 256, 256, 0,
        vi->depth, InputOutput, vi->visual, CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    glXCreateContextAttribsARBProc glXCreateContextAttribsARB =
        (glXCreateContextAttribsARBProc)glXGetProcAddressARB((const GLubyte*)"glXCreateContextAttribsARB");
    int ctx_attrs[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB,  GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        None
    };
    GLXContext ctx = glXCreateContextAttribsARB(dpy, fbconfig, NULL, True, ctx_attrs);
    if (!ctx) { fprintf(stderr, "context creation failed\n"); return 1; }
    glXMakeCurrent(dpy, win, ctx);

    GLuint vs = compile_shader(GL_VERTEX_SHADER, VS);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, FS);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs); glAttachShader(prog, fs);
    glLinkProgram(prog);

    // Shadow-caster analogue: a triangle wound CCW as seen from +Z (the "light").
    // GL default is CCW == FRONT, so this is a front-facing caster to the light.
    float verts[] = {
        -0.8f, -0.8f, 0.0f,
         0.8f, -0.8f, 0.0f,
         0.0f,  0.8f, 0.0f,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao); glBindVertexArray(vao);
    glGenBuffers(1, &vbo); glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof verts, verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), 0);

    // Shadow-pass side selection: front-face culling.
    glEnable(GL_CULL_FACE);
    glFrontFace(GL_CCW);
    glCullFace(GL_FRONT);

    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);

    for (int frame = 0; frame < 5; frame++) {
        glClear(GL_COLOR_BUFFER_BIT);
        glUseProgram(prog);
        glBindVertexArray(vao);
        glDrawArrays(GL_TRIANGLES, 0, 3);

        glXSwapBuffers(dpy, win);
    }

    unsigned char px[4] = {0};
    glReadPixels(128, 128, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center pixel RGBA = %u %u %u %u\n", px[0], px[1], px[2], px[3]);
    printf("center pixel: %s\n", px[0] > 128 ? "red" : "black");
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XFreeColormap(dpy, swa.colormap);
    XCloseDisplay(dpy);
    return 0;
}