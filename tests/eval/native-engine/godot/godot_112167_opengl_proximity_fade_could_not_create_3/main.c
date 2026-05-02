// SOURCE: https://github.com/godotengine/godot/issues/112167
// Compatibility-renderer back-buffer setup for the 3D-scaling path,
// followed by a spatial-style "proximity fade" draw that samples the
// depth texture via a hint_depth_texture uniform. The full-screen quad
// is drawn to the default framebuffer after the back buffer is blitted
// in — whether the quad shows green (back-buffer) or black (default
// clear) depends on whether glTexImage2D accepted the depth/stencil
// configuration used for the back-buffer depth attachment.
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>

#ifndef GL_DEPTH24_STENCIL8
#define GL_DEPTH24_STENCIL8 0x88F0
#endif
#ifndef GL_DEPTH_STENCIL
#define GL_DEPTH_STENCIL 0x84F9
#endif
#ifndef GL_UNSIGNED_INT_24_8
#define GL_UNSIGNED_INT_24_8 0x84FA
#endif

#define GL_FRAMEBUFFER                         0x8D40
#define GL_READ_FRAMEBUFFER                    0x8CA8
#define GL_DRAW_FRAMEBUFFER                    0x8CA9
#define GL_COLOR_ATTACHMENT0                   0x8CE0
#define GL_DEPTH_STENCIL_ATTACHMENT            0x821A
#define GL_FRAMEBUFFER_COMPLETE                0x8CD5
#define GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT   0x8CD6
#define GL_VERTEX_SHADER                       0x8B31
#define GL_FRAGMENT_SHADER                     0x8B30
#define GL_COMPILE_STATUS                      0x8B81
#define GL_LINK_STATUS                         0x8B82
#define GL_ARRAY_BUFFER                        0x8892
#define GL_STATIC_DRAW                         0x88E4

#define GLX_CONTEXT_MAJOR_VERSION_ARB          0x2091
#define GLX_CONTEXT_MINOR_VERSION_ARB          0x2092
#define GLX_CONTEXT_PROFILE_MASK_ARB           0x9126
#define GLX_CONTEXT_CORE_PROFILE_BIT_ARB       0x00000001

typedef void   (*GenFB_t)(GLsizei, GLuint*);
typedef void   (*BindFB_t)(GLenum, GLuint);
typedef void   (*FBTex2D_t)(GLenum, GLenum, GLenum, GLuint, GLint);
typedef GLenum (*CheckFB_t)(GLenum);
typedef void   (*Blit_t)(GLint,GLint,GLint,GLint,GLint,GLint,GLint,GLint,GLbitfield,GLenum);
typedef GLXContext (*CreateCtx_t)(Display*, GLXFBConfig, GLXContext, Bool, const int*);
typedef GLuint (*CreateShader_t)(GLenum);
typedef void   (*ShaderSource_t)(GLuint, GLsizei, const char* const*, const GLint*);
typedef void   (*CompileShader_t)(GLuint);
typedef void   (*GetShaderiv_t)(GLuint, GLenum, GLint*);
typedef void   (*GetShaderInfoLog_t)(GLuint, GLsizei, GLsizei*, GLchar*);
typedef GLuint (*CreateProgram_t)(void);
typedef void   (*AttachShader_t)(GLuint, GLuint);
typedef void   (*LinkProgram_t)(GLuint);
typedef void   (*UseProgram_t)(GLuint);
typedef GLint  (*GetUniformLocation_t)(GLuint, const char*);
typedef void   (*Uniform1i_t)(GLint, GLint);
typedef void   (*GenBuffers_t)(GLsizei, GLuint*);
typedef void   (*BindBuffer_t)(GLenum, GLuint);
typedef void   (*BufferData_t)(GLenum, ptrdiff_t, const void*, GLenum);
typedef void   (*GenVertexArrays_t)(GLsizei, GLuint*);
typedef void   (*BindVertexArray_t)(GLuint);
typedef void   (*EnableVAA_t)(GLuint);
typedef void   (*VertexAttribPointer_t)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void   (*ActiveTexture_t)(GLenum);

#define W 256
#define H 256
#define GETP(T, n) (T)glXGetProcAddressARB((const GLubyte*)n)

static const char *VS =
    "#version 330 core\n"
    "const vec2 P[3] = vec2[3](vec2(-1,-1), vec2(3,-1), vec2(-1,3));\n"
    "out vec2 SCREEN_UV;\n"
    "void main(){\n"
    "  vec2 p = P[gl_VertexID];\n"
    "  SCREEN_UV = p * 0.5 + 0.5;\n"
    "  gl_Position = vec4(p, 0.0, 1.0);\n"
    "}\n";

