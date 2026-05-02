// SOURCE: https://github.com/pmndrs/postprocessing/issues/426
//
// Repro: postprocessing's DepthOfFieldEffect CoC shader treated scene depth
// as linear in [near,far] when the PERSPECTIVE_CAMERA define was missing.
// The depth buffer under perspective projection is nonlinear, so converting
// a world focus distance linearly between near/far produces a target depth
// that only matches the buffer's stored value at the endpoints (near, far).
// Mid-range fragments that ARE at the focus distance appear strongly out of
// focus because CoC = |buffer_depth - linear_focus_depth| is large there.
//
// Setup: a fullscreen plane at view-space z = -5.5 under a perspective
// projection with near=1, far=10. Focus distance uniform is 5.5, so the
// center pixel SHOULD be exactly in focus (CoC=0 → R=0). With the bug,
// the plane's depth-buffer value is ~0.909 while the computed focus depth
// is 0.5, so CoC≈0.409 and R≈104.

#define GL_GLEXT_PROTOTYPES
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>

typedef GLXContext (*glXCreateContextAttribsARBProc)(Display*, GLXFBConfig, GLXContext, Bool, const int*);
#define GLX_CONTEXT_MAJOR_VERSION_ARB     0x2091
#define GLX_CONTEXT_MINOR_VERSION_ARB     0x2092
#define GLX_CONTEXT_PROFILE_MASK_ARB      0x9126
#define GLX_CONTEXT_CORE_PROFILE_BIT_ARB  0x00000001

static const int W = 128, H = 128;

static const char* VS_PLANE =
    "#version 330 core\n"
    "layout(location=0) in vec3 aPos;\n"
    "uniform mat4 uProj;\n"
    "void main(){ gl_Position = uProj * vec4(aPos, 1.0); }\n";

static const char* FS_PLANE =
    "#version 330 core\n"
    "out vec4 o;\n"
    "void main(){ o = vec4(1.0); }\n";

static const char* VS_COC =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "out vec2 vUv;\n"
    "void main(){ vUv = aPos*0.5 + 0.5; gl_Position = vec4(aPos, 0.0, 1.0); }\n";

// Ported from postprocessing's CircleOfConfusionMaterial with the
// PERSPECTIVE_CAMERA define OFF: the shader consumes the depth texel as
// if it were an orthographic (linear in near..far) depth. Under a real
// perspective projection this is a category error.
static const char* FS_COC =
    "#version 330 core\n"
    "in vec2 vUv;\n"
    "out vec4 o;\n"
    "uniform sampler2D uDepth;\n"
    "uniform float uNear;\n"
    "uniform float uFar;\n"
    "uniform float uFocusDist;\n"
    "float getViewZ(float depth){\n"
    "    // With PERSPECTIVE_CAMERA: would be (near*far)/((far-near)*depth - far).\n"
    "    // Without: treat as orthographic -> depth already linear in [0,1].\n"
    "    return -mix(uNear, uFar, depth);\n"
    "}\n"
    "float toOrtho(float viewZ){ return (viewZ + uNear) / (uNear - uFar); }\n"
    "void main(){\n"
    "    float d = texture(uDepth, vUv).r;\n"
    "    float fragOrtho = toOrtho(getViewZ(d));\n"
    "    float focusOrtho = toOrtho(-uFocusDist);\n"
    "    float coc = abs(fragOrtho - focusOrtho);\n"
    "    o = vec4(coc, 0.0, 0.0, 1.0);\n"
    "}\n";

static GLuint compile(GLenum type, const char* src) {
    GLuint sh = glCreateShader(type);
    glShaderSource(sh, 1, &src, NULL);
    glCompileShader(sh);
    GLint ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog(sh, sizeof(log), NULL, log);
        fprintf(stderr, "shader compile failed: %s\n", log);
        exit(1);
    }
    return sh;
}

