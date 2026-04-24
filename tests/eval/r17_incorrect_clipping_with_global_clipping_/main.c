// SOURCE: https://github.com/mrdoob/three.js/issues/28111
// Minimal OpenGL 3.3 port of the "clipping plane uniform leaks across nested render" pattern.
// Two quads are drawn in the outer pass. Between them, an inner pass overwrites the
// clip-plane uniform for its own camera and the outer pass never puts it back.

#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const int W = 256, H = 256;

static const char* VS =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "uniform vec2 uOffset;\n"
    "uniform vec4 uClipPlane;\n"
    "out float gl_ClipDistance[1];\n"
    "void main(){\n"
    "  vec2 p = aPos + uOffset;\n"
    "  gl_Position = vec4(p, 0.0, 1.0);\n"
    "  gl_ClipDistance[0] = dot(vec4(p, 0.0, 1.0), uClipPlane);\n"
    "}\n";

static const char* FS =
    "#version 330 core\n"
    "uniform vec3 uColor;\n"
    "out vec4 fragColor;\n"
    "void main(){ fragColor = vec4(uColor, 1.0); }\n";

static GLuint compile(GLenum type, const char* src){
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok = 0; glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if(!ok){ char log[1024]; glGetShaderInfoLog(s, 1024, NULL, log); fprintf(stderr,"shader: %s\n", log); exit(1); }
    return s;
}

static GLuint link_prog(GLuint vs, GLuint fs){
    GLuint p = glCreateProgram();
    glAttachShader(p, vs); glAttachShader(p, fs); glLinkProgram(p);
    GLint ok = 0; glGetProgramiv(p, GL_LINK_STATUS, &ok);
    if(!ok){ char log[1024]; glGetProgramInfoLog(p, 1024, NULL, log); fprintf(stderr,"link: %s\n", log); exit(1); }
    return p;
}

int main(void){
    Display* dpy = XOpenDisplay(NULL);
    if(!dpy){ fprintf(stderr,"no display\n"); return 1; }
    int fbattr[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), fbattr);
    Window root = RootWindow(dpy, vi->screen);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, root, 0, 0, W, H, 0, vi->depth,
                               InputOutput, vi->visual, CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    GLuint vs = compile(GL_VERTEX_SHADER, VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    GLuint prog = link_prog(vs, fs);
    glUseProgram(prog);

    GLint locOffset = glGetUniformLocation(prog, "uOffset");
    GLint locColor  = glGetUniformLocation(prog, "uColor");
    GLint locClip   = glGetUniformLocation(prog, "uClipPlane");

    float quad[] = {
        -0.2f,-0.2f,   0.2f,-0.2f,   0.2f, 0.2f,
        -0.2f,-0.2f,   0.2f, 0.2f,  -0.2f, 0.2f,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao); glBindVertexArray(vao);
    glGenBuffers(1, &vbo); glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);

    glEnable(GL_CLIP_DISTANCE0);
    glClearColor(0.f, 0.f, 0.f, 1.f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    // outer pass setup: one global clip plane "x >= 0".
    float outerPlane[4] = { 1.0f, 0.0f, 0.0f, 0.0f };
    glUniform4fv(locClip, 1, outerPlane);

    // outer draw A: quad on the right side, centered at (+0.5, +0.5).
    glUniform2f(locOffset,  0.5f,  0.5f);
    glUniform3f(locColor, 0.1f, 0.8f, 0.2f);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    // --- begin nested render (think: a Reflector drawing from its own camera) ---
    // The nested pass transforms the global plane into its own camera space
    // and writes the transformed value into the SAME uniform.
    float nestedPlane[4] = { 0.0f, 1.0f, 0.0f, 0.0f };
    glUniform4fv(locClip, 1, nestedPlane);
    // ... nested draws would happen here; we skip them to keep the repro minimal ...
    // --- end nested render ---

    // outer draw B: quad on the right side, centered at (+0.5, -0.5).
    // Same world-space clip plane as draw A is expected.
    glUniform2f(locOffset,  0.5f, -0.5f);
    glUniform3f(locColor, 0.9f, 0.2f, 0.2f);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glXSwapBuffers(dpy, win);

    unsigned char top[4] = {0}, bot[4] = {0};
    glReadPixels(W*3/4, H*3/4, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, top);
    glReadPixels(W*3/4, H*1/4, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, bot);
    printf("top-right pixel rgba=%u,%u,%u,%u\n", top[0], top[1], top[2], top[3]);
    printf("bot-right pixel rgba=%u,%u,%u,%u\n", bot[0], bot[1], bot[2], bot[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}