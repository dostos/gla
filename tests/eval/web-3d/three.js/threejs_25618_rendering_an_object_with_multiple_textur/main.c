// SOURCE: https://github.com/mrdoob/three.js/issues/25618
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char* vsrc =
    "#version 330 core\n"
    "layout(location=0) in vec2 pos;\n"
    "out vec2 uv;\n"
    "void main(){ uv = pos*0.5+0.5; gl_Position = vec4(pos,0,1); }\n";

static const char* fsrc =
    "#version 330 core\n"
    "in vec2 uv;\n"
    "out vec4 frag;\n"
    "uniform sampler2D map1;\n"
    "uniform sampler2D map2;\n"
    "void main(){\n"
    "  vec4 a = texture(map1, uv*vec2(2.0,1.0));\n"
    "  vec4 b = texture(map2, vec2(uv.x*2.0-1.0, uv.y));\n"
    "  frag = uv.x < 0.5 ? a : b;\n"
    "}\n";

static GLuint compile_shader(GLenum type, const char* src) {
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok = 0;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog(s, sizeof(log), NULL, log);
        fprintf(stderr, "shader compile failed: %s\n", log);
    }
    return s;
}

static GLuint make_solid_texture(int w, int h, unsigned char r, unsigned char g, unsigned char b) {
    GLuint t = 0;
    glGenTextures(1, &t);
    glBindTexture(GL_TEXTURE_2D, t);
    unsigned char* px = (unsigned char*)malloc((size_t)w * h * 4);
    for (int i = 0; i < w * h; i++) {
        px[i*4+0] = r;
        px[i*4+1] = g;
        px[i*4+2] = b;
        px[i*4+3] = 255;
    }
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
    free(px);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    return t;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) {
        fprintf(stderr, "cannot open display\n");
        return 1;
    }
    int attribs[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attribs);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 512, 256, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);
    glViewport(0, 0, 512, 256);

    GLuint prog = glCreateProgram();
    glAttachShader(prog, compile_shader(GL_VERTEX_SHADER, vsrc));
    glAttachShader(prog, compile_shader(GL_FRAGMENT_SHADER, fsrc));
    glLinkProgram(prog);
    glUseProgram(prog);

    GLuint vao = 0, vbo = 0;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    float quad[] = { -1.f, -1.f,  1.f, -1.f,  -1.f, 1.f,  1.f, 1.f };
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL);

    GLuint redTex   = make_solid_texture(64, 64, 255,   0,   0);
    GLuint greenTex = make_solid_texture(64, 64,   0, 255,   0);
    unsigned char blue[16 * 16 * 4];
    for (int i = 0; i < 16 * 16; i++) {
        blue[i*4+0] = 0;
        blue[i*4+1] = 0;
        blue[i*4+2] = 255;
        blue[i*4+3] = 255;
    }

    glUniform1i(glGetUniformLocation(prog, "map1"), 0);
    glUniform1i(glGetUniformLocation(prog, "map2"), 1);

    /* Phase 1: render quad sampling redTex on unit 0 and greenTex on unit 1.
       After binding both, the active texture unit is left at GL_TEXTURE1. */
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, redTex);
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, greenTex);
    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

    /* Phase 2: upload a blue 16x16 patch into redTex.
       A bind-cache shortcut treats slot 0 as already holding redTex from
       phase 1 and elides the glActiveTexture(GL_TEXTURE0) + glBindTexture
       pair that would normally precede the upload. */
    glTexSubImage2D(GL_TEXTURE_2D, 0, 24, 24, 16, 16,
                    GL_RGBA, GL_UNSIGNED_BYTE, blue);

    /* Phase 3: re-render with the same bindings to show which texture
       actually received the patch. */
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, redTex);
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, greenTex);
    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

    glXSwapBuffers(dpy, win);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}