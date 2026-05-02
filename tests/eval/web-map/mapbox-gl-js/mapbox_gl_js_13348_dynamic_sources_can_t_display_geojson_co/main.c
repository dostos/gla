// SOURCE: https://github.com/mapbox/mapbox-gl-js/issues/13348
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char* VS =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "uniform vec2 uTileOrigin;\n"
    "uniform float uTileSize;\n"
    "void main(){\n"
    "  vec2 local = (aPos - uTileOrigin) / uTileSize;\n"
    "  gl_Position = vec4(local * 2.0 - 1.0, 0.0, 1.0);\n"
    "}\n";

static const char* FS =
    "#version 330 core\n"
    "out vec4 FragColor;\n"
    "uniform vec3 uColor;\n"
    "void main(){ FragColor = vec4(uColor, 1.0); }\n";

static GLuint compile(GLenum type, const char* src){
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL); glCompileShader(s);
    return s;
}

static GLuint link_program(void){
    GLuint vs = compile(GL_VERTEX_SHADER, VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    GLuint p = glCreateProgram();
    glAttachShader(p, vs); glAttachShader(p, fs); glLinkProgram(p);
    glDeleteShader(vs); glDeleteShader(fs);
    return p;
}

/* A polygon that crosses two adjacent tile boundaries (world-space coords). */
static float g_world_polygon[] = {
    0.30f, 0.40f,
    1.60f, 0.45f,
    1.70f, 1.30f,
    0.35f, 1.25f,
};

/* Dynamic-source emulation: when the source is marked "dynamic", feature
   vertex data is appended into a shared buffer and features are sliced per
   tile by index ranges. We emulate the observed rendering pattern by
   issuing per-tile draws that re-upload the feature's vertices using only
   the subset of indices whose first vertex falls inside that tile's AABB. */
static void upload_tile_slice_dynamic(GLuint vbo, float ox, float oy, float ts){
    float buf[16]; int n = 0;
    int count = sizeof(g_world_polygon) / (2 * sizeof(float));
    for(int i = 0; i < count; ++i){
        float x = g_world_polygon[2*i+0];
        float y = g_world_polygon[2*i+1];
        if(x >= ox && x < ox+ts && y >= oy && y < oy+ts){
            buf[2*n+0] = x; buf[2*n+1] = y; n++;
        }
    }
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, n * 2 * sizeof(float), buf, GL_DYNAMIC_DRAW);
    if(n >= 3) glDrawArrays(GL_TRIANGLE_FAN, 0, n);
}

int main(void){
    Display* dpy = XOpenDisplay(NULL);
    if(!dpy){ fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int attr[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, attr);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 512, 512, 0, vi->depth,
                               InputOutput, vi->visual, CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    GLuint prog = link_program();
    glUseProgram(prog);

    GLuint vao, vbo;
    glGenVertexArrays(1, &vao); glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, 0);

    GLint locOrigin = glGetUniformLocation(prog, "uTileOrigin");
    GLint locSize   = glGetUniformLocation(prog, "uTileSize");
    GLint locColor  = glGetUniformLocation(prog, "uColor");

    glViewport(0, 0, 512, 512);
    glClearColor(0.1f, 0.1f, 0.1f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    float tile_size = 1.0f;
    float tiles[4][2] = { {0,0}, {1,0}, {0,1}, {1,1} };
    float colors[4][3] = {
        {0.9f, 0.3f, 0.3f}, {0.3f, 0.9f, 0.3f},
        {0.3f, 0.3f, 0.9f}, {0.9f, 0.9f, 0.3f},
    };

    for(int t = 0; t < 4; ++t){
        glUniform2f(locOrigin, tiles[t][0], tiles[t][1]);
        glUniform1f(locSize, tile_size);
        glUniform3f(locColor, colors[t][0], colors[t][1], colors[t][2]);
        glViewport((int)(tiles[t][0]*256), (int)(tiles[t][1]*256), 256, 256);
        upload_tile_slice_dynamic(vbo, tiles[t][0], tiles[t][1], tile_size);
    }

    glXSwapBuffers(dpy, win);

    unsigned char px[4];
    glReadPixels(256, 256, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("seam pixel rgba=%d,%d,%d,%d\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}