// SOURCE: https://stackoverflow.com/questions/50444687/post-effects-and-transparent-background-in-three-js
// Minimal reproducer modeled on the three.js UnrealBloomPass setup.
//
// Pipeline:
//   1. Scene pass: draw a translucent quad into an RGBA8 FBO cleared to (0,0,0,0).
//   2. Blur pass: sample the scene texture with a 1-D gaussian.
//   3. Composite: additive blend the blurred result onto the default framebuffer
//      cleared to (0,0,0,0).

#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define GL_FRAMEBUFFER            0x8D40
#define GL_COLOR_ATTACHMENT0      0x8CE0
#define GL_ARRAY_BUFFER           0x8892
#define GL_STATIC_DRAW            0x88E4
#define GL_VERTEX_SHADER          0x8B31
#define GL_FRAGMENT_SHADER        0x8B30
#define GL_COMPILE_STATUS         0x8B81
#define GL_LINK_STATUS            0x8B82
#define GL_TEXTURE0               0x84C0

typedef char GLchar;
typedef ptrdiff_t GLintptr_compat;

typedef unsigned int (*PFNCREATESHADER)(unsigned int);
typedef void (*PFNSHADERSOURCE)(unsigned int, int, const GLchar *const*, const int*);
typedef void (*PFNCOMPILESHADER)(unsigned int);
typedef unsigned int (*PFNCREATEPROGRAM)(void);
typedef void (*PFNATTACHSHADER)(unsigned int, unsigned int);
typedef void (*PFNLINKPROGRAM)(unsigned int);
typedef void (*PFNUSEPROGRAM)(unsigned int);
typedef void (*PFNGENBUFFERS)(int, unsigned int*);
typedef void (*PFNBINDBUFFER)(unsigned int, unsigned int);
typedef void (*PFNBUFFERDATA)(unsigned int, long, const void*, unsigned int);
typedef void (*PFNGENVERTEXARRAYS)(int, unsigned int*);
typedef void (*PFNBINDVERTEXARRAY)(unsigned int);
typedef void (*PFNENABLEVERTEXATTRIBARRAY)(unsigned int);
typedef void (*PFNVERTEXATTRIBPOINTER)(unsigned int, int, unsigned int, unsigned char, int, const void*);
typedef void (*PFNGENFRAMEBUFFERS)(int, unsigned int*);
typedef void (*PFNBINDFRAMEBUFFER)(unsigned int, unsigned int);
typedef void (*PFNFRAMEBUFFERTEXTURE2D)(unsigned int, unsigned int, unsigned int, unsigned int, int);
typedef int (*PFNGETUNIFORMLOCATION)(unsigned int, const GLchar*);
typedef void (*PFNUNIFORM1I)(int, int);
typedef void (*PFNUNIFORM2F)(int, float, float);
typedef void (*PFNACTIVETEXTURE)(unsigned int);

static PFNCREATESHADER glCreateShader_;
static PFNSHADERSOURCE glShaderSource_;
static PFNCOMPILESHADER glCompileShader_;
static PFNCREATEPROGRAM glCreateProgram_;
static PFNATTACHSHADER glAttachShader_;
static PFNLINKPROGRAM glLinkProgram_;
static PFNUSEPROGRAM glUseProgram_;
static PFNGENBUFFERS glGenBuffers_;
static PFNBINDBUFFER glBindBuffer_;
static PFNBUFFERDATA glBufferData_;
static PFNGENVERTEXARRAYS glGenVertexArrays_;
static PFNBINDVERTEXARRAY glBindVertexArray_;
static PFNENABLEVERTEXATTRIBARRAY glEnableVertexAttribArray_;
static PFNVERTEXATTRIBPOINTER glVertexAttribPointer_;
static PFNGENFRAMEBUFFERS glGenFramebuffers_;
static PFNBINDFRAMEBUFFER glBindFramebuffer_;
static PFNFRAMEBUFFERTEXTURE2D glFramebufferTexture2D_;
static PFNGETUNIFORMLOCATION glGetUniformLocation_;
static PFNUNIFORM1I glUniform1i_;
static PFNUNIFORM2F glUniform2f_;
static PFNACTIVETEXTURE glActiveTexture_;

#define LOAD(name) name##_ = (PFN##name##_TYPE_PLACEHOLDER)glXGetProcAddressARB((const GLubyte*)#name)

static void* load(const char* n) { return (void*)glXGetProcAddressARB((const GLubyte*)n); }

static unsigned int make_program(const char* vs, const char* fs) {
    unsigned int v = glCreateShader_(GL_VERTEX_SHADER);
    glShaderSource_(v, 1, &vs, NULL); glCompileShader_(v);
    unsigned int f = glCreateShader_(GL_FRAGMENT_SHADER);
    glShaderSource_(f, 1, &fs, NULL); glCompileShader_(f);
    unsigned int p = glCreateProgram_();
    glAttachShader_(p, v); glAttachShader_(p, f); glLinkProgram_(p);
    return p;
}

static const char* vs_quad =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "out vec2 vUv;\n"
    "void main(){ vUv = aPos*0.5+0.5; gl_Position = vec4(aPos,0,1);}";

static const char* fs_scene =
    "#version 330 core\n"
    "in vec2 vUv; out vec4 o;\n"
    "void main(){\n"
    "  float d = distance(vUv, vec2(0.5));\n"
    "  float a = smoothstep(0.4, 0.1, d);\n"
    "  o = vec4(1.0, 0.2, 0.3, a);\n"
    "}";

