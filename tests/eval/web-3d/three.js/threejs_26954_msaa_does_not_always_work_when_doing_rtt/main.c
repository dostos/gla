// SOURCE: https://github.com/mrdoob/three.js/issues/26954
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <X11/Xlib.h>
#define GL_GLEXT_PROTOTYPES 1
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>

typedef GLXContext (*CtxAttribsProc)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

#define W 400
#define H 300

static int x_error_handler(Display *dpy, XErrorEvent *ev) {
    char buf[256];
    XGetErrorText(dpy, ev->error_code, buf, sizeof(buf));
    fprintf(stderr, "X Error: %s (%d/%d)\n", buf, ev->request_code, ev->minor_code);
    return 0;
}

static const char *VS_tri =
"#version 330 core\n"
"layout(location=0) in vec2 aPos;\n"
"void main(){ gl_Position = vec4(aPos, 0.0, 1.0); }\n";

static const char *FS_tri =
"#version 330 core\n"
"out vec4 o;\n"
"uniform vec3 uColor;\n"
"void main(){ o = vec4(uColor, 1.0); }\n";

static const char *VS_quad =
"#version 330 core\n"
"layout(location=0) in vec2 aPos;\n"
"out vec2 vUV;\n"
"void main(){ vUV = aPos * 0.5 + 0.5; gl_Position = vec4(aPos, 0.0, 1.0); }\n";

// Reinhard tone-map -- the same family of operator used by three.js OutputPass
// (ReinhardToneMapping / LinearToneMapping / ACESFilmicToneMapping share the
// property that the mapping is monotonic and saturates near 1.0 for large
// inputs). A Reinhard mapping of a >>1 value rounds to very close to 1.0.
static const char *FS_tonemap =
"#version 330 core\n"
"in vec2 vUV;\n"
"out vec4 o;\n"
"uniform sampler2D uTex;\n"
"void main(){\n"
"  vec3 c = texture(uTex, vUV).rgb;\n"
"  vec3 t = c / (1.0 + c);\n"
"  o = vec4(t, 1.0);\n"
"}\n";

static GLuint compile(GLenum type, const char *src) {
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok = 0;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[512];
        glGetShaderInfoLog(s, sizeof(log), NULL, log);
        fprintf(stderr, "shader: %s\n", log);
        exit(1);
    }
    return s;
}

static GLuint link_program(const char *vs_src, const char *fs_src) {
    GLuint vs = compile(GL_VERTEX_SHADER, vs_src);
    GLuint fs = compile(GL_FRAGMENT_SHADER, fs_src);
    GLuint p = glCreateProgram();
    glAttachShader(p, vs);
    glAttachShader(p, fs);
    glLinkProgram(p);
    glDeleteShader(vs);
    glDeleteShader(fs);
    return p;
}

