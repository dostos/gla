// SOURCE: https://github.com/mrdoob/three.js/issues/32585
#define GL_GLEXT_PROTOTYPES
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <GL/glext.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static PFNGLCREATESHADERPROC glCreateShader_;
static PFNGLSHADERSOURCEPROC glShaderSource_;
static PFNGLCOMPILESHADERPROC glCompileShader_;
static PFNGLCREATEPROGRAMPROC glCreateProgram_;
static PFNGLATTACHSHADERPROC glAttachShader_;
static PFNGLLINKPROGRAMPROC glLinkProgram_;
static PFNGLUSEPROGRAMPROC glUseProgram_;
static PFNGLGENVERTEXARRAYSPROC glGenVertexArrays_;
static PFNGLBINDVERTEXARRAYPROC glBindVertexArray_;
static PFNGLGENBUFFERSPROC glGenBuffers_;
static PFNGLBINDBUFFERPROC glBindBuffer_;
static PFNGLBUFFERDATAPROC glBufferData_;
static PFNGLVERTEXATTRIBPOINTERPROC glVertexAttribPointer_;
static PFNGLENABLEVERTEXATTRIBARRAYPROC glEnableVertexAttribArray_;
static PFNGLVERTEXATTRIBDIVISORPROC glVertexAttribDivisor_;
static PFNGLDRAWARRAYSINSTANCEDPROC glDrawArraysInstanced_;
static PFNGLGETUNIFORMLOCATIONPROC glGetUniformLocation_;
static PFNGLUNIFORMMATRIX4FVPROC glUniformMatrix4fv_;
static PFNGLGENFRAMEBUFFERSPROC glGenFramebuffers_;
static PFNGLBINDFRAMEBUFFERPROC glBindFramebuffer_;
static PFNGLFRAMEBUFFERTEXTURE2DPROC glFramebufferTexture2D_;
static PFNGLDRAWBUFFERSPROC glDrawBuffers_;

#define LOAD(NAME) NAME##_ = (typeof(NAME##_))glXGetProcAddressARB((const GLubyte*)#NAME)

static const char *VS =
    "#version 330 core\n"
    "layout(location=0) in vec3 a_pos;\n"
    "layout(location=1) in mat4 a_instanceMatrix;\n"
    "uniform mat4 u_viewProj;\n"
    "uniform mat4 u_prevViewProj;\n"
    "out vec4 v_curClip;\n"
    "out vec4 v_prevClip;\n"
    "void main(){\n"
    "  vec4 world = a_instanceMatrix * vec4(a_pos, 1.0);\n"
    "  v_curClip  = u_viewProj     * world;\n"
    "  v_prevClip = u_prevViewProj * world;\n"
    "  gl_Position = v_curClip;\n"
    "}\n";

static const char *FS =
    "#version 330 core\n"
    "in vec4 v_curClip;\n"
    "in vec4 v_prevClip;\n"
    "layout(location=0) out vec4 o_color;\n"
    "layout(location=1) out vec4 o_velocity;\n"
    "void main(){\n"
    "  vec2 cur  = v_curClip.xy  / v_curClip.w;\n"
    "  vec2 prev = v_prevClip.xy / v_prevClip.w;\n"
    "  vec2 vel  = (cur - prev) * 0.5;\n"
    "  o_color    = vec4(0.2, 0.8, 0.4, 1.0);\n"
    "  o_velocity = vec4(vel, 0.0, 1.0);\n"
    "}\n";

static GLuint compile(GLenum stage, const char *src){
    GLuint s = glCreateShader_(stage);
    glShaderSource_(s, 1, &src, NULL);
    glCompileShader_(s);
    return s;
}

static void identity(float *m){
    memset(m, 0, 16 * sizeof(float));
    m[0] = m[5] = m[10] = m[15] = 1.0f;
}