static GLuint linkProg(const char* vs, const char* fs) {
    GLuint v = compile(GL_VERTEX_SHADER, vs);
    GLuint f = compile(GL_FRAGMENT_SHADER, fs);
    GLuint p = glCreateProgram();
    glAttachShader(p, v); glAttachShader(p, f);
    glLinkProgram(p);
    return p;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }

    int visAttrs[] = {
        GLX_X_RENDERABLE, True, GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_RENDER_TYPE,  GLX_RGBA_BIT,
        GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8, GLX_ALPHA_SIZE, 8,
        GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, True, None
    };
    int fbcount = 0;
    GLXFBConfig* fbc = glXChooseFBConfig(dpy, DefaultScreen(dpy), visAttrs, &fbcount);
    if (!fbc || fbcount == 0) { fprintf(stderr, "no FBConfig\n"); return 1; }

    XVisualInfo* vi = glXGetVisualFromFBConfig(dpy, fbc[0]);
    XSetWindowAttributes swa;
    memset(&swa, 0, sizeof(swa));
    swa.colormap = XCreateColormap(dpy, RootWindow(dpy, vi->screen), vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, RootWindow(dpy, vi->screen), 0, 0, W, H, 0,
                               vi->depth, InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    XSync(dpy, False);

    glXCreateContextAttribsARBProc glXCreateContextAttribsARB =
        (glXCreateContextAttribsARBProc)
        glXGetProcAddressARB((const GLubyte*)"glXCreateContextAttribsARB");
    int ctxAttrs[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3, GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB,  GLX_CONTEXT_CORE_PROFILE_BIT_ARB, None
    };
    GLXContext ctx = glXCreateContextAttribsARB(dpy, fbc[0], 0, True, ctxAttrs);
    glXMakeCurrent(dpy, win, ctx);

    // Offscreen FBO: color + depth, so the CoC pass can sample scene depth.
    GLuint colorTex, depthTex, fbo;
    glGenTextures(1, &colorTex);
    glBindTexture(GL_TEXTURE_2D, colorTex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, W, H, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glGenTextures(1, &depthTex);
    glBindTexture(GL_TEXTURE_2D, depthTex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT24, W, H, 0,
                 GL_DEPTH_COMPONENT, GL_FLOAT, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, colorTex, 0);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_TEXTURE_2D, depthTex, 0);

    // Plane at view-space z = -5.5 (midway between near=1 and far=10).
    // Large XY extent so after projection it covers the viewport.
    float plane[] = {
        -100.0f, -100.0f, -5.5f,
         100.0f, -100.0f, -5.5f,
        -100.0f,  100.0f, -5.5f,
        -100.0f,  100.0f, -5.5f,
         100.0f, -100.0f, -5.5f,
         100.0f,  100.0f, -5.5f,
    };
    GLuint planeVao, planeVbo;
    glGenVertexArrays(1, &planeVao);
    glBindVertexArray(planeVao);
    glGenBuffers(1, &planeVbo);
    glBindBuffer(GL_ARRAY_BUFFER, planeVbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(plane), plane, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), (void*)0);
    glEnableVertexAttribArray(0);

    float quad[] = { -1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1 };
    GLuint quadVao, quadVbo;
    glGenVertexArrays(1, &quadVao);
    glBindVertexArray(quadVao);
    glGenBuffers(1, &quadVbo);
    glBindBuffer(GL_ARRAY_BUFFER, quadVbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), (void*)0);
    glEnableVertexAttribArray(0);

    GLuint progPlane = linkProg(VS_PLANE, FS_PLANE);
    GLuint progCoc   = linkProg(VS_COC,   FS_COC);

    const float nearP = 1.0f, farP = 10.0f;
    // Column-major perspective matrix (fovy=90°, aspect=1).
    float proj[16] = {0};
    proj[0]  = 1.0f;
    proj[5]  = 1.0f;
    proj[10] = -(farP + nearP) / (farP - nearP);
    proj[11] = -1.0f;
    proj[14] = -2.0f * farP * nearP / (farP - nearP);

    // --- Pass 1: render plane into FBO; depth buffer captures perspective depth. ---
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glViewport(0, 0, W, H);
    glEnable(GL_DEPTH_TEST);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glUseProgram(progPlane);
    glUniformMatrix4fv(glGetUniformLocation(progPlane, "uProj"), 1, GL_FALSE, proj);
    glBindVertexArray(planeVao);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    // --- Pass 2: CoC over the captured depth, output to window. ---
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, W, H);
    glDisable(GL_DEPTH_TEST);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(progCoc);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, depthTex);
    glUniform1i(glGetUniformLocation(progCoc, "uDepth"),     0);
    glUniform1f(glGetUniformLocation(progCoc, "uNear"),      nearP);
    glUniform1f(glGetUniformLocation(progCoc, "uFar"),       farP);
    glUniform1f(glGetUniformLocation(progCoc, "uFocusDist"), 5.5f);
    glBindVertexArray(quadVao);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glXSwapBuffers(dpy, win);
    glFinish();

    unsigned char px[4] = {0};
    glReadPixels(W / 2, H / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    fprintf(stderr, "center pixel: R=%u G=%u B=%u (CoC byte; 0 = in focus)\n",
            px[0], px[1], px[2]);

    glXMakeCurrent(dpy, 0, 0);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}