// Mirrors the reporter's Proximity Fade shader:
//   uniform sampler2D depth_texture : hint_depth_texture;
//   float depth = texture(depth_texture, SCREEN_UV).x;
static const char *FS =
    "#version 330 core\n"
    "in vec2 SCREEN_UV;\n"
    "out vec4 FragColor;\n"
    "uniform sampler2D depth_texture;\n"
    "uniform sampler2D back_buffer;\n"
    "void main(){\n"
    "  float depth = texture(depth_texture, SCREEN_UV).x;\n"
    "  vec3 bb = texture(back_buffer, SCREEN_UV).rgb;\n"
    "  float alpha = clamp(1.0 - smoothstep(0.0, 0.1, depth), 0.0, 1.0);\n"
    "  FragColor = vec4(bb, 1.0) + vec4(0.0, alpha * 0.001, 0.0, 0.0);\n"
    "}\n";

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }

    int attrs[] = {
        GLX_X_RENDERABLE,  True,
        GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_RENDER_TYPE,   GLX_RGBA_BIT,
        GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8, GLX_ALPHA_SIZE, 8,
        GLX_DEPTH_SIZE, 24, GLX_STENCIL_SIZE, 8,
        GLX_DOUBLEBUFFER, True,
        None
    };
    int n = 0;
    GLXFBConfig* fbc = glXChooseFBConfig(dpy, DefaultScreen(dpy), attrs, &n);
    if (!fbc || n == 0) { fprintf(stderr, "no FBConfig\n"); return 1; }

    XVisualInfo* vi = glXGetVisualFromFBConfig(dpy, fbc[0]);
    Window root = RootWindow(dpy, vi->screen);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    Window win = XCreateWindow(dpy, root, 0, 0, W, H, 0, vi->depth,
                               InputOutput, vi->visual, CWColormap, &swa);
    XMapWindow(dpy, win);

    CreateCtx_t create_ctx = GETP(CreateCtx_t, "glXCreateContextAttribsARB");
    int ca[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        0
    };
    GLXContext ctx = create_ctx(dpy, fbc[0], 0, True, ca);
    if (!ctx) { fprintf(stderr, "ctx create failed\n"); return 1; }
    glXMakeCurrent(dpy, win, ctx);

    GenFB_t   gen_fb    = GETP(GenFB_t,   "glGenFramebuffers");
    BindFB_t  bind_fb   = GETP(BindFB_t,  "glBindFramebuffer");
    FBTex2D_t fb_tex2d  = GETP(FBTex2D_t, "glFramebufferTexture2D");
    CheckFB_t check_fb  = GETP(CheckFB_t, "glCheckFramebufferStatus");
    Blit_t    blit_fb   = GETP(Blit_t,    "glBlitFramebuffer");
    CreateShader_t create_shader = GETP(CreateShader_t, "glCreateShader");
    ShaderSource_t shader_source = GETP(ShaderSource_t, "glShaderSource");
    CompileShader_t compile_shader = GETP(CompileShader_t, "glCompileShader");
    CreateProgram_t create_program = GETP(CreateProgram_t, "glCreateProgram");
    AttachShader_t attach_shader = GETP(AttachShader_t, "glAttachShader");
    LinkProgram_t  link_program  = GETP(LinkProgram_t,  "glLinkProgram");
    UseProgram_t   use_program   = GETP(UseProgram_t,   "glUseProgram");
    GetUniformLocation_t get_uni = GETP(GetUniformLocation_t, "glGetUniformLocation");
    Uniform1i_t    uniform_1i    = GETP(Uniform1i_t,    "glUniform1i");
    GenVertexArrays_t gen_vao    = GETP(GenVertexArrays_t, "glGenVertexArrays");
    BindVertexArray_t bind_vao   = GETP(BindVertexArray_t, "glBindVertexArray");
    ActiveTexture_t active_tex   = GETP(ActiveTexture_t, "glActiveTexture");

    // Back-buffer color attachment.
    GLuint color_tex;
    glGenTextures(1, &color_tex);
    glBindTexture(GL_TEXTURE_2D, color_tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, W, H, 0,
                 GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);

    // Back-buffer depth/stencil attachment — 3D-scaling code path's
    // pixel-`type` argument.
    GLuint ds_tex;
    glGenTextures(1, &ds_tex);
    glBindTexture(GL_TEXTURE_2D, ds_tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH24_STENCIL8, W, H, 0,
                 GL_DEPTH_STENCIL,
                 GL_FLOAT,
                 NULL);
    GLenum tex_err = glGetError();
    fprintf(stderr, "glTexImage2D(depth/stencil) err=0x%04X\n", tex_err);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);

    GLuint fbo;
    gen_fb(1, &fbo);
    bind_fb(GL_FRAMEBUFFER, fbo);
    fb_tex2d(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
             GL_TEXTURE_2D, color_tex, 0);
    fb_tex2d(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT,
             GL_TEXTURE_2D, ds_tex, 0);

    GLenum status = check_fb(GL_FRAMEBUFFER);
    fprintf(stderr, "FBO status=0x%04X\n", status);

    // Paint default framebuffer black.
    bind_fb(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, W, H);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    // Paint the back buffer green.
    bind_fb(GL_FRAMEBUFFER, fbo);
    glClearColor(0.0f, 1.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    // Blit back-buffer → default fb.
    bind_fb(GL_READ_FRAMEBUFFER, fbo);
    bind_fb(GL_DRAW_FRAMEBUFFER, 0);
    blit_fb(0, 0, W, H, 0, 0, W, H, GL_COLOR_BUFFER_BIT, GL_NEAREST);

    // Proximity-fade-style pass: sample the back-buffer color and the
    // depth texture that the back-buffer is supposed to own.
    GLuint vs = create_shader(GL_VERTEX_SHADER);
    shader_source(vs, 1, &VS, NULL); compile_shader(vs);
    GLuint fs = create_shader(GL_FRAGMENT_SHADER);
    shader_source(fs, 1, &FS, NULL); compile_shader(fs);
    GLuint prog = create_program();
    attach_shader(prog, vs); attach_shader(prog, fs);
    link_program(prog);

    GLuint vao;
    gen_vao(1, &vao);
    bind_vao(vao);

    bind_fb(GL_FRAMEBUFFER, 0);
    use_program(prog);
    uniform_1i(get_uni(prog, "depth_texture"), 0);
    uniform_1i(get_uni(prog, "back_buffer"),   1);
    active_tex(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, ds_tex);
    active_tex(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, color_tex);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    glFinish();

    unsigned char px[4] = {0};
    glReadPixels(W / 2, H / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    fprintf(stderr, "center pixel=%u,%u,%u,%u\n",
            px[0], px[1], px[2], px[3]);

    glXSwapBuffers(dpy, win);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}
