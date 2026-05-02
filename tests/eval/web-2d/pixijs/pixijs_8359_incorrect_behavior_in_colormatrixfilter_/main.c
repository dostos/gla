// SOURCE: https://github.com/pixijs/pixijs/issues/8359
#define GL_GLEXT_PROTOTYPES 1
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char* VS =
  "#version 330 core\n"
  "layout(location=0) in vec2 aPos;\n"
  "void main(){ gl_Position = vec4(aPos, 0.0, 1.0); }\n";

// Fragment shader mirrors pixi.js ColorMatrixFilter's shader: a 4x5 color
// matrix whose rightmost column is an additive offset in the same unit space
// as the input color (0..1). The diagonal scales and the offset column are
// consumed without any further normalization.
static const char* FS =
  "#version 330 core\n"
  "out vec4 fragColor;\n"
  "uniform float m[20];\n"
  "uniform vec4 uInput;\n"
  "void main(){\n"
  "  vec4 c = uInput;\n"
  "  fragColor.r = m[0]*c.r + m[1]*c.g + m[2]*c.b + m[3]*c.a + m[4];\n"
  "  fragColor.g = m[5]*c.r + m[6]*c.g + m[7]*c.b + m[8]*c.a + m[9];\n"
  "  fragColor.b = m[10]*c.r + m[11]*c.g + m[12]*c.b + m[13]*c.a + m[14];\n"
  "  fragColor.a = m[15]*c.r + m[16]*c.g + m[17]*c.b + m[18]*c.a + m[19];\n"
  "}\n";

// Pattern port of pixi.js ColorMatrixFilter.contrast(1, /*multiply=*/true)
// starting from an identity matrix.
//   Step A: contrast() builds a 4x5 matrix with diagonal v = amount+1 = 2
//           and offset o = -128 * (v-1) = -128 in pixi's 0..255 convention.
//   Step B: _loadMatrix(..., multiply=true) delegates to _colorMatrix, which
//           multiplies the incoming matrix by the current identity matrix
//           (leaving it unchanged) AND THEN divides the rightmost offset
//           column entries by 255. The multiply=false path skips this divide.
static void build_buggy_contrast_matrix(float out[20]) {
    const float v = 2.0f;
    const float o = -128.0f * (v - 1.0f);
    float m[20] = {
        v, 0, 0, 0, o,
        0, v, 0, 0, o,
        0, 0, v, 0, o,
        0, 0, 0, 1, 0,
    };
    m[4]  /= 255.0f;
    m[9]  /= 255.0f;
    m[14] /= 255.0f;
    m[19] /= 255.0f;
    memcpy(out, m, sizeof(m));
}

static GLuint compile_shader(GLenum type, const char* src) {
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok = 0;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog(s, sizeof(log), NULL, log);
        fprintf(stderr, "shader compile error: %s\n", log);
        exit(1);
    }
    return s;
}

static int x_error_handler(Display *d, XErrorEvent *e) {
    (void)d; (void)e;
    return 0;
}

int main(void) {
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    XSetErrorHandler(x_error_handler);

    int fb_attribs[] = {
        GLX_X_RENDERABLE, True,
        GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_RENDER_TYPE, GLX_RGBA_BIT,
        GLX_X_VISUAL_TYPE, GLX_TRUE_COLOR,
        GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8,
        GLX_BLUE_SIZE, 8, GLX_ALPHA_SIZE, 8,
        GLX_DEPTH_SIZE, 24,
        GLX_DOUBLEBUFFER, True,
        None
    };
    int fbc_count = 0;
    GLXFBConfig *fbc = glXChooseFBConfig(dpy, DefaultScreen(dpy), fb_attribs, &fbc_count);
    if (!fbc || !fbc_count) { fprintf(stderr, "no FBConfig\n"); return 1; }
    XVisualInfo *vi = glXGetVisualFromFBConfig(dpy, fbc[0]);

    Window root = RootWindow(dpy, vi->screen);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 256, 256, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    PFNGLXCREATECONTEXTATTRIBSARBPROC glXCreateContextAttribsARB =
        (PFNGLXCREATECONTEXTATTRIBSARBPROC)
        glXGetProcAddressARB((const GLubyte*)"glXCreateContextAttribsARB");
    int ctx_attribs[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        None
    };
    GLXContext ctx = glXCreateContextAttribsARB(dpy, fbc[0], NULL, True, ctx_attribs);
    if (!ctx) { fprintf(stderr, "no GL 3.3 core context\n"); return 1; }
    glXMakeCurrent(dpy, win, ctx);

    GLuint vs = compile_shader(GL_VERTEX_SHADER, VS);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, FS);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);
    glUseProgram(prog);

    float verts[] = { -1.f,-1.f,  1.f,-1.f,  -1.f,1.f,  1.f,1.f };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, 0);
    glEnableVertexAttribArray(0);

    float m[20];
    build_buggy_contrast_matrix(m);
    GLint locM = glGetUniformLocation(prog, "m");
    glUniform1fv(locM, 20, m);

    // Bright gray 0.7 input. Under the multiply=false path pixi would produce
    // offset -128, clamping every channel to 0 (black). The buggy multiply=true
    // path gives offset -128/255 ~= -0.502, so output is 2*0.7 - 0.502 ~= 0.898
    // -- near-white -- even though the user expects parity with multiply=false.
    GLint locIn = glGetUniformLocation(prog, "uInput");
    glUniform4f(locIn, 0.7f, 0.7f, 0.7f, 1.0f);

    glViewport(0, 0, 256, 256);
    glClearColor(0.f, 0.f, 0.f, 1.f);
    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    glXSwapBuffers(dpy, win);
    return 0;
}