static const char* fs_blur =
    "#version 330 core\n"
    "in vec2 vUv; out vec4 o;\n"
    "uniform sampler2D tex; uniform vec2 dir; uniform vec2 texSize;\n"
    "float gpdf(float x, float s){ return 0.39894*exp(-0.5*x*x/(s*s))/s; }\n"
    "void main(){\n"
    "  vec2 inv = 1.0/texSize; float sigma = 4.0;\n"
    "  float w = gpdf(0.0, sigma);\n"
    "  vec3 sum = texture(tex, vUv).rgb * w; float wsum = w;\n"
    "  for(int i=1;i<8;i++){\n"
    "    float x=float(i); float ww=gpdf(x, sigma); vec2 off=dir*inv*x;\n"
    "    sum += texture(tex, vUv+off).rgb*ww;\n"
    "    sum += texture(tex, vUv-off).rgb*ww;\n"
    "    wsum += ww*2.0;\n"
    "  }\n"
    "  o = vec4(sum/wsum, 1.0);\n"
    "}";

static const char* fs_copy =
    "#version 330 core\n"
    "in vec2 vUv; out vec4 o; uniform sampler2D tex;\n"
    "void main(){ o = texture(tex, vUv); }";

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    int attribs[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_RED_SIZE,8, GLX_GREEN_SIZE,8,
                      GLX_BLUE_SIZE,8, GLX_ALPHA_SIZE,8, GLX_DEPTH_SIZE,24, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, attribs);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0,0,256,256,0, vi->depth, InputOutput,
                               vi->visual, CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    glCreateShader_ = load("glCreateShader");
    glShaderSource_ = load("glShaderSource");
    glCompileShader_ = load("glCompileShader");
    glCreateProgram_ = load("glCreateProgram");
    glAttachShader_ = load("glAttachShader");
    glLinkProgram_ = load("glLinkProgram");
    glUseProgram_ = load("glUseProgram");
    glGenBuffers_ = load("glGenBuffers");
    glBindBuffer_ = load("glBindBuffer");
    glBufferData_ = load("glBufferData");
    glGenVertexArrays_ = load("glGenVertexArrays");
    glBindVertexArray_ = load("glBindVertexArray");
    glEnableVertexAttribArray_ = load("glEnableVertexAttribArray");
    glVertexAttribPointer_ = load("glVertexAttribPointer");
    glGenFramebuffers_ = load("glGenFramebuffers");
    glBindFramebuffer_ = load("glBindFramebuffer");
    glFramebufferTexture2D_ = load("glFramebufferTexture2D");
    glGetUniformLocation_ = load("glGetUniformLocation");
    glUniform1i_ = load("glUniform1i");
    glUniform2f_ = load("glUniform2f");
    glActiveTexture_ = load("glActiveTexture");

    unsigned int vao, vbo;
    glGenVertexArrays_(1, &vao); glBindVertexArray_(vao);
    glGenBuffers_(1, &vbo); glBindBuffer_(GL_ARRAY_BUFFER, vbo);
    float quad[] = { -1,-1,  1,-1,  -1,1,  -1,1,  1,-1,  1,1 };
    glBufferData_(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glEnableVertexAttribArray_(0);
    glVertexAttribPointer_(0, 2, GL_FLOAT, 0, 8, 0);

    unsigned int scene_tex, blur_tex, scene_fbo, blur_fbo;
    glGenTextures(1, &scene_tex); glBindTexture(GL_TEXTURE_2D, scene_tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 256,256, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glGenTextures(1, &blur_tex); glBindTexture(GL_TEXTURE_2D, blur_tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 256,256, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);

    glGenFramebuffers_(1, &scene_fbo); glBindFramebuffer_(GL_FRAMEBUFFER, scene_fbo);
    glFramebufferTexture2D_(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, scene_tex, 0);
    glGenFramebuffers_(1, &blur_fbo); glBindFramebuffer_(GL_FRAMEBUFFER, blur_fbo);
    glFramebufferTexture2D_(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, blur_tex, 0);

    unsigned int p_scene = make_program(vs_quad, fs_scene);
    unsigned int p_blur  = make_program(vs_quad, fs_blur);
    unsigned int p_copy  = make_program(vs_quad, fs_copy);

    // 1) Scene pass
    glBindFramebuffer_(GL_FRAMEBUFFER, scene_fbo);
    glViewport(0,0,256,256);
    glClearColor(0,0,0,0); glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram_(p_scene);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    // 2) Blur pass
    glBindFramebuffer_(GL_FRAMEBUFFER, blur_fbo);
    glClearColor(0,0,0,0); glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram_(p_blur);
    glActiveTexture_(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, scene_tex);
    glUniform1i_(glGetUniformLocation_(p_blur, "tex"), 0);
    glUniform2f_(glGetUniformLocation_(p_blur, "dir"), 1.0f, 0.0f);
    glUniform2f_(glGetUniformLocation_(p_blur, "texSize"), 256.0f, 256.0f);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    // 3) Composite to default framebuffer (cleared to transparent)
    glBindFramebuffer_(GL_FRAMEBUFFER, 0);
    glClearColor(0,0,0,0); glClear(GL_COLOR_BUFFER_BIT);
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE);  // additive, like bloom composite
    glUseProgram_(p_copy);
    glActiveTexture_(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, blur_tex);
    glUniform1i_(glGetUniformLocation_(p_copy, "tex"), 0);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glXSwapBuffers(dpy, win);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}