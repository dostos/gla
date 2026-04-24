// SOURCE: https://github.com/mapbox/mapbox-gl-js/issues/4552
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char* VSRC =
"#version 330 core\n"
"layout(location=0) in vec2 a_pos;\n"
"layout(location=1) in vec2 a_uv;\n"
"uniform mat4 u_proj;\n"
"out vec2 v_uv;\n"
"void main(){ v_uv = a_uv; gl_Position = u_proj * vec4(a_pos, 0.0, 1.0); }\n";

static const char* FSRC =
"#version 330 core\n"
"in vec2 v_uv;\n"
"uniform sampler2D u_tex;\n"
"out vec4 o_color;\n"
"void main(){ o_color = texture(u_tex, v_uv); }\n";

static GLuint compile_shader(GLenum type, const char* src) {
    GLuint sh = glCreateShader(type);
    glShaderSource(sh, 1, &src, NULL);
    glCompileShader(sh);
    GLint ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[512];
        glGetShaderInfoLog(sh, sizeof(log), NULL, log);
        fprintf(stderr, "shader compile: %s\n", log);
    }
    return sh;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    int attrs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attrs);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 256, 256, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    const int W = 256, H = 256;
    glViewport(0, 0, W, H);

    // Raster tile texture: alternating single-pixel vertical stripes (black / white),
    // like a high-frequency pattern in a map tile (e.g. thin labels or grid lines).
    unsigned char* pixels = (unsigned char*)malloc((size_t)W * H * 4);
    for (int y = 0; y < H; y++) {
        for (int x = 0; x < W; x++) {
            unsigned char c = (x & 1) ? 255 : 0;
            int i = (y * W + x) * 4;
            pixels[i] = c; pixels[i+1] = c; pixels[i+2] = c; pixels[i+3] = 255;
        }
    }
    GLuint tex;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, W, H, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
    free(pixels);

    // Tile quad in world units, large enough to cover the camera view under
    // any small pan. UVs scale so each 256-unit step wraps the texture once.
    float quad[] = {
        -512.0f, -512.0f,   -2.0f, -2.0f,
         512.0f, -512.0f,    2.0f, -2.0f,
        -512.0f,  512.0f,   -2.0f,  2.0f,
         512.0f,  512.0f,    2.0f,  2.0f,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glGenBuffers(1, &vbo);
    glBindVertexArray(vao);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 16, (void*)0);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 16, (void*)8);
    glEnableVertexAttribArray(1);

    GLuint vs = compile_shader(GL_VERTEX_SHADER, VSRC);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, FSRC);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);
    glUseProgram(prog);
    glUniform1i(glGetUniformLocation(prog, "u_tex"), 0);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, tex);

    // Camera state. Viewport is W x H device pixels; one world unit == one
    // device pixel (discrete zoom level -- no scale). The projection maps
    // the rectangle [camX, camX+W] x [camY, camY+H] in world space to the
    // full NDC cube [-1, 1]^2.
    float camX = 100.37f;
    float camY =  50.21f;
    float sx = 2.0f / (float)W;
    float sy = 2.0f / (float)H;
    float proj[16] = {
        sx,            0,             0, 0,
         0,           sy,             0, 0,
         0,            0,             1, 0,
        -1.0f - camX*sx, -1.0f - camY*sy, 0, 1,
    };
    glUniformMatrix4fv(glGetUniformLocation(prog, "u_proj"), 1, GL_FALSE, proj);

    glClearColor(0.5f, 0.5f, 0.5f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    glFinish();

    unsigned char row[256 * 4];
    glReadPixels(0, H / 2, W, 1, GL_RGBA, GL_UNSIGNED_BYTE, row);
    int extreme = 0, mid = 0;
    for (int x = 8; x < W - 8; x++) {
        int r = row[x * 4];
        if (r < 16 || r > 240) extreme++;
        else if (r > 64 && r < 192) mid++;
    }
    printf("center_scanline: extreme_pixels=%d mid_pixels=%d sampled=%d\n",
           extreme, mid, W - 16);
    printf("sample row[128..135]: %d %d %d %d %d %d %d %d\n",
           row[128*4], row[129*4], row[130*4], row[131*4],
           row[132*4], row[133*4], row[134*4], row[135*4]);

    glXSwapBuffers(dpy, win);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}