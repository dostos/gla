// SOURCE: https://github.com/mrdoob/three.js/issues/33009
//
// Minimal repro of the three.js InstanceNode UBO-overflow bug pattern:
// the shader declares a fixed-size mat4 array uniform block sized under
// an assumed 64KB limit, but the platform actually reports a smaller
// GL_MAX_UNIFORM_BLOCK_SIZE. Program link fails; the mesh does not render
// and the frame shows only the clear color.

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>

typedef GLXContext (*PFNGLXCREATECONTEXTATTRIBSARBPROC)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

#define GLX_CONTEXT_MAJOR_VERSION_ARB     0x2091
#define GLX_CONTEXT_MINOR_VERSION_ARB     0x2092
#define GLX_CONTEXT_PROFILE_MASK_ARB      0x9126
#define GLX_CONTEXT_CORE_PROFILE_BIT_ARB  0x00000001

static void dump_log(GLuint obj, int is_program) {
    GLint len = 0;
    if (is_program) glGetProgramiv(obj, GL_INFO_LOG_LENGTH, &len);
    else            glGetShaderiv(obj, GL_INFO_LOG_LENGTH, &len);
    if (len > 0) {
        char* buf = (char*)malloc((size_t)len + 1);
        if (is_program) glGetProgramInfoLog(obj, len, NULL, buf);
        else            glGetShaderInfoLog(obj, len, NULL, buf);
        fprintf(stderr, "%s\n", buf);
        free(buf);
    }
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int scr = DefaultScreen(dpy);

    int fb_attribs[] = {
        GLX_RENDER_TYPE,   GLX_RGBA_BIT,
        GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_DOUBLEBUFFER,  True,
        GLX_RED_SIZE,   8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8,
        GLX_DEPTH_SIZE, 24,
        None
    };
    int fb_count = 0;
    GLXFBConfig* fbs = glXChooseFBConfig(dpy, scr, fb_attribs, &fb_count);
    if (!fbs || fb_count == 0) { fprintf(stderr, "no FBConfig\n"); return 1; }
    GLXFBConfig fb = fbs[0];

    XVisualInfo* vi = glXGetVisualFromFBConfig(dpy, fb);
    Window root = RootWindow(dpy, scr);
    XSetWindowAttributes swa;
    memset(&swa, 0, sizeof(swa));
    swa.colormap   = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 800, 600, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    PFNGLXCREATECONTEXTATTRIBSARBPROC glXCreateContextAttribsARB =
        (PFNGLXCREATECONTEXTATTRIBSARBPROC)
        glXGetProcAddressARB((const GLubyte*)"glXCreateContextAttribsARB");
    int ctx_attribs[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB,  GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        None
    };
    GLXContext ctx = glXCreateContextAttribsARB(dpy, fb, NULL, True, ctx_attribs);
    if (!ctx) { fprintf(stderr, "ctx create failed\n"); return 1; }
    glXMakeCurrent(dpy, win, ctx);

    GLint max_ubo_size = 0;
    glGetIntegerv(GL_MAX_UNIFORM_BLOCK_SIZE, &max_ubo_size);
    fprintf(stderr, "GL_MAX_UNIFORM_BLOCK_SIZE = %d bytes\n", max_ubo_size);

    // Reproduce the three.js InstanceNode bug pattern: the calling code
    // picks a matrix count from a hardcoded budget (assuming ~64KB UBO) and
    // never consults GL_MAX_UNIFORM_BLOCK_SIZE. Here we emulate that mistake
    // by declaring a count that exceeds the reported device maximum. A mat4
    // laid out as std140 is 64 bytes.
    int count = (max_ubo_size / 64) + 32;
    fprintf(stderr, "Declaring uniform block NodeBuffer with %d mat4 (%d bytes, limit %d)\n",
            count, count * 64, max_ubo_size);

    char vs_src[8192];
    snprintf(vs_src, sizeof(vs_src),
        "#version 330 core\n"
        "layout(location = 0) in vec3 aPos;\n"
        "layout(std140) uniform NodeBuffer {\n"
        "    mat4 matrices[%d];\n"
        "};\n"
        "void main() {\n"
        "    mat4 m = matrices[gl_InstanceID %% %d];\n"
        "    gl_Position = m * vec4(aPos, 1.0);\n"
        "}\n",
        count, count);

    const char* fs_src =
        "#version 330 core\n"
        "out vec4 FragColor;\n"
        "void main() { FragColor = vec4(1.0, 0.5, 0.2, 1.0); }\n";

    GLuint vs = glCreateShader(GL_VERTEX_SHADER);
    const char* p = vs_src;
    glShaderSource(vs, 1, &p, NULL);
    glCompileShader(vs);
    GLint ok = 0;
    glGetShaderiv(vs, GL_COMPILE_STATUS, &ok);
    if (!ok) { fprintf(stderr, "VS compile failed:\n"); dump_log(vs, 0); }

    GLuint fs = glCreateShader(GL_FRAGMENT_SHADER);
    glShaderSource(fs, 1, &fs_src, NULL);
    glCompileShader(fs);
    glGetShaderiv(fs, GL_COMPILE_STATUS, &ok);
    if (!ok) { fprintf(stderr, "FS compile failed:\n"); dump_log(fs, 0); }

    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);
    glGetProgramiv(prog, GL_LINK_STATUS, &ok);
    if (!ok) {
        fprintf(stderr, "Program link failed (expected UBO overflow):\n");
        dump_log(prog, 1);
    }

    float verts[] = {
        -0.5f, -0.5f, 0.0f,
         0.5f, -0.5f, 0.0f,
         0.0f,  0.5f, 0.0f
    };
    GLuint vao = 0, vbo = 0;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), (void*)0);
    glEnableVertexAttribArray(0);

    // Allocate the oversized UBO matching the shader declaration. Even if
    // the driver would accept the buffer binding, the program is unlinked,
    // so drawing will not produce output.
    GLuint ubo = 0;
    glGenBuffers(1, &ubo);
    glBindBuffer(GL_UNIFORM_BUFFER, ubo);
    glBufferData(GL_UNIFORM_BUFFER, (GLsizeiptr)count * 64, NULL, GL_STATIC_DRAW);
    glBindBufferBase(GL_UNIFORM_BUFFER, 0, ubo);

    glClearColor(0.1f, 0.1f, 0.12f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glUseProgram(prog);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glXSwapBuffers(dpy, win);

    GLenum err = glGetError();
    fprintf(stderr, "post-draw glGetError = 0x%x\n", err);

    glXMakeCurrent(dpy, NULL, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    XFree(fbs);
    XFree(vi);
    return 0;
}