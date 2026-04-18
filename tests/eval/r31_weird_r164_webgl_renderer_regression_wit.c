// SOURCE: https://github.com/mrdoob/three.js/issues/28420
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>

static const char* VS =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "void main(){ gl_Position = vec4(aPos, 0.0, 1.0); }\n";

static const char* FS =
    "#version 330 core\n"
    "uniform vec3 uColor;\n"
    "out vec4 FragColor;\n"
    "void main(){ FragColor = vec4(uColor, 1.0); }\n";

static GLuint compile(GLenum t, const char* s){
    GLuint sh = glCreateShader(t);
    glShaderSource(sh, 1, &s, NULL);
    glCompileShader(sh);
    return sh;
}

typedef GLXContext (*PFNGLXCREATECONTEXTATTRIBSARBPROC)(
    Display*, GLXFBConfig, GLXContext, Bool, const int*);

int main(void){
    Display* dpy = XOpenDisplay(NULL);
    if(!dpy){ fprintf(stderr, "Cannot open display\n"); return 1; }
    int scr = DefaultScreen(dpy);

    int attribs[] = {
        GLX_X_RENDERABLE, True,
        GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_RENDER_TYPE, GLX_RGBA_BIT,
        GLX_X_VISUAL_TYPE, GLX_TRUE_COLOR,
        GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8, GLX_ALPHA_SIZE, 8,
        GLX_DEPTH_SIZE, 24,
        GLX_DOUBLEBUFFER, True,
        None
    };

    int fbcount = 0;
    GLXFBConfig* fbc = glXChooseFBConfig(dpy, scr, attribs, &fbcount);
    if(!fbc || fbcount == 0){ fprintf(stderr, "no fbconfig\n"); return 1; }
    GLXFBConfig config = fbc[0];
    XVisualInfo* vi = glXGetVisualFromFBConfig(dpy, config);

    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, RootWindow(dpy, scr), vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, RootWindow(dpy, scr), 0, 0, 256, 256, 0,
        vi->depth, InputOutput, vi->visual, CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, win);

    PFNGLXCREATECONTEXTATTRIBSARBPROC glXCreateContextAttribsARB =
        (PFNGLXCREATECONTEXTATTRIBSARBPROC)glXGetProcAddressARB(
            (const GLubyte*)"glXCreateContextAttribsARB");

    int ctx_attribs[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        None
    };
    GLXContext ctx = glXCreateContextAttribsARB(dpy, config, 0, True, ctx_attribs);
    glXMakeCurrent(dpy, win, ctx);

    // Port of three.js r164 render ordering change (PR #28118).
    // Performs two logical frames back-to-back:
    //   Frame N-1: clear white, draw a RED quad on the left.
    //   Frame N  : draw a GREEN quad on the right (no color clear).

    GLuint vs = compile(GL_VERTEX_SHADER, VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs); glAttachShader(prog, fs);
    glLinkProgram(prog);
    glUseProgram(prog);
    GLint uColor = glGetUniformLocation(prog, "uColor");

    float quadL[] = {
        -0.8f, -0.5f,  -0.2f, -0.5f,  -0.2f,  0.5f,
        -0.8f, -0.5f,  -0.2f,  0.5f,  -0.8f,  0.5f
    };
    float quadR[] = {
         0.2f, -0.5f,   0.8f, -0.5f,   0.8f,  0.5f,
         0.2f, -0.5f,   0.8f,  0.5f,   0.2f,  0.5f
    };

    GLuint vao, vboL, vboR;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vboL);
    glBindBuffer(GL_ARRAY_BUFFER, vboL);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quadL), quadL, GL_STATIC_DRAW);
    glGenBuffers(1, &vboR);
    glBindBuffer(GL_ARRAY_BUFFER, vboR);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quadR), quadR, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);

    glViewport(0, 0, 256, 256);

    for (int frame = 0; frame < 5; frame++) {
        // --- logical frame N-1 (content that would normally be cleared on next frame) ---
        glClearColor(1.0f, 1.0f, 1.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glUniform3f(uColor, 1.0f, 0.0f, 0.0f); // red
        glBindBuffer(GL_ARRAY_BUFFER, vboL);
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, 0);
        glDrawArrays(GL_TRIANGLES, 0, 6);

        // --- logical frame N: color clear omitted ---
        glUniform3f(uColor, 0.0f, 1.0f, 0.0f); // green
        glBindBuffer(GL_ARRAY_BUFFER, vboR);
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, 0);
        glDrawArrays(GL_TRIANGLES, 0, 6);

        glXSwapBuffers(dpy, win);
    }
    glFinish();
    XSync(dpy, False);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}