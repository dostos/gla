// SOURCE: https://github.com/mrdoob/three.js/issues/31387
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>

#define W 256
#define H 256

static GLuint mkProgram(const char* vs, const char* fs) {
    GLuint v = glCreateShader(GL_VERTEX_SHADER);
    glShaderSource(v, 1, &vs, NULL); glCompileShader(v);
    GLuint f = glCreateShader(GL_FRAGMENT_SHADER);
    glShaderSource(f, 1, &fs, NULL); glCompileShader(f);
    GLuint p = glCreateProgram();
    glAttachShader(p, v); glAttachShader(p, f); glLinkProgram(p);
    glDeleteShader(v); glDeleteShader(f);
    return p;
}

static const char* VS_TRI =
    "#version 330 core\n"
    "layout(location=0) in vec2 p;\n"
    "void main(){ gl_Position = vec4(p, 0.0, 1.0); }\n";

static const char* FS_RED =
    "#version 330 core\n"
    "out vec4 c; void main(){ c = vec4(0.85, 0.10, 0.10, 1.0); }\n";

static const char* FS_GREEN =
    "#version 330 core\n"
    "out vec4 c; void main(){ c = vec4(0.10, 0.80, 0.20, 1.0); }\n";

static const char* VS_QUAD =
    "#version 330 core\n"
    "layout(location=0) in vec2 p;\n"
    "out vec2 uv;\n"
    "void main(){ uv = p * 0.5 + 0.5; gl_Position = vec4(p, 0.0, 1.0); }\n";

static const char* FS_POST =
    "#version 330 core\n"
    "in vec2 uv; out vec4 c; uniform sampler2D src;\n"
    "void main(){ vec3 col = texture(src, uv).rgb; c = vec4(pow(col, vec3(0.4545)), 1.0); }\n";

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    int attrs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, attrs);
    if (!vi) { fprintf(stderr, "no visual\n"); return 1; }
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, W, H, 0, vi->depth, InputOutput,
                               vi->visual, CWColormap | CWEventMask, &swa);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, True);
    glXMakeCurrent(dpy, win, ctx);

    // scene triangle
    float tri[] = { -0.9f, -0.9f, 0.9f, -0.9f, 0.0f, 0.9f };
    GLuint triVbo, triVao;
    glGenVertexArrays(1, &triVao); glBindVertexArray(triVao);
    glGenBuffers(1, &triVbo); glBindBuffer(GL_ARRAY_BUFFER, triVbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(tri), tri, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, 0);
    glEnableVertexAttribArray(0);

    // fullscreen quad
    float quad[] = { -1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1 };
    GLuint quadVbo, quadVao;
    glGenVertexArrays(1, &quadVao); glBindVertexArray(quadVao);
    glGenBuffers(1, &quadVbo); glBindBuffer(GL_ARRAY_BUFFER, quadVbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, 0);
    glEnableVertexAttribArray(0);

    // scene render target (linear HDR-style color held in 8-bit for the demo)
    GLuint sceneTex, sceneFbo;
    glGenTextures(1, &sceneTex); glBindTexture(GL_TEXTURE_2D, sceneTex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, W, H, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glGenFramebuffers(1, &sceneFbo);
    glBindFramebuffer(GL_FRAMEBUFFER, sceneFbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, sceneTex, 0);

    // post-processing tone-map target — this is the "presented" surface
    GLuint postTex, postFbo;
    glGenTextures(1, &postTex); glBindTexture(GL_TEXTURE_2D, postTex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, W, H, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glGenFramebuffers(1, &postFbo);
    glBindFramebuffer(GL_FRAMEBUFFER, postFbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, postTex, 0);

    GLuint progRed   = mkProgram(VS_TRI,  FS_RED);
    GLuint progGreen = mkProgram(VS_TRI,  FS_GREEN);
    GLuint progPost  = mkProgram(VS_QUAD, FS_POST);

    glViewport(0, 0, W, H);

    // 1. scene pass: render red triangle into sceneFbo
    glBindFramebuffer(GL_FRAMEBUFFER, sceneFbo);
    glClearColor(0.05f, 0.05f, 0.10f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(progRed);
    glBindVertexArray(triVao);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    // 2. postProcessing.render(): tone-map sceneTex into postFbo
    glBindFramebuffer(GL_FRAMEBUFFER, postFbo);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(progPost);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, sceneTex);
    glUniform1i(glGetUniformLocation(progPost, "src"), 0);
    glBindVertexArray(quadVao);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    // 3. minimap pass: viewport overlay rendered through the normal render path
    int dim = 64;
    glViewport(W - dim, H - dim, dim, dim);
    glClearColor(1.0f, 1.0f, 1.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(progGreen);
    glBindVertexArray(triVao);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    glFlush();

    // sample the presented surface
    glBindFramebuffer(GL_READ_FRAMEBUFFER, postFbo);
    unsigned char center[4] = {0}, corner[4] = {0};
    glReadPixels(W / 2, H / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, center);
    glReadPixels(W - dim / 2, H - dim / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, corner);
    printf("center rgba=%u,%u,%u,%u\n", center[0], center[1], center[2], center[3]);
    printf("corner rgba=%u,%u,%u,%u\n", corner[0], corner[1], corner[2], corner[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}