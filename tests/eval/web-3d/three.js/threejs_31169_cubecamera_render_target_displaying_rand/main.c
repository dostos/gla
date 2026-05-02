// SOURCE: https://github.com/mrdoob/three.js/issues/31169
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char* vs_src =
    "#version 330 core\n"
    "layout(location=0) in vec3 aPos;\n"
    "out vec2 vUV;\n"
    "void main() { vUV = aPos.xy * 0.5 + 0.5; gl_Position = vec4(aPos, 1.0); }\n";

static const char* fs_src =
    "#version 330 core\n"
    "in vec2 vUV;\n"
    "uniform sampler2D uTex;\n"
    "out vec4 fragColor;\n"
    "void main() { fragColor = texture(uTex, vUV); }\n";

static GLuint compile_shader(GLenum type, const char* src) {
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok; glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024]; glGetShaderInfoLog(s, 1024, NULL, log);
        fprintf(stderr, "shader: %s\n", log);
    }
    return s;
}

static GLuint make_program(void) {
    GLuint vs = compile_shader(GL_VERTEX_SHADER, vs_src);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, fs_src);
    GLuint p = glCreateProgram();
    glAttachShader(p, vs);
    glAttachShader(p, fs);
    glLinkProgram(p);
    glDeleteShader(vs);
    glDeleteShader(fs);
    return p;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int scr = DefaultScreen(dpy);
    int attribs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, scr, attribs);
    if (!vi) { fprintf(stderr, "glXChooseVisual failed\n"); return 1; }
    Window root = RootWindow(dpy, scr);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 256, 256, 0,
        vi->depth, InputOutput, vi->visual,
        CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    // Create a cube render target: one texture object, six 64x64 faces of distinct solid colors.
    GLuint envTex;
    glGenTextures(1, &envTex);
    glBindTexture(GL_TEXTURE_CUBE_MAP, envTex);
    unsigned char face_colors[6][4] = {
        {255,  0,  0,255}, {  0,255,  0,255}, {  0,  0,255,255},
        {255,255,  0,255}, {255,  0,255,255}, {  0,255,255,255}
    };
    unsigned char face_pixels[64*64*4];
    for (int i = 0; i < 6; ++i) {
        for (int p = 0; p < 64*64; ++p) memcpy(&face_pixels[p*4], face_colors[i], 4);
        glTexImage2D(GL_TEXTURE_CUBE_MAP_POSITIVE_X + i, 0, GL_RGBA,
            64, 64, 0, GL_RGBA, GL_UNSIGNED_BYTE, face_pixels);
    }
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glBindTexture(GL_TEXTURE_CUBE_MAP, 0);

    // Fullscreen triangle (clip-space).
    float verts[] = {
        -1.0f, -1.0f, 0.0f,
         3.0f, -1.0f, 0.0f,
        -1.0f,  3.0f, 0.0f,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3*sizeof(float), NULL);
    glEnableVertexAttribArray(0);

    GLuint prog = make_program();
    glUseProgram(prog);
    glUniform1i(glGetUniformLocation(prog, "uTex"), 0);

    // Visualize the cube render target on a quad: bind its texture for sampling on unit 0.
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, envTex);

    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    unsigned char px[4] = {0};
    glReadPixels(128, 128, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center pixel rgba=%d,%d,%d,%d\n", px[0], px[1], px[2], px[3]);

    GLenum err;
    while ((err = glGetError()) != GL_NO_ERROR) {
        printf("glGetError=0x%04x\n", err);
    }

    glXSwapBuffers(dpy, win);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}