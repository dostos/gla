// SOURCE: https://github.com/mrdoob/three.js/pull/33422
// Minimal GL reproduction of the NodeMaterialObserver "default version =
// value.version" race-condition bug.
//
// An "observer" struct caches a texture's `version` on first observation.
// The render loop later compares the live `version` against the cached
// one and conditionally calls `glTexImage2D` to upload the latest pixels.
// If the cache was initialised with the live version (the buggy path),
// the compare never differs and the upload is skipped forever — the GPU
// keeps sampling its default placeholder texture (initialised to all
// zeros above) and the center pixel reads (0, 0, 0).
//
// In the live three.js code path the equivalent buggy line is:
//     data[ property ] = { id: value.id, version: value.version };
// in src/materials/nodes/manager/NodeMaterialObserver.js. The fix flips
// `value.version` to `0` so the first-frame compare always mismatches.

#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const int W = 256, H = 256;

static GLuint compile_shader(GLenum kind, const char* src) {
    GLuint s = glCreateShader(kind);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok = 0; glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024]; glGetShaderInfoLog(s, sizeof log, NULL, log);
        fprintf(stderr, "shader compile failed: %s\n", log);
        exit(1);
    }
    return s;
}

static GLuint link_program(const char* vsrc, const char* fsrc) {
    GLuint vs = compile_shader(GL_VERTEX_SHADER, vsrc);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, fsrc);
    GLuint p = glCreateProgram();
    glAttachShader(p, vs); glAttachShader(p, fs);
    glLinkProgram(p);
    GLint ok = 0; glGetProgramiv(p, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[1024]; glGetProgramInfoLog(p, sizeof log, NULL, log);
        fprintf(stderr, "link failed: %s\n", log);
        exit(1);
    }
    glDeleteShader(vs); glDeleteShader(fs);
    return p;
}

static const char* VS =
"#version 330 core\n"
"layout(location=0) in vec2 a_pos;\n"
"out vec2 v_uv;\n"
"void main() { gl_Position = vec4(a_pos, 0.0, 1.0); v_uv = a_pos * 0.5 + 0.5; }\n";

static const char* FS =
"#version 330 core\n"
"in vec2 v_uv;\n"
"uniform sampler2D u_tex;\n"
"out vec4 fragColor;\n"
"void main() { fragColor = texture(u_tex, v_uv); }\n";

// "Texture" with id and version, mirroring three.js Texture API.
typedef struct {
    int id;
    int version;
    int width;
    int height;
    unsigned char* pixels;
} Texture;

// "ObserverData" — caches version per observed texture.
typedef struct {
    int cached_version;
    int initialised;
} ObserverData;

// Pre-fix observer init: cache the *current* version. Bug.
static void observer_init_buggy(ObserverData* d, const Texture* t) {
    d->cached_version = t->version;     // BUGGY (matches live -> compare never fires)
    // Post-fix line: d->cached_version = 0;
    d->initialised = 1;
}

// Returns true if the renderer should re-upload the texture.
static int observer_dirty(ObserverData* d, const Texture* t) {
    if (!d->initialised) return 1;
    if (d->cached_version != t->version) {
        d->cached_version = t->version;
        return 1;
    }
    return 0;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "cannot open display\n"); return 1; }
    int attribs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, attribs);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    swa.colormap   = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, W, H, 0, vi->depth,
        InputOutput, vi->visual, CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, win);

    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);
    glViewport(0, 0, W, H);

    GLuint prog = link_program(VS, FS);

    float quad[] = {
        -1.0f, -1.0f,  1.0f, -1.0f,  1.0f,  1.0f,
        -1.0f, -1.0f,  1.0f,  1.0f, -1.0f,  1.0f,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glGenBuffers(1, &vbo);
    glBindVertexArray(vao);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof quad, quad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL);

    // GL texture: initialise the GPU binding with a 1x1 black placeholder
    // (matches what WebGPURenderer's WebGL backend does at material setup).
    GLuint gl_tex = 0; glGenTextures(1, &gl_tex);
    glBindTexture(GL_TEXTURE_2D, gl_tex);
    {
        unsigned char placeholder[4] = {0, 0, 0, 255};
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 1, 1, 0,
                     GL_RGBA, GL_UNSIGNED_BYTE, placeholder);
    }
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);

    // CPU-side "Texture" representing the user's loaded image.
    // The image "loaded" before the observer's first observation, so its
    // version is already 1 by the time we observe it.
    Texture user_tex;
    user_tex.id = 42;
    user_tex.width = 4;
    user_tex.height = 4;
    static unsigned char loaded_pixels[16 * 4];
    for (int i = 0; i < 16; ++i) {
        loaded_pixels[4*i + 0] = 220;
        loaded_pixels[4*i + 1] = 220;
        loaded_pixels[4*i + 2] = 220;
        loaded_pixels[4*i + 3] = 255;
    }
    user_tex.pixels = loaded_pixels;
    user_tex.version = 1;   // <-- LOADED BEFORE OBSERVATION (race condition).

    // Observer first sees the texture (race-loss path: image is already loaded).
    ObserverData obs = { 0, 0 };
    observer_init_buggy(&obs, &user_tex);

    // Render loop tick: ask the observer if the texture needs uploading.
    if (observer_dirty(&obs, &user_tex)) {
        glBindTexture(GL_TEXTURE_2D, gl_tex);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8,
                     user_tex.width, user_tex.height, 0,
                     GL_RGBA, GL_UNSIGNED_BYTE, user_tex.pixels);
    }
    // Pre-fix path: observer_dirty returns 0 here because cached == live ==
    // 1, so the upload never happens; the GPU sampler keeps reading the
    // 1x1 black placeholder.

    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(prog);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, gl_tex);
    glUniform1i(glGetUniformLocation(prog, "u_tex"), 0);
    glDrawArrays(GL_TRIANGLES, 0, 6);
    glXSwapBuffers(dpy, win);

    unsigned char px[4];
    glReadPixels(W/2, H/2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center pixel rgba=%u,%u,%u,%u "
           "(expected ~220,220,220 with upload-on-first-frame; "
           "broken ~0,0,0 with placeholder retained)\n",
           px[0], px[1], px[2], px[3]);

    glDeleteProgram(prog);
    glDeleteTextures(1, &gl_tex);
    glDeleteVertexArrays(1, &vao);
    glDeleteBuffers(1, &vbo);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}
