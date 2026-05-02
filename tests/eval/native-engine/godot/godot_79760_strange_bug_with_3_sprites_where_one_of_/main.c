// SOURCE: https://github.com/godotengine/godot/issues/79760
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *vs_src =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "uniform vec2 uOffset;\n"
    "void main(){ gl_Position = vec4(aPos + uOffset, 0.0, 1.0); }\n";

static const char *fs_plain_src =
    "#version 330 core\n"
    "out vec4 FragColor;\n"
    "void main(){ FragColor = vec4(1.0, 1.0, 1.0, 1.0); }\n";

static const char *fs_uniform_src =
    "#version 330 core\n"
    "out vec4 FragColor;\n"
    "uniform vec4 color;\n"
    "void main(){ FragColor = vec4(color.rgb, 1.0); }\n";

static GLuint compile(GLenum type, const char *src) {
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok; glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) { char log[1024]; glGetShaderInfoLog(s, 1024, NULL, log); fprintf(stderr, "compile: %s\n", log); exit(1); }
    return s;
}

static GLuint link_program(GLuint vs, GLuint fs) {
    GLuint p = glCreateProgram();
    glAttachShader(p, vs); glAttachShader(p, fs);
    glLinkProgram(p);
    return p;
}

int main(void) {
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int attribs[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo *vi = glXChooseVisual(dpy, 0, attribs);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 256, 256, 0, vi->depth,
                               InputOutput, vi->visual, CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext glc = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, glc);

    GLuint vs = compile(GL_VERTEX_SHADER, vs_src);
    GLuint fs_plain = compile(GL_FRAGMENT_SHADER, fs_plain_src);
    GLuint fs_uniform = compile(GL_FRAGMENT_SHADER, fs_uniform_src);
    GLuint prog_plain = link_program(vs, fs_plain);
    GLuint prog_uniform = link_program(vs, fs_uniform);

    float quad[] = { -0.1f,-0.1f,  0.1f,-0.1f,  0.1f,0.1f,
                     -0.1f,-0.1f,  0.1f, 0.1f, -0.1f,0.1f };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao); glBindVertexArray(vao);
    glGenBuffers(1, &vbo); glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL);
    glEnableVertexAttribArray(0);

    glClearColor(0.2f, 0.2f, 0.2f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    float offsets[3][2] = { {-0.5f, 0.0f}, {0.5f, 0.0f}, {0.0f, 0.5f} };

    glUseProgram(prog_plain);
    glUniform2f(glGetUniformLocation(prog_plain, "uOffset"), offsets[0][0], offsets[0][1]);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glUseProgram(prog_plain);
    glUniform2f(glGetUniformLocation(prog_plain, "uOffset"), offsets[1][0], offsets[1][1]);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glUseProgram(prog_uniform);
    glUniform2f(glGetUniformLocation(prog_uniform, "uOffset"), offsets[2][0], offsets[2][1]);
    glUniform4f(glGetUniformLocation(prog_uniform, "color"), 0.0f, 1.0f, 0.0f, 1.0f);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glXSwapBuffers(dpy, win);

    unsigned char px[4];
    glReadPixels(128, 128 + 64, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center-top pixel rgba=%u,%u,%u,%u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, glc);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}