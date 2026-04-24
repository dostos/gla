// SOURCE: https://github.com/pmndrs/postprocessing/issues/526
#include <GL/gl.h>
#include <GL/glx.h>
#include <GL/glext.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define GL_FUNCS(X) \
    X(PFNGLCREATESHADERPROC, CreateShader) \
    X(PFNGLSHADERSOURCEPROC, ShaderSource) \
    X(PFNGLCOMPILESHADERPROC, CompileShader) \
    X(PFNGLGETSHADERIVPROC, GetShaderiv) \
    X(PFNGLGETSHADERINFOLOGPROC, GetShaderInfoLog) \
    X(PFNGLCREATEPROGRAMPROC, CreateProgram) \
    X(PFNGLATTACHSHADERPROC, AttachShader) \
    X(PFNGLLINKPROGRAMPROC, LinkProgram) \
    X(PFNGLUSEPROGRAMPROC, UseProgram) \
    X(PFNGLGENVERTEXARRAYSPROC, GenVertexArrays) \
    X(PFNGLBINDVERTEXARRAYPROC, BindVertexArray) \
    X(PFNGLGENBUFFERSPROC, GenBuffers) \
    X(PFNGLBINDBUFFERPROC, BindBuffer) \
    X(PFNGLBUFFERDATAPROC, BufferData) \
    X(PFNGLVERTEXATTRIBPOINTERPROC, VertexAttribPointer) \
    X(PFNGLENABLEVERTEXATTRIBARRAYPROC, EnableVertexAttribArray) \
    X(PFNGLGENFRAMEBUFFERSPROC, GenFramebuffers) \
    X(PFNGLBINDFRAMEBUFFERPROC, BindFramebuffer) \
    X(PFNGLFRAMEBUFFERTEXTURE2DPROC, FramebufferTexture2D) \
    X(PFNGLCHECKFRAMEBUFFERSTATUSPROC, CheckFramebufferStatus) \
    X(PFNGLGETUNIFORMLOCATIONPROC, GetUniformLocation) \
    X(PFNGLUNIFORM1IPROC, Uniform1i) \
    X(PFNGLUNIFORM1FPROC, Uniform1f)

#define DECL(type, name) static type pgl##name;
GL_FUNCS(DECL)
#undef DECL

static void load_gl(void) {
#define LOAD(type, name) pgl##name = (type)glXGetProcAddressARB((const GLubyte*)"gl" #name);
    GL_FUNCS(LOAD)
#undef LOAD
}

static const char* vs_src =
"#version 330 core\n"
"layout(location=0) in vec2 pos;\n"
"out vec2 uv;\n"
"void main(){ uv = pos*0.5+0.5; gl_Position = vec4(pos,0.0,1.0); }\n";

static const char* fs_irradiance_src =
"#version 330 core\n"
"in vec2 uv; out vec4 frag;\n"
"uniform float lobe;\n"
"// Evaluate a spherical-harmonic-like basis. Coefficients are the kind of\n"
"// values a probe capture can produce when baked from a high-contrast\n"
"// environment; the linear basis terms are signed.\n"
"vec3 shEvaluate(vec3 n){\n"
"    vec3 c0 = vec3(0.25, 0.25, 0.25);\n"
"    vec3 c1 = vec3(0.40, 0.10, 0.00);\n"
"    vec3 c2 = vec3(0.00, 0.30, 0.20);\n"
"    vec3 c3 = vec3(0.10, 0.00, 0.40);\n"
"    return c0 + c1*n.x + c2*n.y + c3*n.z;\n"
"}\n"
"void main(){\n"
"    vec3 n = normalize(vec3(uv*2.0-1.0, lobe));\n"
"    vec3 irradiance = shEvaluate(n);\n"
"    frag = vec4(irradiance, 1.0);\n"
"}\n";

static const char* fs_bright_src =
"#version 330 core\n"
"in vec2 uv; out vec4 frag;\n"
"uniform sampler2D src;\n"
"// Bloom-style bright pass. Operates on HDR input and assumes non-negative\n"
"// radiance (uses sqrt for tonemap weighting).\n"
"void main(){\n"
"    vec3 c = texture(src, uv).rgb;\n"
"    float lum = dot(c, vec3(0.2126, 0.7152, 0.0722));\n"
"    vec3 bright = c * sqrt(max(lum - 0.05, 0.0));\n"
"    vec3 tone = sqrt(c);\n"
"    frag = vec4(tone + bright, 1.0);\n"
"}\n";

static GLuint compile(GLenum kind, const char* src) {
    GLuint s = pglCreateShader(kind);
    pglShaderSource(s, 1, &src, NULL);
    pglCompileShader(s);
    GLint ok = 0;
    pglGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[2048]; pglGetShaderInfoLog(s, sizeof log, NULL, log);
        fprintf(stderr, "shader compile error: %s\n", log);
        exit(2);
    }
    return s;
}

static GLuint link2(GLuint vs, GLuint fs) {
    GLuint p = pglCreateProgram();
    pglAttachShader(p, vs);
    pglAttachShader(p, fs);
    pglLinkProgram(p);
    return p;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }

    int attribs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attribs);
    if (!vi) { fprintf(stderr, "glXChooseVisual failed\n"); return 1; }

    Window root = RootWindow(dpy, vi->screen);
    Colormap cmap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    XSetWindowAttributes swa = {0};
    swa.colormap = cmap;
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 256, 256, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);
    load_gl();

    GLuint vao; pglGenVertexArrays(1, &vao); pglBindVertexArray(vao);
    GLuint vbo; pglGenBuffers(1, &vbo); pglBindBuffer(GL_ARRAY_BUFFER, vbo);
    float quad[] = { -1,-1,  1,-1, -1,1,   -1,1,  1,-1,  1,1 };
    pglBufferData(GL_ARRAY_BUFFER, sizeof quad, quad, GL_STATIC_DRAW);
    pglVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);
    pglEnableVertexAttribArray(0);

    GLuint vs = compile(GL_VERTEX_SHADER, vs_src);
    GLuint fs_irr = compile(GL_FRAGMENT_SHADER, fs_irradiance_src);
    GLuint fs_br = compile(GL_FRAGMENT_SHADER, fs_bright_src);
    GLuint prog_irr = link2(vs, fs_irr);
    GLuint prog_br = link2(vs, fs_br);

    const int W = 256, H = 256;

    GLuint irrTex; glGenTextures(1, &irrTex);
    glBindTexture(GL_TEXTURE_2D, irrTex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, W, H, 0, GL_RGBA, GL_HALF_FLOAT, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    GLuint fbo; pglGenFramebuffers(1, &fbo);
    pglBindFramebuffer(GL_FRAMEBUFFER, fbo);
    pglFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, irrTex, 0);
    if (pglCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
        fprintf(stderr, "FBO incomplete\n"); return 3;
    }

    glViewport(0, 0, W, H);
    glClearColor(0, 0, 0, 1); glClear(GL_COLOR_BUFFER_BIT);
    pglUseProgram(prog_irr);
    pglUniform1f(pglGetUniformLocation(prog_irr, "lobe"), 0.25f);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    pglBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, W, H);
    glClearColor(0, 0, 0, 1); glClear(GL_COLOR_BUFFER_BIT);
    pglUseProgram(prog_br);
    glBindTexture(GL_TEXTURE_2D, irrTex);
    pglUniform1i(pglGetUniformLocation(prog_br, "src"), 0);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glXSwapBuffers(dpy, win);

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(W/4, H/2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("sampled rgba=%u,%u,%u,%u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}