int main(void) {
    XSetErrorHandler(x_error_handler);
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) return 1;

    int fb_attribs[] = {
        GLX_X_RENDERABLE, True,
        GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_RENDER_TYPE, GLX_RGBA_BIT,
        GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8,
        GLX_ALPHA_SIZE, 8, GLX_DEPTH_SIZE, 24,
        GLX_DOUBLEBUFFER, True, None
    };
    int fbcount = 0;
    GLXFBConfig *fbc = glXChooseFBConfig(dpy, DefaultScreen(dpy), fb_attribs, &fbcount);
    if (!fbc) return 1;
    XVisualInfo *vi = glXGetVisualFromFBConfig(dpy, fbc[0]);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    memset(&swa, 0, sizeof(swa));
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, W, H, 0, vi->depth,
                               InputOutput, vi->visual, CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    CtxAttribsProc glXCreateContextAttribsARB =
        (CtxAttribsProc) glXGetProcAddressARB((const GLubyte *)"glXCreateContextAttribsARB");
    int ctx_attribs[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        None
    };
    GLXContext ctx = glXCreateContextAttribsARB(dpy, fbc[0], 0, True, ctx_attribs);
    if (!ctx) return 1;
    glXMakeCurrent(dpy, win, ctx);

    // MSAA 4x RGBA16F color buffer -- matches three.js EffectComposer default
    // (HalfFloatType, samples=4) for postprocessing render targets.
    GLuint msaaFbo, msaaColor;
    glGenFramebuffers(1, &msaaFbo);
    glBindFramebuffer(GL_FRAMEBUFFER, msaaFbo);
    glGenRenderbuffers(1, &msaaColor);
    glBindRenderbuffer(GL_RENDERBUFFER, msaaColor);
    glRenderbufferStorageMultisample(GL_RENDERBUFFER, 4, GL_RGBA16F, W, H);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                              GL_RENDERBUFFER, msaaColor);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
        fprintf(stderr, "MSAA FBO incomplete\n"); return 1;
    }

    // Single-sample RGBA16F resolve target.
    GLuint resolveFbo, resolveTex;
    glGenFramebuffers(1, &resolveFbo);
    glBindFramebuffer(GL_FRAMEBUFFER, resolveFbo);
    glGenTextures(1, &resolveTex);
    glBindTexture(GL_TEXTURE_2D, resolveTex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, W, H, 0, GL_RGBA, GL_HALF_FLOAT, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_2D, resolveTex, 0);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
        fprintf(stderr, "resolve FBO incomplete\n"); return 1;
    }

    // Triangle with a crisp diagonal edge from (-1,+1) to (+1,-1) in NDC,
    // covering the lower-left half of the framebuffer.
    float tri[] = { -1.f, -1.f,   1.f, -1.f,   -1.f,  1.f };
    GLuint triVao, triVbo;
    glGenVertexArrays(1, &triVao); glBindVertexArray(triVao);
    glGenBuffers(1, &triVbo);
    glBindBuffer(GL_ARRAY_BUFFER, triVbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(tri), tri, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2*sizeof(float), NULL);

    float quad[] = {
        -1.f, -1.f,   1.f, -1.f,   -1.f, 1.f,
         1.f, -1.f,   1.f,  1.f,   -1.f, 1.f,
    };
    GLuint quadVao, quadVbo;
    glGenVertexArrays(1, &quadVao); glBindVertexArray(quadVao);
    glGenBuffers(1, &quadVbo);
    glBindBuffer(GL_ARRAY_BUFFER, quadVbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2*sizeof(float), NULL);

    GLuint triProg = link_program(VS_tri, FS_tri);
    GLuint tmProg  = link_program(VS_quad, FS_tonemap);

    // Pass 1: draw the triangle into the MSAA FP16 render target with a
    // strongly-lit color. A value of 20.0 per channel is in the range a
    // MeshStandardMaterial surface hits under AmbientLight(intensity ~= 10).
    glBindFramebuffer(GL_FRAMEBUFFER, msaaFbo);
    glViewport(0, 0, W, H);
    glDisable(GL_DEPTH_TEST);
    glClearColor(0.f, 0.f, 0.f, 1.f);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(triProg);
    glUniform3f(glGetUniformLocation(triProg, "uColor"), 20.f, 20.f, 20.f);
    glBindVertexArray(triVao);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    // Pass 2: resolve the 4 samples per pixel into the single-sample FP16
    // target (glBlitFramebuffer averages samples linearly).
    glBindFramebuffer(GL_READ_FRAMEBUFFER, msaaFbo);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, resolveFbo);
    glBlitFramebuffer(0, 0, W, H, 0, 0, W, H, GL_COLOR_BUFFER_BIT, GL_NEAREST);

    // Pass 3: tone-map the FP16 texture onto the default RGBA8 framebuffer.
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, W, H);
    glClearColor(0.f, 0.f, 0.f, 1.f);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(tmProg);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, resolveTex);
    glUniform1i(glGetUniformLocation(tmProg, "uTex"), 0);
    glBindVertexArray(quadVao);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glXSwapBuffers(dpy, win);

    // Read back: one pixel well inside the triangle and one pixel on the
    // diagonal edge. Printing coordinate-labelled rgba values only; no bug
    // interpretation.
    unsigned char px_inside[4] = {0}, px_edge[4] = {0};
    glReadBuffer(GL_BACK);
    glReadPixels(W/4, H/4, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px_inside);
    glReadPixels(W/2, H/2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px_edge);
    printf("r4: px(W/4,H/4) rgba=%u,%u,%u,%u  px(W/2,H/2) rgba=%u,%u,%u,%u\n",
           px_inside[0], px_inside[1], px_inside[2], px_inside[3],
           px_edge[0], px_edge[1], px_edge[2], px_edge[3]);

    glDeleteProgram(triProg); glDeleteProgram(tmProg);
    glDeleteBuffers(1, &triVbo); glDeleteBuffers(1, &quadVbo);
    glDeleteVertexArrays(1, &triVao); glDeleteVertexArrays(1, &quadVao);
    glDeleteTextures(1, &resolveTex);
    glDeleteRenderbuffers(1, &msaaColor);
    glDeleteFramebuffers(1, &msaaFbo);
    glDeleteFramebuffers(1, &resolveFbo);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XFreeColormap(dpy, swa.colormap);
    XFree(vi); XFree(fbc);
    XCloseDisplay(dpy);
    return 0;
}