// SOURCE: https://github.com/mrdoob/three.js/issues/33009
#define _GNU_SOURCE
#define GL_GLEXT_PROTOTYPES 1
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// Ported pattern from three.js r182 InstanceNode.js: a hardcoded ~1000-instance
// UBO threshold assumes ~64 KB GL_MAX_UNIFORM_BLOCK_SIZE. When the actual driver
// limit is smaller (e.g. Chrome/ANGLE reports the WebGL2 minimum 16 KB), the
// UBO-backed shader fails to link and the InstancedMesh silently vanishes.
// To make the failure deterministic on any desktop GL driver used under Xvfb
// (llvmpipe reports ~64 KB), we push to 3000 mat4 (192 KB) so the declared
// block exceeds every real implementation's limit.
#define INSTANCE_COUNT 3000
#define STR1(x) #x
#define STR(x) STR1(x)

static const char *VS_SRC =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "layout(std140) uniform InstanceBlock {\n"
    "    mat4 matrices[" STR(INSTANCE_COUNT) "];\n"
    "};\n"
    "void main(){\n"
    "    gl_Position = matrices[gl_InstanceID] * vec4(aPos, 0.0, 1.0);\n"
    "}\n";

static const char *FS_SRC =
    "#version 330 core\n"
    "out vec4 fragColor;\n"
    "void main(){ fragColor = vec4(1.0, 0.3, 0.1, 1.0); }\n";

#define GLX_CONTEXT_MAJOR_VERSION_ARB 0x2091
#define GLX_CONTEXT_MINOR_VERSION_ARB 0x2092
#define GLX_CONTEXT_PROFILE_MASK_ARB  0x9126
#define GLX_CONTEXT_CORE_PROFILE_BIT_ARB 0x00000001

typedef GLXContext (*glXCreateContextAttribsARBProc)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

static GLuint build_shader(GLenum stage, const char *src){
    GLuint s = glCreateShader(stage);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok = 0;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if(!ok){
        char log[1024] = {0};
        glGetShaderInfoLog(s, sizeof(log)-1, NULL, log);
        fprintf(stderr, "shader compile error: %s\n", log);
    }
    return s;
}

int main(void){
    Display *dpy = XOpenDisplay(NULL);
    if(!dpy){ fprintf(stderr, "cannot open display\n"); return 1; }

    int fbattribs[] = {
        GLX_X_RENDERABLE, True,
        GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_RENDER_TYPE, GLX_RGBA_BIT,
        GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8,
        GLX_ALPHA_SIZE, 8, GLX_DEPTH_SIZE, 24,
        GLX_DOUBLEBUFFER, True,
        None
    };
    int nfb = 0;
    GLXFBConfig *fbcs = glXChooseFBConfig(dpy, DefaultScreen(dpy), fbattribs, &nfb);
    if(!fbcs || nfb == 0){ fprintf(stderr, "no fbconfig\n"); return 1; }
    GLXFBConfig fbc = fbcs[0];
    XVisualInfo *vi = glXGetVisualFromFBConfig(dpy, fbc);

    Window root = RootWindow(dpy, vi->screen);
    XSetWindowAttributes swa; memset(&swa, 0, sizeof(swa));
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 256, 256, 0,
        vi->depth, InputOutput, vi->visual,
        CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    glXCreateContextAttribsARBProc createCtx =
        (glXCreateContextAttribsARBProc)glXGetProcAddressARB((const GLubyte*)"glXCreateContextAttribsARB");
    int ctxattr[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        None
    };
    GLXContext ctx = createCtx(dpy, fbc, NULL, True, ctxattr);
    if(!ctx){ fprintf(stderr, "no GL 3.3 core context\n"); return 1; }
    glXMakeCurrent(dpy, win, ctx);

    GLint maxUBO = 0;
    glGetIntegerv(GL_MAX_UNIFORM_BLOCK_SIZE, &maxUBO);
    fprintf(stderr, "GL_MAX_UNIFORM_BLOCK_SIZE = %d bytes; declared UBO = %d bytes\n",
            maxUBO, (int)(INSTANCE_COUNT) * 64);

    GLuint vs = build_shader(GL_VERTEX_SHADER, VS_SRC);
    GLuint fs = build_shader(GL_FRAGMENT_SHADER, FS_SRC);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);

    GLint linked = 0;
    glGetProgramiv(prog, GL_LINK_STATUS, &linked);
    if(!linked){
        char log[2048] = {0};
        glGetProgramInfoLog(prog, sizeof(log)-1, NULL, log);
        fprintf(stderr, "LINK FAILED: %s\n", log);
    } else {
        fprintf(stderr, "link ok (unexpected on limited drivers)\n");
    }

    float verts[] = { -0.6f, -0.5f,  0.6f, -0.5f,  0.0f, 0.6f };
    GLuint vao = 0, vbo = 0;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);
    glEnableVertexAttribArray(0);

    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.2f, 0.4f, 1.0f);

    for (int frame = 0; frame < 5; frame++) {
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        glUseProgram(prog);
        glDrawArraysInstanced(GL_TRIANGLES, 0, 3, 8);

        glXSwapBuffers(dpy, win);
    }

    unsigned char px[4] = {0};
    glReadPixels(128, 128, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    fprintf(stderr, "center pixel = (%u,%u,%u,%u)\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XFree(vi);
    XFree(fbcs);
    XCloseDisplay(dpy);
    return 0;
}