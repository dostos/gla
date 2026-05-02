// SOURCE: https://github.com/pixijs/pixijs/issues/11995
// Models a pooled mask texture (128x128) reused for two consecutive draws,
// each with its own active sub-region (100x80 then 70x110). `uMapCoord` is a
// vec2 that scales UVs into the active sub-region.
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *VS_SRC =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "layout(location=1) in vec2 aUV;\n"
    "uniform vec2 uOffset;\n"
    "out vec2 vUV;\n"
    "void main(){ vUV = aUV; gl_Position = vec4(aPos + uOffset, 0.0, 1.0); }\n";

static const char *FS_SRC =
    "#version 330 core\n"
    "in vec2 vUV;\n"
    "uniform sampler2D uMask;\n"
    "uniform vec2 uMapCoord;\n"   // frame.size / source.size — tells us where the live mask sits inside the 128x128 pool
    "uniform vec3 uTint;\n"
    "out vec4 fragColor;\n"
    "void main(){\n"
    "  float m = texture(uMask, vUV * uMapCoord).r;\n"
    "  fragColor = vec4(uTint, 1.0) * m;\n"
    "}\n";

static GLuint compile_shader(GLenum kind, const char *src) {
    GLuint sh = glCreateShader(kind);
    glShaderSource(sh, 1, &src, NULL);
    glCompileShader(sh);
    GLint ok = 0; glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024]; glGetShaderInfoLog(sh, sizeof(log), NULL, log);
        fprintf(stderr, "shader compile failed: %s\n", log); exit(1);
    }
    return sh;
}

#define POOL 128

// Repopulate the entire pooled texture: white in [0,sub_w) x [0,sub_h),
// black elsewhere.
static void upload_mask_into_pool(GLuint tex, int sub_w, int sub_h) {
    static unsigned char data[POOL * POOL];
    memset(data, 0, sizeof(data));
    for (int y = 0; y < sub_h; ++y)
        for (int x = 0; x < sub_w; ++x)
            data[y * POOL + x] = 255;
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, POOL, POOL, GL_RED, GL_UNSIGNED_BYTE, data);
}

int main(void) {
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }

    int attribs[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo *vi = glXChooseVisual(dpy, 0, attribs);
    if (!vi) { fprintf(stderr, "no visual\n"); return 1; }

    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 800, 600, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    glViewport(0, 0, 800, 600);

    // === Quad geometry: a 0.5x0.5 NDC square centered at the origin ===
    float verts[] = {
        -0.25f, -0.25f, 0.f, 0.f,
         0.25f, -0.25f, 1.f, 0.f,
         0.25f,  0.25f, 1.f, 1.f,
        -0.25f,  0.25f, 0.f, 1.f,
    };
    unsigned int idx[] = { 0, 1, 2, 0, 2, 3 };

    GLuint vao, vbo, ebo;
    glGenVertexArrays(1, &vao); glBindVertexArray(vao);
    glGenBuffers(1, &vbo); glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glGenBuffers(1, &ebo); glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, sizeof(idx), idx, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 4 * sizeof(float), (void*)0);
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 4 * sizeof(float), (void*)(2 * sizeof(float)));

    // === Allocate ONE pooled mask texture (128x128 R8) reused across both passes. ===
    GLuint pool;
    glGenTextures(1, &pool);
    glBindTexture(GL_TEXTURE_2D, pool);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_R8, POOL, POOL, 0, GL_RED, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    GLuint vs = compile_shader(GL_VERTEX_SHADER,   VS_SRC);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, FS_SRC);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs); glAttachShader(prog, fs);
    glLinkProgram(prog); glUseProgram(prog);
    GLint locOffset   = glGetUniformLocation(prog, "uOffset");
    GLint locMask     = glGetUniformLocation(prog, "uMask");
    GLint locMapCoord = glGetUniformLocation(prog, "uMapCoord");
    GLint locTint     = glGetUniformLocation(prog, "uTint");
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, pool);
    glUniform1i(locMask, 0);

    glClearColor(0.08f, 0.08f, 0.10f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    // ---- Mask A pass: pool holds a 100x80 white block in its top-left.
    upload_mask_into_pool(pool, 100, 80);

    // Draw squareA (green) on the LEFT.
    glUniform2f(locOffset,   -0.45f, 0.0f);
    glUniform2f(locMapCoord, 100.0f / (float)POOL, 80.0f / (float)POOL);
    glUniform3f(locTint,     0.10f, 0.85f, 0.40f);
    glDrawElements(GL_TRIANGLES, 6, GL_UNSIGNED_INT, 0);

    // ---- Reuse the SAME texture object for mask B (70x110).
    upload_mask_into_pool(pool, 70, 110);

    // Draw squareB (blue) on the RIGHT.
    glUniform2f(locOffset, 0.45f, 0.0f);
    glUniform3f(locTint,   0.20f, 0.45f, 0.95f);
    glDrawElements(GL_TRIANGLES, 6, GL_UNSIGNED_INT, 0);

    GLenum err = glGetError();
    if (err != GL_NO_ERROR) fprintf(stderr, "post-draw glGetError = 0x%x\n", err);

    glXSwapBuffers(dpy, win);
    return 0;
}