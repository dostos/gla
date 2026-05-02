// SOURCE: https://github.com/Orama-Interactive/Pixelorama/issues/938
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>

static const char* VS_SRC =
    "#version 330 core\n"
    "layout(location=0) in vec2 p;\n"
    "void main(){ gl_Position = vec4(p, 0.0, 1.0); }\n";

/* Pattern from Pixelorama's BlendLayers.gdshader:
 *   uniform float[1024] opacities;
 *   uniform int[1024]   blend_modes;
 *   uniform vec2[1024]  origins;
 * Enlarged past any typical desktop MAX_FRAGMENT_UNIFORM_COMPONENTS
 * (usually 4096) so the silent link failure reproduces on desktop. */
static const char* FS_SRC =
    "#version 330 core\n"
    "uniform float opacities[8192];\n"
    "uniform int   blend_modes[8192];\n"
    "uniform vec2  origins[8192];\n"
    "out vec4 FragColor;\n"
    "void main(){\n"
    "  int i = (int(gl_FragCoord.x) + int(gl_FragCoord.y)) % 8192;\n"
    "  FragColor = vec4(opacities[i], float(blend_modes[i]), origins[i]);\n"
    "}\n";

static GLuint make_program(void){
    GLuint vs = glCreateShader(GL_VERTEX_SHADER);
    glShaderSource(vs, 1, &VS_SRC, NULL);
    glCompileShader(vs);
    GLuint fs = glCreateShader(GL_FRAGMENT_SHADER);
    glShaderSource(fs, 1, &FS_SRC, NULL);
    glCompileShader(fs);
    /* Upstream never checks GL_COMPILE_STATUS / GL_LINK_STATUS. When the
     * combined uniform components exceed the GPU limit the link fails
     * silently, glUseProgram becomes a no-op, and the frame stays blank. */
    GLuint p = glCreateProgram();
    glAttachShader(p, vs);
    glAttachShader(p, fs);
    glLinkProgram(p);
    return p;
}

int main(void){
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }

    int attrs[] = { GLX_RGBA, GLX_DOUBLEBUFFER,
                    GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8,
                    GLX_DEPTH_SIZE, 24, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attrs);
    if (!vi) return 1;

    Window root = RootWindow(dpy, vi->screen);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    Window win = XCreateWindow(dpy, root, 0, 0, 512, 512, 0,
                               vi->depth, InputOutput, vi->visual,
                               CWColormap, &swa);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, True);
    glXMakeCurrent(dpy, win, ctx);

    /* Pixelorama clears to the transparency-checker background then blends
     * the layer shader over it. Use an obvious color so a blank frame is
     * clearly the failure mode. */
    glClearColor(0.0f, 0.0f, 0.4f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    GLuint prog = make_program();

    GLfloat quad[] = { -1,-1, 1,-1, -1,1,  1,-1, 1,1, -1,1 };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof quad, quad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, 0);

    glUseProgram(prog);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glFinish();
    glXSwapBuffers(dpy, win);
    return 0;
}