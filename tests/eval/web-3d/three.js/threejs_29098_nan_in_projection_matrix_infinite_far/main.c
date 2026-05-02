// SOURCE: https://github.com/mrdoob/three.js/issues/29098
//
// Reproduces three.js WebXRDepthSensing NaN projection matrix: on Quest 3,
// the depth-sensing module reports depthFar=Infinity. three.js assigns
// camera.far = Infinity, then Matrix4.makePerspective evaluates
//   m[10] = (far+near)/(near-far)   -> Inf / -Inf = NaN
//   m[14] = 2*far*near/(near-far)   -> Inf / -Inf = NaN
// After the XR session ends, this polluted matrix is used to render the
// scene with the user camera. Every vertex gets NaN in gl_Position.z; GPU
// clipping fails all comparisons involving NaN and discards every primitive,
// so the canvas is blank.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <X11/Xlib.h>
#define GL_GLEXT_PROTOTYPES 1
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>

typedef GLXContext (*CtxAttribsProc)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

#define W 400
#define H 300

static int x_error_handler(Display *dpy, XErrorEvent *ev) {
    char buf[256];
    XGetErrorText(dpy, ev->error_code, buf, sizeof(buf));
    fprintf(stderr, "X Error (suppressed): %s (opcode %d/%d)\n",
            buf, ev->request_code, ev->minor_code);
    return 0;
}

static const char *VS =
"#version 330 core\n"
"layout(location=0) in vec3 aPos;\n"
"uniform mat4 uProjection;\n"
"void main(){ gl_Position = uProjection * vec4(aPos, 1.0); }\n";

static const char *FS =
"#version 330 core\n"
"out vec4 o;\n"
"void main(){ o = vec4(1.0, 0.5, 0.2, 1.0); }\n";

static GLuint compile(GLenum type, const char *src) {
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok = 0;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[512];
        glGetShaderInfoLog(s, sizeof(log), NULL, log);
        fprintf(stderr, "shader compile: %s\n", log);
        exit(1);
    }
    return s;
}

int main(void) {
    XSetErrorHandler(x_error_handler);

    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }

    int fb_attribs[] = {
        GLX_X_RENDERABLE, True,
        GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_RENDER_TYPE, GLX_RGBA_BIT,
        GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8,
        GLX_ALPHA_SIZE, 8, GLX_DEPTH_SIZE, 24,
        GLX_DOUBLEBUFFER, True,
        None
    };
    int fbcount = 0;
    GLXFBConfig *fbc = glXChooseFBConfig(dpy, DefaultScreen(dpy), fb_attribs, &fbcount);
    if (!fbc || fbcount == 0) { fprintf(stderr, "glXChooseFBConfig failed\n"); return 1; }
    XVisualInfo *vi = glXGetVisualFromFBConfig(dpy, fbc[0]);

    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    memset(&swa, 0, sizeof(swa));
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, W, H, 0, vi->depth,
                               InputOutput, vi->visual, CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    CtxAttribsProc glXCreateContextAttribsARB =
        (CtxAttribsProc) glXGetProcAddressARB((const GLubyte *)"glXCreateContextAttribsARB");
    int ctx_attribs[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        None
    };
    GLXContext ctx = glXCreateContextAttribsARB(dpy, fbc[0], 0, True, ctx_attribs);
    if (!ctx) { fprintf(stderr, "no GL 3.3 core context\n"); return 1; }
    glXMakeCurrent(dpy, win, ctx);

    GLuint vs = compile(GL_VERTEX_SHADER, VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);

    // A centered triangle in front of the camera. With a healthy projection
    // this fills a large fraction of the viewport with the orange fragment.
    float verts[] = {
        -0.5f, -0.5f, -2.0f,
         0.5f, -0.5f, -2.0f,
         0.0f,  0.5f, -2.0f,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), (void*)0);

    // Replicate three.js Matrix4.makePerspective with far = Infinity.
    //   m[0]  = 2*near/(right-left)        = near/right  (symmetric frustum)
    //   m[5]  = 2*near/(top-bottom)        = near/top
    //   m[10] = (far+near)/(near-far)      = NaN
    //   m[14] = 2*far*near/(near-far)      = NaN
    //   m[11] = -1
    float near = 0.1f;
    float far  = INFINITY;
    float top  = near * tanf(0.5f);
    float right = top * ((float)W / (float)H);

    float proj[16] = {
        near / right, 0.0f, 0.0f, 0.0f,
        0.0f, near / top, 0.0f, 0.0f,
        0.0f, 0.0f, (far + near) / (near - far), -1.0f,
        0.0f, 0.0f, (2.0f * far * near) / (near - far), 0.0f,
    };

    glUseProgram(prog);
    GLint locProj = glGetUniformLocation(prog, "uProjection");
    glUniformMatrix4fv(locProj, 1, GL_FALSE, proj);

    glViewport(0, 0, W, H);
    glClearColor(0.1f, 0.1f, 0.3f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glXSwapBuffers(dpy, win);

    glDeleteShader(vs);
    glDeleteShader(fs);
    glDeleteProgram(prog);
    glDeleteBuffers(1, &vbo);
    glDeleteVertexArrays(1, &vao);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XFreeColormap(dpy, swa.colormap);
    XFree(vi);
    XFree(fbc);
    XCloseDisplay(dpy);

    printf("r1: frame submitted with NaN projection\n");
    return 0;
}