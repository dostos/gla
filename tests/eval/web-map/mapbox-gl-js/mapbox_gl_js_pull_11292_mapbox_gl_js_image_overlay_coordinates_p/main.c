// SOURCE: https://github.com/mapbox/mapbox-gl-js/issues/9158
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>

static const int W = 512, H = 512;

typedef GLXContext (*glXCreateContextAttribsARBProc)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

static GLuint compile(GLenum t, const char* src) {
    GLuint s = glCreateShader(t);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog(s, 1024, NULL, log);
        fprintf(stderr, "shader compile: %s\n", log);
        exit(1);
    }
    return s;
}

static const char* VS =
    "#version 330 core\n"
    "layout(location=0) in vec2 a_pos;\n"
    "layout(location=1) in vec2 a_uv;\n"
    "out vec2 v_uv;\n"
    "void main() {\n"
    "    v_uv = a_uv;\n"
    "    gl_Position = vec4(a_pos, 0.0, 1.0);\n"
    "}\n";

static const char* FS =
    "#version 330 core\n"
    "in vec2 v_uv;\n"
    "uniform sampler2D u_tex;\n"
    "out vec4 frag;\n"
    "void main() {\n"
    "    frag = texture(u_tex, v_uv);\n"
    "}\n";

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "cannot open display\n"); return 1; }

    int va[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, va);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, W, H, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    GLXContext legacy = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, legacy);

    glXCreateContextAttribsARBProc glXCreateContextAttribsARB =
        (glXCreateContextAttribsARBProc)glXGetProcAddressARB(
            (const GLubyte*)"glXCreateContextAttribsARB");
    int cattr[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        None
    };
    int n;
    GLXFBConfig* fbc = glXChooseFBConfig(dpy, DefaultScreen(dpy), NULL, &n);
    GLXContext ctx = glXCreateContextAttribsARB(dpy, fbc[0], NULL, True, cattr);
    glXMakeCurrent(dpy, win, ctx);

    // Checkerboard texture so any UV interpolation discontinuity is visible
    const int TS = 64;
    unsigned char tex[64 * 64 * 4];
    for (int y = 0; y < TS; y++) {
        for (int x = 0; x < TS; x++) {
            int c = ((x / 8) + (y / 8)) & 1;
            int o = (y * TS + x) * 4;
            tex[o+0] = c ? 240 : 20;
            tex[o+1] = c ? 240 : 20;
            tex[o+2] = c ? 240 : 20;
            tex[o+3] = 255;
        }
    }
    GLuint t;
    glGenTextures(1, &t);
    glBindTexture(GL_TEXTURE_2D, t);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, TS, TS, 0,
                 GL_RGBA, GL_UNSIGNED_BYTE, tex);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    // Image-overlay style quad: four corners forming a non-rectangular
    // quadrilateral (top edge wider than bottom — a trapezoid), drawn
    // as two triangles sharing the BL->TR diagonal.
    // Layout: pos.x, pos.y, uv.x, uv.y
    float verts[] = {
        -0.30f, -0.65f,   0.0f, 0.0f,  // BL
         0.30f, -0.65f,   1.0f, 0.0f,  // BR
         0.85f,  0.65f,   1.0f, 1.0f,  // TR
        -0.85f,  0.65f,   0.0f, 1.0f,  // TL
    };
    unsigned int idx[] = { 0, 1, 2,  0, 2, 3 };

    GLuint vao, vbo, ebo;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glGenBuffers(1, &ebo);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, sizeof(idx), idx, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 4*sizeof(float), (void*)0);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 4*sizeof(float),
                          (void*)(2*sizeof(float)));
    glEnableVertexAttribArray(1);

    GLuint vs = compile(GL_VERTEX_SHADER, VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);
    glUseProgram(prog);
    glUniform1i(glGetUniformLocation(prog, "u_tex"), 0);

    glViewport(0, 0, W, H);
    glClearColor(0.10f, 0.10f, 0.15f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, t);
    glDrawElements(GL_TRIANGLES, 6, GL_UNSIGNED_INT, 0);
    glXSwapBuffers(dpy, win);

    // Sample a few pixels along the BL->TR diagonal so the harness can
    // measure the texture pattern at known screen positions.
    unsigned char px[4];
    int probes[][2] = { {W*1/4, H*1/4}, {W/2, H/2}, {W*3/4, H*3/4} };
    for (int i = 0; i < 3; i++) {
        glReadPixels(probes[i][0], probes[i][1], 1, 1,
                     GL_RGBA, GL_UNSIGNED_BYTE, px);
        printf("probe %d at (%d,%d) rgba=%d,%d,%d,%d\n",
               i, probes[i][0], probes[i][1], px[0], px[1], px[2], px[3]);
    }

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XCloseDisplay(dpy);
    return 0;
}