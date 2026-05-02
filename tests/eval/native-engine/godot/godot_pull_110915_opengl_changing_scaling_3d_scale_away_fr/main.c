// SOURCE: https://github.com/godotengine/godot/issues/102860
// Minimal repro of "double tonemap" pattern:
// When the renderer enables an intermediate buffer (e.g. on scaling_3d != 1.0),
// the scene shader keeps applying tonemapping inline, AND the post pass that
// resolves the intermediate buffer to the default framebuffer also tonemaps.
// Result: the scene comes out visibly dimmer than it should.
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define W 320
#define H 240

typedef GLuint (*PFN_CreateShader)(GLenum);
typedef void (*PFN_ShaderSource)(GLuint, GLsizei, const char *const *, const GLint *);
typedef void (*PFN_CompileShader)(GLuint);
typedef GLuint (*PFN_CreateProgram)(void);
typedef void (*PFN_AttachShader)(GLuint, GLuint);
typedef void (*PFN_LinkProgram)(GLuint);
typedef void (*PFN_UseProgram)(GLuint);
typedef void (*PFN_GenFramebuffers)(GLsizei, GLuint *);
typedef void (*PFN_BindFramebuffer)(GLenum, GLuint);
typedef void (*PFN_FramebufferTexture2D)(GLenum, GLenum, GLenum, GLuint, GLint);
typedef void (*PFN_GenVertexArrays)(GLsizei, GLuint *);
typedef void (*PFN_BindVertexArray)(GLuint);
typedef void (*PFN_GenBuffers)(GLsizei, GLuint *);
typedef void (*PFN_BindBuffer)(GLenum, GLuint);
typedef void (*PFN_BufferData)(GLenum, long, const void *, GLenum);
typedef void (*PFN_VertexAttribPointer)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void *);
typedef void (*PFN_EnableVertexAttribArray)(GLuint);
typedef GLint (*PFN_GetUniformLocation)(GLuint, const char *);
typedef void (*PFN_Uniform1i)(GLint, GLint);
typedef void (*PFN_ActiveTexture)(GLenum);

#define GL_FRAGMENT_SHADER 0x8B30
#define GL_VERTEX_SHADER 0x8B31
#define GL_FRAMEBUFFER 0x8D40
#define GL_COLOR_ATTACHMENT0 0x8CE0
#define GL_ARRAY_BUFFER 0x8892
#define GL_STATIC_DRAW 0x88E4
#define GL_TEXTURE0 0x84C0
#define GL_CLAMP_TO_EDGE 0x812F

#define LD(T, n) T n = (T)glXGetProcAddressARB((const GLubyte *)#n)

static const char *vs_src =
"#version 330 core\nlayout(location=0) in vec2 p; out vec2 uv;\n"
"void main(){ uv = p*0.5+0.5; gl_Position = vec4(p,0,1); }\n";

// Scene shader: produces a "linear HDR" color, then tonemaps inline.
// In Godot's GL3 path this happens unconditionally in the scene shader,
// regardless of whether an intermediate buffer is in use.
static const char *fs_scene_src =
"#version 330 core\nin vec2 uv; out vec4 c;\n"
"vec3 tonemap(vec3 x){ return x/(x+vec3(1.0)); }\n"
"void main(){ vec3 hdr = vec3(0.8, 0.6, 0.4); c = vec4(tonemap(hdr), 1.0); }\n";

// Post shader: samples the intermediate buffer and tonemaps AGAIN.
static const char *fs_post_src =
"#version 330 core\nin vec2 uv; out vec4 c; uniform sampler2D src;\n"
"vec3 tonemap(vec3 x){ return x/(x+vec3(1.0)); }\n"
"void main(){ vec3 s = texture(src, uv).rgb; c = vec4(tonemap(s), 1.0); }\n";

static GLuint mk_prog(PFN_CreateShader cs, PFN_ShaderSource ss, PFN_CompileShader csh,
                      PFN_CreateProgram cp, PFN_AttachShader as, PFN_LinkProgram lp,
                      const char *vs, const char *fs) {
    GLuint v = cs(GL_VERTEX_SHADER); ss(v,1,&vs,NULL); csh(v);
    GLuint f = cs(GL_FRAGMENT_SHADER); ss(f,1,&fs,NULL); csh(f);
    GLuint p = cp(); as(p,v); as(p,f); lp(p); return p;
}

int main(void) {
    Display *dpy = XOpenDisplay(NULL);
    int attr[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo *vi = glXChooseVisual(dpy, 0, attr);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa = { .colormap = XCreateColormap(dpy, root, vi->visual, AllocNone) };
    Window win = XCreateWindow(dpy, root, 0,0,W,H,0,vi->depth,InputOutput,vi->visual,CWColormap,&swa);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    LD(PFN_CreateShader, glCreateShader);
    LD(PFN_ShaderSource, glShaderSource);
    LD(PFN_CompileShader, glCompileShader);
    LD(PFN_CreateProgram, glCreateProgram);
    LD(PFN_AttachShader, glAttachShader);
    LD(PFN_LinkProgram, glLinkProgram);
    LD(PFN_UseProgram, glUseProgram);
    LD(PFN_GenFramebuffers, glGenFramebuffers);
    LD(PFN_BindFramebuffer, glBindFramebuffer);
    LD(PFN_FramebufferTexture2D, glFramebufferTexture2D);
    LD(PFN_GenVertexArrays, glGenVertexArrays);
    LD(PFN_BindVertexArray, glBindVertexArray);
    LD(PFN_GenBuffers, glGenBuffers);
    LD(PFN_BindBuffer, glBindBuffer);
    LD(PFN_BufferData, glBufferData);
    LD(PFN_VertexAttribPointer, glVertexAttribPointer);
    LD(PFN_EnableVertexAttribArray, glEnableVertexAttribArray);
    LD(PFN_GetUniformLocation, glGetUniformLocation);
    LD(PFN_Uniform1i, glUniform1i);
    LD(PFN_ActiveTexture, glActiveTexture);

    GLuint scene_prog = mk_prog(glCreateShader, glShaderSource, glCompileShader,
                                glCreateProgram, glAttachShader, glLinkProgram,
                                vs_src, fs_scene_src);
    GLuint post_prog = mk_prog(glCreateShader, glShaderSource, glCompileShader,
                               glCreateProgram, glAttachShader, glLinkProgram,
                               vs_src, fs_post_src);

    GLuint vao, vbo;
    glGenVertexArrays(1, &vao); glBindVertexArray(vao);
    glGenBuffers(1, &vbo); glBindBuffer(GL_ARRAY_BUFFER, vbo);
    float quad[] = { -1,-1,  1,-1,  -1,1,  -1,1,  1,-1,  1,1 };
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL);

    // "Intermediate buffer" — analogous to internal3d.fbo when scaling_3d != 1.0.
    GLuint inter_tex, inter_fbo;
    glGenTextures(1, &inter_tex);
    glBindTexture(GL_TEXTURE_2D, inter_tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, W, H, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glGenFramebuffers(1, &inter_fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, inter_fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, inter_tex, 0);

    // Scene pass into intermediate FBO. Scene shader applies tonemap inline.
    glViewport(0, 0, W, H);
    glClearColor(0, 0, 0, 1); glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(scene_prog);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    // Post pass to default framebuffer. ALSO applies tonemap.
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, W, H);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(post_prog);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, inter_tex);
    GLint loc = glGetUniformLocation(post_prog, "src");
    glUniform1i(loc, 0);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glXSwapBuffers(dpy, win);
    return 0;
}