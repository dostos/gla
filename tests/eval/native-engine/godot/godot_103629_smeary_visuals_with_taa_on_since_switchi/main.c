// SOURCE: https://github.com/godotengine/godot/issues/103629
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

static const char *quad_vs =
    "#version 330 core\n"
    "layout(location=0) in vec2 pos;\n"
    "out vec2 v_uv;\n"
    "void main(){ v_uv = pos*0.5+0.5; gl_Position = vec4(pos,0,1); }\n";

// Scene pass: writes color to MRT[0] and per-pixel motion vectors to MRT[1].
static const char *scene_fs =
    "#version 330 core\n"
    "in vec2 v_uv;\n"
    "layout(location=0) out vec4 o_color;\n"
    "layout(location=1) out vec4 o_motion;\n"
    "void main(){\n"
    "  o_color = vec4(0.2, 0.5, 0.9, 1.0);\n"
    "  o_motion = vec4(v_uv.x, v_uv.y, 0.5, 1.0);\n"
    "}\n";

// Post-process fullscreen quad: samples screen color, but is still bound to
// the MRT setup that includes the motion vector attachment. Its motion-vector
// output is uniform zero, overwriting the per-pixel scene motion vectors.
static const char *post_fs =
    "#version 330 core\n"
    "in vec2 v_uv;\n"
    "uniform sampler2D screen_tex;\n"
    "layout(location=0) out vec4 o_color;\n"
    "layout(location=1) out vec4 o_motion;\n"
    "void main(){\n"
    "  o_color = texture(screen_tex, v_uv);\n"
    "  o_motion = vec4(0.0, 0.0, 0.0, 1.0);\n"
    "}\n";

static GLuint compile_shader(GLenum type, const char *src) {
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok = 0;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
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
    GLint ok = 0;
    glGetProgramiv(p, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetProgramInfoLog(p, sizeof(log), NULL, log);
        fprintf(stderr, "link error: %s\n", log);
        exit(1);
    }
    return p;
}

int main(void) {
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "cannot open display\n"); return 1; }
    int attribs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo *vi = glXChooseVisual(dpy, 0, attribs);
    if (!vi) { fprintf(stderr, "no visual\n"); return 1; }
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, W, H, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    // Build MRT framebuffer: color + motion-vector attachments.
    GLuint fbo, color_tex, motion_tex;
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);

    glGenTextures(1, &color_tex);
    glBindTexture(GL_TEXTURE_2D, color_tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, W, H, 0, GL_RGBA,
                 GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_2D, color_tex, 0);

    glGenTextures(1, &motion_tex);
    glBindTexture(GL_TEXTURE_2D, motion_tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, W, H, 0, GL_RGBA,
                 GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT1,
                           GL_TEXTURE_2D, motion_tex, 0);

    GLenum bufs[2] = { GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1 };
    glDrawBuffers(2, bufs);

    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
        fprintf(stderr, "FBO incomplete\n");
        return 1;
    }

    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    float tri[] = { -1.0f, -1.0f,  3.0f, -1.0f, -1.0f, 3.0f };
    glBufferData(GL_ARRAY_BUFFER, sizeof(tri), tri, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, 0);
    glEnableVertexAttribArray(0);

    GLuint vs = compile_shader(GL_VERTEX_SHADER, quad_vs);
    GLuint scene_prog = link_program(vs, compile_shader(GL_FRAGMENT_SHADER, scene_fs));
    GLuint post_prog  = link_program(vs, compile_shader(GL_FRAGMENT_SHADER, post_fs));

    glViewport(0, 0, W, H);

    // Pass 1: scene → MRT, writes per-pixel motion vectors to attachment 1.
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glDrawBuffers(2, bufs);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(scene_prog);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    // Pass 2: fullscreen post quad samples color attachment 0, but the engine
    // left attachment 1 bound. The quad's motion-vector output is zero, which
    // wipes the per-pixel scene motion vectors that pass 1 produced.
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, color_tex);
    glUseProgram(post_prog);
    glUniform1i(glGetUniformLocation(post_prog, "screen_tex"), 0);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    // Present the motion vector buffer so the corruption is visible.
    glBindFramebuffer(GL_READ_FRAMEBUFFER, fbo);
    glReadBuffer(GL_COLOR_ATTACHMENT1);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
    glBlitFramebuffer(0, 0, W, H, 0, 0, W, H,
                      GL_COLOR_BUFFER_BIT, GL_NEAREST);

    glXSwapBuffers(dpy, win);
    glFinish();
    return 0;
}