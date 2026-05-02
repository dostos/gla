// SOURCE: https://github.com/daronyondem/agent-cockpit/issues/142
// Pattern: a post-processing "bloom" pass executes (draw call issued, no GL
// errors), but its fullscreen quad shader program silently produces no visible
// output because of a shader compile/link issue that GL itself does not flag
// via glGetError. Mirrors the reported UnrealBloomPass behavior.
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

typedef GLuint (*PFNCREATESHADER)(GLenum);
typedef void   (*PFNSHADERSOURCE)(GLuint, GLsizei, const char* const*, const GLint*);
typedef void   (*PFNCOMPILESHADER)(GLuint);
typedef GLuint (*PFNCREATEPROGRAM)(void);
typedef void   (*PFNATTACHSHADER)(GLuint, GLuint);
typedef void   (*PFNLINKPROGRAM)(GLuint);
typedef void   (*PFNUSEPROGRAM)(GLuint);
typedef void   (*PFNGENBUFFERS)(GLsizei, GLuint*);
typedef void   (*PFNBINDBUFFER)(GLenum, GLuint);
typedef void   (*PFNBUFFERDATA)(GLenum, long, const void*, GLenum);
typedef void   (*PFNGENVAOS)(GLsizei, GLuint*);
typedef void   (*PFNBINDVAO)(GLuint);
typedef void   (*PFNVERTEXATTRIBPTR)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void   (*PFNENABLEVAA)(GLuint);
typedef void   (*PFNGETSHADERIV)(GLuint, GLenum, GLint*);
typedef void   (*PFNGETPROGRAMIV)(GLuint, GLenum, GLint*);

#define GL_VERTEX_SHADER   0x8B31
#define GL_FRAGMENT_SHADER 0x8B30
#define GL_ARRAY_BUFFER    0x8892
#define GL_STATIC_DRAW     0x88E4
#define GL_COMPILE_STATUS  0x8B81
#define GL_LINK_STATUS     0x8B82

