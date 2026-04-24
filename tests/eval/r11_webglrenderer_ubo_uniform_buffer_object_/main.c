// SOURCE: https://github.com/mrdoob/three.js/issues/28818
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef GLXContext (*glXCreateContextAttribsARBProc)(Display*, GLXFBConfig,
                                                      GLXContext, Bool,
                                                      const int*);

static const char* vs_src =
    "#version 330 core\n"
    "const vec2 verts[3] = vec2[3](vec2(-1.0,-1.0), vec2(3.0,-1.0), vec2(-1.0,3.0));\n"
    "void main() { gl_Position = vec4(verts[gl_VertexID], 0.0, 1.0); }\n";

static const char* fs_src =
    "#version 330 core\n"
    "layout(std140) uniform Global {\n"
    "    float time;\n"
    "    vec2  resolution;\n"
    "};\n"
    "out vec4 frag;\n"
    "void main() {\n"
    "    frag = vec4(resolution.x / 100.0, resolution.y / 100.0, 0.0, 1.0);\n"
    "}\n";

static GLuint compile_shader(GLenum stage, const char* src) {
    GLuint s = glCreateShader(stage);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok = 0;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[2048];
        glGetShaderInfoLog(s, sizeof(log), NULL, log);
        fprintf(stderr, "shader compile failed: %s\n", log);
        exit(1);
    }
    return s;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "cannot open display\n"); return 1; }

    int fb_attr[] = {
        GLX_RENDER_TYPE,   GLX_RGBA_BIT,
        GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_DOUBLEBUFFER,  True,
        GLX_RED_SIZE,      8,
        GLX_GREEN_SIZE,    8,
        GLX_BLUE_SIZE,     8,
        GLX_ALPHA_SIZE,    8,
        None
    };
    int nfb = 0;
    GLXFBConfig* fbs = glXChooseFBConfig(dpy, DefaultScreen(dpy), fb_attr, &nfb);
    if (!fbs || nfb == 0) { fprintf(stderr, "no fbconfig\n"); return 1; }
    XVisualInfo* vi = glXGetVisualFromFBConfig(dpy, fbs[0]);

    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, RootWindow(dpy, vi->screen),
                                   vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, RootWindow(dpy, vi->screen),
                               0, 0, 256, 256, 0,
                               vi->depth, InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    glXCreateContextAttribsARBProc ccaa = (glXCreateContextAttribsARBProc)
        glXGetProcAddressARB((const GLubyte*)"glXCreateContextAttribsARB");
    int ctx_attr[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB,  GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        None
    };
    GLXContext ctx = ccaa(dpy, fbs[0], NULL, True, ctx_attr);
    glXMakeCurrent(dpy, win, ctx);

    GLuint vs   = compile_shader(GL_VERTEX_SHADER, vs_src);
    GLuint fs   = compile_shader(GL_FRAGMENT_SHADER, fs_src);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);

    GLuint block_idx = glGetUniformBlockIndex(prog, "Global");
    glUniformBlockBinding(prog, block_idx, 0);

    // CPU-side uniform data: one float followed by one vec2 (two floats),
    // written into the buffer in source order.
    unsigned char buf[16] = {0};
    float time_val = 0.0f;
    float res_x    = 11.0f;
    float res_y    = 33.0f;
    size_t off = 0;
    memcpy(buf + off, &time_val, sizeof(float)); off += sizeof(float);
    memcpy(buf + off, &res_x,    sizeof(float)); off += sizeof(float);
    memcpy(buf + off, &res_y,    sizeof(float)); off += sizeof(float);

    GLuint ubo;
    glGenBuffers(1, &ubo);
    glBindBuffer(GL_UNIFORM_BUFFER, ubo);
    glBufferData(GL_UNIFORM_BUFFER, sizeof(buf), buf, GL_STATIC_DRAW);
    glBindBufferBase(GL_UNIFORM_BUFFER, 0, ubo);

    GLuint vao;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);

    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(prog);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    unsigned char px[4] = {0};
    glReadPixels(128, 128, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center pixel rgba=%u,%u,%u,%u\n", px[0], px[1], px[2], px[3]);

    glXSwapBuffers(dpy, win);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}