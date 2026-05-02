// SOURCE: https://github.com/mrdoob/three.js/issues/33060
// Minimal reproduction of the r182 transmission render path:
// when capabilities.samples == 0, the transmission render target's
// texture is attached directly as COLOR_ATTACHMENT0 while the fragment
// shader simultaneously samples that same texture via a uniform.

#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define W 256
#define H 256

static const char* VS =
    "#version 330 core\n"
    "layout(location=0) in vec2 p;\n"
    "out vec2 uv;\n"
    "void main(){ uv = p*0.5+0.5; gl_Position = vec4(p,0,1); }\n";

/* Fragment shader mimics the transmission pass: reads the transmission
 * texture and tints it -- the DoubleSide/back-face pass from
 * WebGLRenderer.js lines 2016-2042. */
static const char* FS =
    "#version 330 core\n"
    "in vec2 uv;\n"
    "uniform sampler2D transmissionMap;\n"
    "out vec4 o;\n"
    "void main(){\n"
    "    vec4 t = texture(transmissionMap, uv);\n"
    "    o = vec4(t.rgb * 0.8 + vec3(0.1,0.05,0.0), 1.0);\n"
    "}\n";

static GLuint compile(GLenum type, const char* src) {
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok = 0;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog(s, 1024, NULL, log);
        fprintf(stderr, "shader compile error: %s\n", log);
        exit(1);
    }
    return s;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "cannot open display\n"); return 1; }
    int scr = DefaultScreen(dpy);
    int attrs[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo* vi = glXChooseVisual(dpy, scr, attrs);
    if (!vi) { fprintf(stderr, "no GLX visual\n"); return 1; }

    Colormap cmap = XCreateColormap(dpy, RootWindow(dpy, scr),
                                    vi->visual, AllocNone);
    XSetWindowAttributes swa;
    memset(&swa, 0, sizeof swa);
    swa.colormap = cmap;
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, RootWindow(dpy, scr), 0, 0, W, H, 0,
                               vi->depth, InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    GLXContext ctx = glXCreateContext(dpy, vi, NULL, True);
    if (!ctx) { fprintf(stderr, "GLX ctx failed\n"); return 1; }
    glXMakeCurrent(dpy, win, ctx);

    /* Full-screen triangle (represents a DoubleSide back-face draw of
     * the transmissive mesh). */
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    float verts[] = { -1.0f, -1.0f,  3.0f, -1.0f,  -1.0f, 3.0f };
    glBufferData(GL_ARRAY_BUFFER, sizeof verts, verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);

    /* Program. */
    GLuint prog = glCreateProgram();
    glAttachShader(prog, compile(GL_VERTEX_SHADER,   VS));
    glAttachShader(prog, compile(GL_FRAGMENT_SHADER, FS));
    glLinkProgram(prog);
    GLint linked = 0;
    glGetProgramiv(prog, GL_LINK_STATUS, &linked);
    if (!linked) { fprintf(stderr, "link failed\n"); return 1; }
    glUseProgram(prog);
    glUniform1i(glGetUniformLocation(prog, "transmissionMap"), 0);

    /* "Transmission render target" texture. In three.js r182 with
     * samples:0 this is attached directly, with no MSAA resolve step. */
    GLuint transmissionTex;
    glGenTextures(1, &transmissionTex);
    glBindTexture(GL_TEXTURE_2D, transmissionTex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, W, H, 0,
                 GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    /* FBO: attach the same texture as COLOR_ATTACHMENT0. This mirrors
     * the samples==0 branch: no renderbuffer between framebuffer and
     * sampled texture. */
    GLuint fbo;
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_2D, transmissionTex, 0);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
        fprintf(stderr, "FBO incomplete\n"); return 1;
    }

    glViewport(0, 0, W, H);
    glClearColor(0.2f, 0.4f, 0.8f, 1.0f);

    for (int frame = 0; frame < 5; frame++) {
        glBindFramebuffer(GL_FRAMEBUFFER, fbo);
        glClear(GL_COLOR_BUFFER_BIT);

        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, transmissionTex);

        /* Back-face pass sampling the transmission RT. */
        glDrawArrays(GL_TRIANGLES, 0, 3);

        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glXSwapBuffers(dpy, win);
    }

    /* Check for GL errors after the draw. */
    GLenum err;
    int reported = 0;
    while ((err = glGetError()) != GL_NO_ERROR && reported < 8) {
        fprintf(stderr, "GL error 0x%x\n", err);
        reported++;
    }

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XFreeColormap(dpy, cmap);
    XFree(vi);
    XCloseDisplay(dpy);
    return 0;
}