static void* gl(const char* n){ return glXGetProcAddressARB((const GLubyte*)n); }

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    int attribs[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, attribs);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 512, 512, 0, vi->depth,
        InputOutput, vi->visual, CWColormap | CWEventMask, &swa);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    PFNCREATESHADER  CreateShader  = gl("glCreateShader");
    PFNSHADERSOURCE  ShaderSource  = gl("glShaderSource");
    PFNCOMPILESHADER CompileShader = gl("glCompileShader");
    PFNCREATEPROGRAM CreateProgram = gl("glCreateProgram");
    PFNATTACHSHADER  AttachShader  = gl("glAttachShader");
    PFNLINKPROGRAM   LinkProgram   = gl("glLinkProgram");
    PFNUSEPROGRAM    UseProgram    = gl("glUseProgram");
    PFNGENBUFFERS    GenBuffers    = gl("glGenBuffers");
    PFNBINDBUFFER    BindBuffer    = gl("glBindBuffer");
    PFNBUFFERDATA    BufferData    = gl("glBufferData");
    PFNGENVAOS       GenVAOs       = gl("glGenVertexArrays");
    PFNBINDVAO       BindVAO       = gl("glBindVertexArray");
    PFNVERTEXATTRIBPTR VAPtr       = gl("glVertexAttribPointer");
    PFNENABLEVAA     EnableVAA     = gl("glEnableVertexAttribArray");
    PFNGETSHADERIV   GetShaderiv   = gl("glGetShaderiv");
    PFNGETPROGRAMIV  GetProgramiv  = gl("glGetProgramiv");

    // Scene: a green triangle (acts as the "graph")
    const char* sceneVS =
        "#version 330 core\n"
        "layout(location=0) in vec2 p;\n"
        "void main(){ gl_Position = vec4(p, 0.0, 1.0); }\n";
    const char* sceneFS =
        "#version 330 core\n"
        "out vec4 c;\n"
        "void main(){ c = vec4(0.0, 0.7, 0.0, 1.0); }\n";

    // "Bloom" full-screen quad pass: shader is syntactically valid GLSL but
    // declares an unused 'inputBuffer' sampler whose binding is never set, AND
    // outputs only the result of a function whose return value the optimizer
    // collapses to vec4(0). Mirrors the reported pattern: program links, no GL
    // error, draw call issues, but framebuffer is unaffected.
    const char* bloomVS =
        "#version 330 core\n"
        "layout(location=0) in vec2 p;\n"
        "out vec2 uv;\n"
        "void main(){ uv = p*0.5+0.5; gl_Position = vec4(p, 0.0, 1.0); }\n";
    const char* bloomFS =
        "#version 330 core\n"
        "in vec2 uv;\n"
        "uniform sampler2D inputBuffer;\n"
        "uniform float strength;\n"
        "out vec4 outColor;\n"
        "vec4 highpass(vec2 u){\n"
        "    vec4 s = texture(inputBuffer, u);\n"
        "    return max(s - vec4(1.0), vec4(0.0));\n"
        "}\n"
        "void main(){\n"
        "    outColor = highpass(uv) * strength;\n"
        "}\n";

    auto_GLuint:;
    GLuint sceneProg, bloomProg;
    {
        GLuint vs = CreateShader(GL_VERTEX_SHADER);
        ShaderSource(vs, 1, &sceneVS, NULL); CompileShader(vs);
        GLuint fs = CreateShader(GL_FRAGMENT_SHADER);
        ShaderSource(fs, 1, &sceneFS, NULL); CompileShader(fs);
        sceneProg = CreateProgram();
        AttachShader(sceneProg, vs); AttachShader(sceneProg, fs);
        LinkProgram(sceneProg);

        GLuint bvs = CreateShader(GL_VERTEX_SHADER);
        ShaderSource(bvs, 1, &bloomVS, NULL); CompileShader(bvs);
        GLuint bfs = CreateShader(GL_FRAGMENT_SHADER);
        ShaderSource(bfs, 1, &bloomFS, NULL); CompileShader(bfs);
        bloomProg = CreateProgram();
        AttachShader(bloomProg, bvs); AttachShader(bloomProg, bfs);
        LinkProgram(bloomProg);

        GLint ok = 0;
        GetProgramiv(bloomProg, GL_LINK_STATUS, &ok);
        printf("bloom link status=%d glError=0x%x\n", ok, glGetError());
    }

    // Triangle VAO
    float tri[] = { -0.5f,-0.5f,  0.5f,-0.5f,  0.0f,0.5f };
    GLuint vao, vbo;
    GenVAOs(1, &vao); BindVAO(vao);
    GenBuffers(1, &vbo); BindBuffer(GL_ARRAY_BUFFER, vbo);
    BufferData(GL_ARRAY_BUFFER, sizeof(tri), tri, GL_STATIC_DRAW);
    VAPtr(0, 2, GL_FLOAT, GL_FALSE, 0, 0); EnableVAA(0);

    // Fullscreen quad VAO
    float quad[] = { -1,-1, 1,-1, -1,1,  -1,1, 1,-1, 1,1 };
    GLuint qvao, qvbo;
    GenVAOs(1, &qvao); BindVAO(qvao);
    GenBuffers(1, &qvbo); BindBuffer(GL_ARRAY_BUFFER, qvbo);
    BufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    VAPtr(0, 2, GL_FLOAT, GL_FALSE, 0, 0); EnableVAA(0);

    glViewport(0, 0, 512, 512);
    glClearColor(0.0f, 0.0f, 0.05f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    // Scene draw
    UseProgram(sceneProg);
    BindVAO(vao);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    // "Bloom" pass — issues a fullscreen draw call, but produces no visible
    // change to the framebuffer (no glow added on top of the triangle).
    UseProgram(bloomProg);
    BindVAO(qvao);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    printf("post-bloom glError=0x%x\n", glGetError());

    glXSwapBuffers(dpy, win);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}