// SOURCE: https://github.com/mapbox/mapbox-gl-js/issues/13384
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

typedef GLXContext (*glXCreateContextAttribsARBProc)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

static const char* VS =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "uniform vec2 uOrigin;\n"
    "uniform mat4 uView;\n"
    "void main(){\n"
    "  vec2 p = uOrigin + aPos;\n"
    "  gl_Position = uView * vec4(p, 0.0, 1.0);\n"
    "}\n";

static const char* FS =
    "#version 330 core\n"
    "out vec4 FragColor;\n"
    "void main(){ FragColor = vec4(0.9, 0.3, 0.2, 1.0); }\n";

static GLuint compile(GLenum type, const char* src){
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok=0; glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if(!ok){ char log[1024]; glGetShaderInfoLog(s, 1024, NULL, log); fprintf(stderr, "shader: %s\n", log); exit(2); }
    return s;
}

static int point_in_view(float x, float y){
    return (x >= -1.0f && x <= 1.0f && y >= -1.0f && y <= 1.0f);
}

int main(void){
    Display* dpy = XOpenDisplay(NULL);
    if(!dpy){ fprintf(stderr, "no display\n"); return 1; }
    int vis_attr[] = { GLX_X_RENDERABLE, True, GLX_RENDER_TYPE, GLX_RGBA_BIT,
        GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT, GLX_DOUBLEBUFFER, True,
        GLX_RED_SIZE,8, GLX_GREEN_SIZE,8, GLX_BLUE_SIZE,8, GLX_DEPTH_SIZE,24, None };
    int nfb = 0;
    GLXFBConfig* fbc = glXChooseFBConfig(dpy, DefaultScreen(dpy), vis_attr, &nfb);
    XVisualInfo* vi = glXGetVisualFromFBConfig(dpy, fbc[0]);
    Colormap cmap = XCreateColormap(dpy, RootWindow(dpy, vi->screen), vi->visual, AllocNone);
    XSetWindowAttributes swa = {0}; swa.colormap = cmap; swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, RootWindow(dpy, vi->screen), 0,0, 512,512, 0, vi->depth,
        InputOutput, vi->visual, CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, win);
    int ctx_attr[] = { GLX_CONTEXT_MAJOR_VERSION_ARB, 3, GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB, None };
    glXCreateContextAttribsARBProc glXCreateContextAttribsARB =
        (glXCreateContextAttribsARBProc)glXGetProcAddressARB((const GLubyte*)"glXCreateContextAttribsARB");
    GLXContext ctx = glXCreateContextAttribsARB(dpy, fbc[0], 0, True, ctx_attr);
    glXMakeCurrent(dpy, win, ctx);

    GLuint vs = compile(GL_VERTEX_SHADER, VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs); glAttachShader(prog, fs); glLinkProgram(prog);

    // Quad vertices in model-local coordinates. The model's local origin
    // sits at (0,0); the geometry spans roughly 1.4 units in each direction
    // around it (modelling a large GLB whose pivot is at one end).
    float quad[] = {
        0.2f, 0.2f,  1.6f, 0.2f,  1.6f, 1.6f,
        0.2f, 0.2f,  1.6f, 1.6f,  0.2f, 1.6f,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao); glBindVertexArray(vao);
    glGenBuffers(1, &vbo); glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2*sizeof(float), 0);
    glEnableVertexAttribArray(0);

    GLint locOrigin = glGetUniformLocation(prog, "uOrigin");
    GLint locView   = glGetUniformLocation(prog, "uView");

    // Identity view — clip space is already [-1,1].
    float view[16] = {1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};

    // Simulate a zoomed/rotated camera: the tile that contains the model's
    // anchor has scrolled just off the right side of the viewport, while the
    // model's geometry (+0.2..+1.6) still protrudes back into view if drawn.
    float origin_x = -1.2f;
    float origin_y =  0.0f;

    glViewport(0, 0, 512, 512);
    glClearColor(0.1f, 0.1f, 0.1f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    glUseProgram(prog);
    glUniformMatrix4fv(locView, 1, GL_FALSE, view);
    glUniform2f(locOrigin, origin_x, origin_y);

    // Host-side visibility test: is the model's anchor point inside clip?
    if (point_in_view(origin_x, origin_y)) {
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }

    glXSwapBuffers(dpy, win);

    unsigned char px[4] = {0};
    glReadPixels(400, 256, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("probe pixel rgba=%u,%u,%u,%u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}