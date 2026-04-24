// SOURCE: https://github.com/mrdoob/three.js/issues/32533
// Minimal GL reproduction of the KTX2Loader BC3-vs-DXT3 mismatch.
//
// We pre-bake a 4×4 DXT5/BC3 block whose alpha is set up to decode to
// fully opaque (1.0) across the entire 4×4 texel region. We then upload
// this block with the WRONG internalformat enum:
//     COMPRESSED_RGBA_S3TC_DXT3_EXT = 0x83F2   (three.js r181 bug)
// instead of
//     COMPRESSED_RGBA_S3TC_DXT5_EXT = 0x83F3   (correct for BC3 payload)
//
// A fragment shader samples the texture, applies an alpha-test (discard
// if alpha < 0.5), and otherwise outputs the RGB color. Under the wrong
// format, the alpha channel decodes to near-random values across the
// 4×4 block — a subset of fragments discard, producing a stippled
// "noise" pattern. Under the correct format the entire region survives
// the alpha test.

#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef GL_COMPRESSED_RGBA_S3TC_DXT3_EXT
#define GL_COMPRESSED_RGBA_S3TC_DXT3_EXT 0x83F2
#endif
#ifndef GL_COMPRESSED_RGBA_S3TC_DXT5_EXT
#define GL_COMPRESSED_RGBA_S3TC_DXT5_EXT 0x83F3
#endif

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
"void main() {\n"
"    v_uv = a_pos * 0.5 + 0.5;\n"
"    gl_Position = vec4(a_pos, 0.0, 1.0);\n"
"}\n";

static const char* FS =
"#version 330 core\n"
"in vec2 v_uv;\n"
"uniform sampler2D u_tex;\n"
"out vec4 fragColor;\n"
"void main() {\n"
"    vec4 s = texture(u_tex, v_uv);\n"
"    if (s.a < 0.5) discard;\n"
"    fragColor = vec4(s.rgb, 1.0);\n"
"}\n";

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
        -0.8f, -0.8f,   0.8f, -0.8f,   0.8f,  0.8f,
        -0.8f, -0.8f,   0.8f,  0.8f,  -0.8f,  0.8f,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glGenBuffers(1, &vbo);
    glBindVertexArray(vao);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof quad, quad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL);

    // -------------------------------------------------------------------
    // Pre-baked BC3/DXT5 block for a 4×4 gray-with-opaque-alpha region.
    //
    // A DXT5 block is 16 bytes laid out as:
    //   [0..1]  alpha0 (u8), alpha1 (u8)   -- alpha endpoints
    //   [2..7]  48-bit alpha index table (3 bits per texel)
    //   [8..9]  color0 (u16, 5-6-5 RGB)
    //   [10..11] color1 (u16, 5-6-5 RGB)
    //   [12..15] 32-bit color index table (2 bits per texel)
    //
    // Alpha: set both endpoints to 0xFF so every texel decodes to 1.0.
    // Color: solid mid-gray (RGB565 ~ 0x8410 for gray). Both endpoints
    // identical → every color index yields the same gray.
    // -------------------------------------------------------------------
    // Mid-gray in RGB565: R=16 (5-bit), G=32 (6-bit), B=16 (5-bit) → 0x8410
    unsigned short gray565 = ((16u & 0x1F) << 11) | ((32u & 0x3F) << 5) | (16u & 0x1F);
    unsigned char block[16];
    block[0] = 0xFF;                // alpha0 = 1.0
    block[1] = 0xFF;                // alpha1 = 1.0
    memset(&block[2], 0, 6);        // all alpha indices = 0 → alpha0 → 1.0
    block[8]  = (unsigned char)(gray565 & 0xFF);
    block[9]  = (unsigned char)((gray565 >> 8) & 0xFF);
    block[10] = (unsigned char)(gray565 & 0xFF);
    block[11] = (unsigned char)((gray565 >> 8) & 0xFF);
    memset(&block[12], 0, 4);       // color indices = 0 → color0 → gray

    GLuint tex;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);

    // ===================================================================
    // THE BUG: upload BC3 payload but label it as DXT3. Mirrors three.js
    // r181 KTX2Loader.FORMAT_MAP[VK_FORMAT_BC3_*] = RGBA_S3TC_DXT3_Format.
    // Three.js constant 33778 = RGBA_S3TC_DXT3_Format → GL 0x83F2 on upload.
    // Correct would be 33779 / GL 0x83F3 / DXT5_EXT.
    // ===================================================================
    GLenum BUG_FORMAT = GL_COMPRESSED_RGBA_S3TC_DXT3_EXT;  // 0x83F2 (33778)
    // GLenum FIX_FORMAT = GL_COMPRESSED_RGBA_S3TC_DXT5_EXT;  // 0x83F3 (33779)
    glCompressedTexImage2D(GL_TEXTURE_2D, 0,
                           BUG_FORMAT,
                           4, 4, 0,
                           (GLsizei)sizeof(block), block);

    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S,     GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T,     GL_CLAMP_TO_EDGE);

    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    glUseProgram(prog);
    glUniform1i(glGetUniformLocation(prog, "u_tex"), 0);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, tex);

    glDrawArrays(GL_TRIANGLES, 0, 6);
    glXSwapBuffers(dpy, win);

    unsigned char px[4];
    glReadPixels(W/2, H/2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center pixel rgba=%u,%u,%u,%u "
           "(expected ~200 gray, broken 0 background; "
           "internalformat=0x%x, expected 0x83F3=DXT5)\n",
           px[0], px[1], px[2], px[3], BUG_FORMAT);

    glDeleteTextures(1, &tex);
    glDeleteProgram(prog);
    glDeleteVertexArrays(1, &vao);
    glDeleteBuffers(1, &vbo);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}
