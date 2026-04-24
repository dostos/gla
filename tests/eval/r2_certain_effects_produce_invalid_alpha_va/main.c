// SOURCE: https://github.com/pmndrs/postprocessing/issues/719
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define W 128
#define H 128

static const char *VS_SRC =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "out vec2 vUV;\n"
    "void main() { vUV = aPos * 0.5 + 0.5; gl_Position = vec4(aPos, 0.0, 1.0); }\n";

// Effect pass written in the postprocessing library's mainImage(inputColor,
// uv, outputColor) convention: `inputBuffer` is the upstream pass's
// accumulation and `map` is the bloom mip chain sampled at the current uv.
static const char *FS_SRC =
    "#version 330 core\n"
    "in vec2 vUV;\n"
    "out vec4 fragColor;\n"
    "uniform sampler2D inputBuffer;\n"
    "uniform sampler2D map;\n"
    "uniform float intensity;\n"
    "void mainImage(const in vec4 inputColor, const in vec2 uv, out vec4 outputColor) {\n"
    "  vec4 texel = texture(map, uv);\n"
    "  outputColor = vec4(texel.rgb * intensity, texel.a);\n"
    "}\n"
    "void main() {\n"
    "  vec4 inputColor = texture(inputBuffer, vUV);\n"
    "  vec4 outputColor;\n"
    "  mainImage(inputColor, vUV, outputColor);\n"
    "  fragColor = outputColor;\n"
    "}\n";

static GLuint compile_shader(GLenum kind, const char *src) {
    GLuint sh = glCreateShader(kind);
    glShaderSource(sh, 1, &src, NULL);
    glCompileShader(sh);
    GLint ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog(sh, sizeof(log), NULL, log);
        fprintf(stderr, "shader: %s\n", log);
        exit(1);
    }
    return sh;
}

int main(void) {
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int attribs[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo *vi = glXChooseVisual(dpy, 0, attribs);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, root, 0, 0, W, H, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    // Upstream pass: fully opaque magenta across the whole frame.
    unsigned char *sceneTexels = malloc(W * H * 4);
    for (int i = 0; i < W * H; ++i) {
        sceneTexels[i * 4 + 0] = 180;
        sceneTexels[i * 4 + 1] = 40;
        sceneTexels[i * 4 + 2] = 160;
        sceneTexels[i * 4 + 3] = 255;
    }
    GLuint inputTex;
    glGenTextures(1, &inputTex);
    glBindTexture(GL_TEXTURE_2D, inputTex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, W, H, 0, GL_RGBA, GL_UNSIGNED_BYTE, sceneTexels);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    free(sceneTexels);

    // Bloom mip: soft radial highlight centered in the frame; outside the
    // radius of coverage all four channels fall off to zero.
    unsigned char *bloomTexels = calloc(W * H * 4, 1);
    for (int y = 0; y < H; ++y) {
        for (int x = 0; x < W; ++x) {
            float dx = x - W * 0.5f, dy = y - H * 0.5f;
            float r = sqrtf(dx * dx + dy * dy);
            float f = fmaxf(0.0f, 1.0f - r / 16.0f);
            int i = (y * W + x) * 4;
            bloomTexels[i + 0] = (unsigned char)(255 * f);
            bloomTexels[i + 1] = (unsigned char)(220 * f);
            bloomTexels[i + 2] = (unsigned char)(80 * f);
            bloomTexels[i + 3] = (unsigned char)(255 * f);
        }
    }
    GLuint bloomTex;
    glGenTextures(1, &bloomTex);
    glBindTexture(GL_TEXTURE_2D, bloomTex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, W, H, 0, GL_RGBA, GL_UNSIGNED_BYTE, bloomTexels);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    free(bloomTexels);

    // Effect render target.
    GLuint outTex, outFbo;
    glGenTextures(1, &outTex);
    glBindTexture(GL_TEXTURE_2D, outTex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, W, H, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glGenFramebuffers(1, &outFbo);
    glBindFramebuffer(GL_FRAMEBUFFER, outFbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, outTex, 0);

    float verts[] = { -1.f, -1.f,  3.f, -1.f,  -1.f, 3.f };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, (void *)0);

    GLuint vs = compile_shader(GL_VERTEX_SHADER, VS_SRC);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, FS_SRC);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);
    glUseProgram(prog);
    glUniform1i(glGetUniformLocation(prog, "inputBuffer"), 0);
    glUniform1i(glGetUniformLocation(prog, "map"), 1);
    glUniform1f(glGetUniformLocation(prog, "intensity"), 1.0f);

    glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, inputTex);
    glActiveTexture(GL_TEXTURE1); glBindTexture(GL_TEXTURE_2D, bloomTex);

    glBindFramebuffer(GL_FRAMEBUFFER, outFbo);
    glViewport(0, 0, W, H);
    glDisable(GL_BLEND);
    glClearColor(0, 0, 0, 0);
    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    unsigned char edge[4];
    glReadPixels(4, 4, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, edge);
    printf("edge pixel rgba=%d,%d,%d,%d\n", edge[0], edge[1], edge[2], edge[3]);

    unsigned char center[4];
    glReadPixels(W / 2, H / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, center);
    printf("center pixel rgba=%d,%d,%d,%d\n", center[0], center[1], center[2], center[3]);

    glBindFramebuffer(GL_READ_FRAMEBUFFER, outFbo);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
    glBlitFramebuffer(0, 0, W, H, 0, 0, W, H, GL_COLOR_BUFFER_BIT, GL_NEAREST);
    glXSwapBuffers(dpy, win);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}