// SOURCE: https://github.com/mrdoob/three.js/issues/16211
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef GLXContext (*glXCreateContextAttribsARBProc)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

static const char* VS =
"#version 330 core\n"
"layout(location=0) in vec3 aPos;\n"
"layout(location=1) in vec3 aNormal;\n"
"out vec3 vN;\n"
"void main(){ vN = aNormal; gl_Position = vec4(aPos, 1.0); }\n";

static const char* FS =
"#version 330 core\n"
"in vec3 vN;\n"
"out vec4 frag;\n"
"void main(){\n"
"  vec3 L = normalize(vec3(0.0, 0.0, 1.0));\n"
"  float d = max(dot(normalize(vN), L), 0.0);\n"
"  frag = vec4(vec3(0.15) + vec3(0.85) * d, 1.0);\n"
"}\n";

static GLuint compile_shader(GLenum type, const char* src) {
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok = 0;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog(s, 1024, NULL, log);
        fprintf(stderr, "shader compile failed: %s\n", log);
        exit(1);
    }
    return s;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    int screen = DefaultScreen(dpy);

    int fbc_attribs[] = {
        GLX_RENDER_TYPE, GLX_RGBA_BIT,
        GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_DEPTH_SIZE, 24,
        GLX_DOUBLEBUFFER, True,
        None
    };
    int nfbc = 0;
    GLXFBConfig* fbcs = glXChooseFBConfig(dpy, screen, fbc_attribs, &nfbc);
    if (!fbcs || nfbc < 1) { fprintf(stderr, "no fbc\n"); return 1; }
    XVisualInfo* vi = glXGetVisualFromFBConfig(dpy, fbcs[0]);

    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, RootWindow(dpy, screen), vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, RootWindow(dpy, screen), 0, 0, 800, 600, 0,
                               vi->depth, InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    glXCreateContextAttribsARBProc glXCreateContextAttribsARB =
        (glXCreateContextAttribsARBProc)glXGetProcAddress((const GLubyte*)"glXCreateContextAttribsARB");
    int ctx_attribs[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        None
    };
    GLXContext ctx = glXCreateContextAttribsARB(dpy, fbcs[0], NULL, True, ctx_attribs);
    glXMakeCurrent(dpy, win, ctx);

    GLuint vs = compile_shader(GL_VERTEX_SHADER, VS);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, FS);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);

    // Five triangles spaced across the viewport (15 vertices).
    float positions[15 * 3] = {
        -0.92f, -0.5f, 0.0f,  -0.62f, -0.5f, 0.0f,  -0.77f, 0.5f, 0.0f,
        -0.55f, -0.5f, 0.0f,  -0.25f, -0.5f, 0.0f,  -0.40f, 0.5f, 0.0f,
        -0.15f, -0.5f, 0.0f,   0.15f, -0.5f, 0.0f,   0.00f, 0.5f, 0.0f,
         0.25f, -0.5f, 0.0f,   0.55f, -0.5f, 0.0f,   0.40f, 0.5f, 0.0f,
         0.65f, -0.5f, 0.0f,   0.92f, -0.5f, 0.0f,   0.78f, 0.5f, 0.0f,
    };
    // Per-vertex normals.
    float normals[12 * 3] = {
        0.0f, 0.0f, 1.0f,  0.0f, 0.0f, 1.0f,  0.0f, 0.0f, 1.0f,
        0.0f, 0.0f, 1.0f,  0.0f, 0.0f, 1.0f,  0.0f, 0.0f, 1.0f,
        0.0f, 0.0f, 1.0f,  0.0f, 0.0f, 1.0f,  0.0f, 0.0f, 1.0f,
        0.0f, 0.0f, 1.0f,  0.0f, 0.0f, 1.0f,  0.0f, 0.0f, 1.0f,
    };

    GLuint vao = 0;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);

    GLuint vbo_pos = 0;
    glGenBuffers(1, &vbo_pos);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_pos);
    glBufferData(GL_ARRAY_BUFFER, sizeof(positions), positions, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), (void*)0);

    GLuint vbo_nrm = 0;
    glGenBuffers(1, &vbo_nrm);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_nrm);
    glBufferData(GL_ARRAY_BUFFER, sizeof(normals), normals, GL_STATIC_DRAW);
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), (void*)0);

    glViewport(0, 0, 800, 600);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glUseProgram(prog);
    glBindVertexArray(vao);
    glDrawArrays(GL_TRIANGLES, 0, 15);

    glXSwapBuffers(dpy, win);

    int sample_x[5] = { 70, 230, 400, 570, 730 };
    for (int i = 0; i < 5; ++i) {
        unsigned char rgba[4] = {0, 0, 0, 0};
        glReadPixels(sample_x[i], 300, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
        printf("sample x=%d rgba=%u,%u,%u,%u\n",
               sample_x[i], rgba[0], rgba[1], rgba[2], rgba[3]);
    }

    glXMakeCurrent(dpy, NULL, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}