int main(void){
    Display *dpy = XOpenDisplay(NULL);
    if(!dpy){ fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int attribs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo *vi = glXChooseVisual(dpy, 0, attribs);
    if(!vi){ fprintf(stderr, "glXChooseVisual failed\n"); return 1; }
    Colormap cmap = XCreateColormap(dpy, RootWindow(dpy, vi->screen), vi->visual, AllocNone);
    XSetWindowAttributes swa = {0};
    swa.colormap = cmap; swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, RootWindow(dpy, vi->screen), 0, 0, 256, 256,
                               0, vi->depth, InputOutput, vi->visual,
                               CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    LOAD(glCreateShader); LOAD(glShaderSource); LOAD(glCompileShader);
    LOAD(glCreateProgram); LOAD(glAttachShader); LOAD(glLinkProgram);
    LOAD(glUseProgram); LOAD(glGenVertexArrays); LOAD(glBindVertexArray);
    LOAD(glGenBuffers); LOAD(glBindBuffer); LOAD(glBufferData);
    LOAD(glVertexAttribPointer); LOAD(glEnableVertexAttribArray);
    LOAD(glVertexAttribDivisor); LOAD(glDrawArraysInstanced);
    LOAD(glGetUniformLocation); LOAD(glUniformMatrix4fv);
    LOAD(glGenFramebuffers); LOAD(glBindFramebuffer);
    LOAD(glFramebufferTexture2D); LOAD(glDrawBuffers);

    GLuint vs = compile(GL_VERTEX_SHADER, VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    GLuint prog = glCreateProgram_();
    glAttachShader_(prog, vs); glAttachShader_(prog, fs);
    glLinkProgram_(prog);

    float verts[] = {
        -0.15f, -0.15f, 0.0f,
         0.15f, -0.15f, 0.0f,
         0.00f,  0.15f, 0.0f,
    };
    GLuint vao, vbo;
    glGenVertexArrays_(1, &vao);
    glBindVertexArray_(vao);
    glGenBuffers_(1, &vbo);
    glBindBuffer_(GL_ARRAY_BUFFER, vbo);
    glBufferData_(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glVertexAttribPointer_(0, 3, GL_FLOAT, GL_FALSE, 0, 0);
    glEnableVertexAttribArray_(0);

    // One instance: world transform at the current frame.
    float instanceMatrix[16];
    identity(instanceMatrix);
    instanceMatrix[12] = 0.3f;
    GLuint ibo;
    glGenBuffers_(1, &ibo);
    glBindBuffer_(GL_ARRAY_BUFFER, ibo);
    glBufferData_(GL_ARRAY_BUFFER, sizeof(instanceMatrix), instanceMatrix, GL_STATIC_DRAW);
    for(int i = 0; i < 4; i++){
        glVertexAttribPointer_(1 + i, 4, GL_FLOAT, GL_FALSE,
                               16 * sizeof(float),
                               (void*)(i * 4 * sizeof(float)));
        glEnableVertexAttribArray_(1 + i);
        glVertexAttribDivisor_(1 + i, 1);
    }

    GLuint fbo;
    glGenFramebuffers_(1, &fbo);
    glBindFramebuffer_(GL_FRAMEBUFFER, fbo);

    GLuint texColor, texVelocity;
    glGenTextures(1, &texColor);
    glBindTexture(GL_TEXTURE_2D, texColor);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 256, 256, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glFramebufferTexture2D_(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texColor, 0);

    glGenTextures(1, &texVelocity);
    glBindTexture(GL_TEXTURE_2D, texVelocity);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, 256, 256, 0, GL_RGBA, GL_FLOAT, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glFramebufferTexture2D_(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT1, GL_TEXTURE_2D, texVelocity, 0);

    GLenum bufs[2] = { GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1 };
    glDrawBuffers_(2, bufs);

    float viewProj[16];
    float prevViewProj[16];
    identity(viewProj);
    identity(prevViewProj);

    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    glUseProgram_(prog);
    glUniformMatrix4fv_(glGetUniformLocation_(prog, "u_viewProj"),     1, GL_FALSE, viewProj);
    glUniformMatrix4fv_(glGetUniformLocation_(prog, "u_prevViewProj"), 1, GL_FALSE, prevViewProj);

    glBindVertexArray_(vao);
    glDrawArraysInstanced_(GL_TRIANGLES, 0, 3, 1);

    float pix[4] = {0};
    glReadBuffer(GL_COLOR_ATTACHMENT1);
    glReadPixels(166, 128, 1, 1, GL_RGBA, GL_FLOAT, pix);
    fprintf(stdout, "velocity_sample rgba=%.4f,%.4f,%.4f,%.4f\n",
            pix[0], pix[1], pix[2], pix[3]);

    glBindFramebuffer_(GL_FRAMEBUFFER, 0);
    glXSwapBuffers(dpy, win);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}