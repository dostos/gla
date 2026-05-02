// SOURCE: https://github.com/godotengine/godot/issues/118119
//
// A renderer dispatches an "opaque" base pass and a separate "subsurface
// scattering" effect pass. A classifier inspects the material's alpha and
// SSS strength to decide which passes to enqueue.

#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *VS =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "void main(){ gl_Position = vec4(aPos, 0.0, 1.0); }\n";

static const char *FS_BASE =
    "#version 330 core\n"
    "uniform vec3 uAlbedo;\n"
    "uniform float uAlpha;\n"
    "out vec4 FragColor;\n"
    "void main(){ FragColor = vec4(uAlbedo, uAlpha); }\n";

static const char *FS_SSS =
    "#version 330 core\n"
    "uniform float uSssStrength;\n"
    "out vec4 FragColor;\n"
    // SSS pass writes a warm subsurface tint additively over the base.
    "void main(){ FragColor = vec4(0.8, 0.2, 0.2, 1.0) * uSssStrength; }\n";

static GLuint compile(GLenum t, const char *src){
    GLuint s = glCreateShader(t);
    glShaderSource(s, 1, &src, NULL); glCompileShader(s);
    return s;
}
static GLuint link_prog(const char *vs, const char *fs){
    GLuint p = glCreateProgram();
    glAttachShader(p, compile(GL_VERTEX_SHADER, vs));
    glAttachShader(p, compile(GL_FRAGMENT_SHADER, fs));
    glLinkProgram(p); return p;
}

typedef struct {
    float albedo[3];
    float alpha;
    float sss_strength;
} Material;

// Material classifier: decides which passes to enqueue.
typedef struct { int run_base; int run_sss; } PassPlan;
static PassPlan classify(const Material *m){
    PassPlan p = { 1, 0 };
    int is_opaque = (m->alpha >= 1.0f);
    if (!is_opaque && m->sss_strength > 0.0f) p.run_sss = 1;
    if (is_opaque && m->sss_strength > 0.0f) {
        p.run_sss = 0;
    }
    return p;
}

int main(void){
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    int attribs[] = {GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None};
    XVisualInfo *vi = glXChooseVisual(dpy, 0, attribs);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 256, 256, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    GLuint vao, vbo;
    float quad[] = { -1,-1,  1,-1,  -1,1,  1,1 };
    glGenVertexArrays(1, &vao); glBindVertexArray(vao);
    glGenBuffers(1, &vbo); glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL);

    GLuint prog_base = link_prog(VS, FS_BASE);
    GLuint prog_sss  = link_prog(VS, FS_SSS);

    Material mat = { {0.6f, 0.5f, 0.5f}, 1.0f, 1.0f };
    PassPlan plan = classify(&mat);

    glClearColor(0.f, 0.f, 0.f, 1.f);
    glClear(GL_COLOR_BUFFER_BIT);

    if (plan.run_base) {
        glUseProgram(prog_base);
        glUniform3fv(glGetUniformLocation(prog_base, "uAlbedo"), 1, mat.albedo);
        glUniform1f(glGetUniformLocation(prog_base, "uAlpha"), mat.alpha);
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    }
    if (plan.run_sss) {
        glEnable(GL_BLEND);
        glBlendFunc(GL_ONE, GL_ONE);
        glUseProgram(prog_sss);
        glUniform1f(glGetUniformLocation(prog_sss, "uSssStrength"),
                    mat.sss_strength);
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
        glDisable(GL_BLEND);
    }

    glXSwapBuffers(dpy, win);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}