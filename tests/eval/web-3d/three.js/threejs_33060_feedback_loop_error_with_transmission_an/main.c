// SOURCE: https://github.com/mrdoob/three.js/issues/33060
// Minimal reproducer for a framebuffer feedback loop: the same GL texture
// is simultaneously attached as the bound FBO's COLOR_ATTACHMENT0 AND
// bound to a sampler unit referenced by the active fragment shader.
// Issuing a draw under this configuration produces undefined results
// per the GL spec; implementations typically signal GL_INVALID_OPERATION
// and silently drop the draw, leaving the framebuffer untouched.
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>

static const char *VS_SRC =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "out vec2 vUV;\n"
    "void main(){ vUV = aPos*0.5+0.5; gl_Position = vec4(aPos,0.0,1.0); }\n";

static const char *FS_SRC =
    "#version 330 core\n"
    "in vec2 vUV;\n"
    "uniform sampler2D transmissionSamplerMap;\n"
    "out vec4 oColor;\n"
    "void main(){\n"
    "  vec4 base = vec4(0.1, 0.6, 0.9, 1.0);\n"
    "  vec4 transmitted = texture(transmissionSamplerMap, vUV);\n"
    "  oColor = mix(base, transmitted, 0.85);\n"
    "}\n";

static GLuint compile_shader(GLenum kind, const char *src) {
    GLuint sh = glCreateShader(kind);
    glShaderSource(sh, 1, &src, NULL);
    glCompileShader(sh);
    GLint ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024]; glGetShaderInfoLog(sh, sizeof(log), NULL, log);
        fprintf(stderr, "shader compile failed: %s\n", log);
        exit(1);
    }
    return sh;
}

int main(void) {
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }

    int attribs[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo *vi = glXChooseVisual(dpy, 0, attribs);
    if (!vi) { fprintf(stderr, "no visual\n"); return 1; }

    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 800, 600, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    // === Build the transmission render target. ===
    // In three.js this is created with samples=0 when antialias:false and
    // capabilities.samples returns 0 (PR #32444). With samples=0, no MSAA
    // renderbuffer exists; the texture itself becomes COLOR_ATTACHMENT0.
    GLuint transmissionTex;
    glGenTextures(1, &transmissionTex);
    glBindTexture(GL_TEXTURE_2D, transmissionTex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 800, 600, 0,
                 GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    GLuint transmissionFbo;
    glGenFramebuffers(1, &transmissionFbo);
    glBindFramebuffer(GL_FRAMEBUFFER, transmissionFbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_2D, transmissionTex, 0);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
        fprintf(stderr, "FBO incomplete\n"); return 1;
    }

    // Front-face transmission pass populated the target with some content.
    glViewport(0, 0, 800, 600);
    glClearColor(0.95f, 0.85f, 0.20f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    // === Geometry: a fullscreen quad standing in for the back-face draw. ===
    float verts[] = { -1.f, -1.f,  1.f, -1.f, -1.f, 1.f,  1.f, 1.f };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);

    GLuint vs = compile_shader(GL_VERTEX_SHADER,   VS_SRC);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, FS_SRC);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs); glAttachShader(prog, fs);
    glLinkProgram(prog);
    glUseProgram(prog);
    glUniform1i(glGetUniformLocation(prog, "transmissionSamplerMap"), 0);

    // === The bug: bind transmissionTex as the sampled texture WHILE it
    // is still the bound FBO's COLOR_ATTACHMENT0. This is exactly what
    // renderTransmissionPass()'s back-face DoubleSide loop does in r182+
    // when the WEBGL_multisampled_render_to_texture extension is absent
    // and capabilities.samples == 0. ===
    glBindFramebuffer(GL_FRAMEBUFFER, transmissionFbo);  // still bound
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, transmissionTex);       // collision

    // The "back-face" draw — reads from transmissionSamplerMap while
    // writing to COLOR_ATTACHMENT0 of the same texture object.
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

    GLenum err = glGetError();
    if (err != GL_NO_ERROR) {
        fprintf(stderr, "post-draw glGetError = 0x%x\n", err);
    }

    glXSwapBuffers(dpy, win);
    return 0;
}