// SOURCE: https://github.com/godotengine/godot/issues/86530
// Reproduces the Godot clearcoat NaN-pixel pattern.
//
// The symptom reported upstream is "NaN pixels" appearing as flickering
// bright/black specks that are visible through occluders when glow is on.
// The reproduction below evaluates a GGX-style clearcoat distribution with
// roughness = 0 and NdotH = 1 — a configuration that makes the GGX
// denominator collapse to zero:
//
//   a2 = 0
//   denom = 1*1 * (0 - 1) + 1 = 0
//   D     = 0 / (pi * 0 * 0)  = NaN
//
// Writing that NaN to an RGBA16F HDR attachment is the same substrate Godot
// uses for its lighting pass. The NaN is invisible in raw output (it tonemaps
// to 0 on some backends, to garbage on others) but poisons any downstream
// blur/downsample — which is why the upstream report only shows the artifact
// once glow/bloom is enabled.

#define GL_GLEXT_PROTOTYPES 1
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int xerr(Display* d, XErrorEvent* e) { (void)d; (void)e; return 0; }

static const char* VS =
    "#version 330 core\n"
    "layout(location=0) in vec2 a_pos;\n"
    "out vec2 v_uv;\n"
    "void main() {\n"
    "  v_uv = a_pos * 0.5 + 0.5;\n"
    "  gl_Position = vec4(a_pos, 0.0, 1.0);\n"
    "}\n";

// Clearcoat-style GGX term with the NaN-producing configuration at roughness=0.
// Matches the shape of the term in Godot's SceneForwardClusteredShaderRD
// clearcoat path (distribution + Schlick Fresnel) without copying source.
static const char* FS =
    "#version 330 core\n"
    "in vec2 v_uv;\n"
    "out vec4 fragColor;\n"
    "uniform float u_clearcoat_roughness;\n"
    "uniform float u_clearcoat;\n"
    "void main() {\n"
    "  float a     = u_clearcoat_roughness;\n"
    "  float a2    = a * a;\n"
    "  float NdotH = 1.0;\n"
    "  float denom = NdotH * NdotH * (a2 - 1.0) + 1.0;\n"
    "  float D     = a2 / (3.14159265 * denom * denom);\n"
    "  float F     = 0.04 + 0.96 * pow(1.0 - NdotH, 5.0);\n"
    "  float cc    = u_clearcoat * D * F;\n"
    "  fragColor   = vec4(vec3(cc), 1.0);\n"
    "}\n";

static GLuint compile(GLenum type, const char* src) {
  GLuint s = glCreateShader(type);
  glShaderSource(s, 1, &src, NULL);
  glCompileShader(s);
  GLint ok = 0;
  glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
  if (!ok) {
    char log[2048];
    glGetShaderInfoLog(s, sizeof(log), NULL, log);
    fprintf(stderr, "shader compile error: %s\n", log);
    exit(1);
  }
  return s;
}

int main(void) {
  XSetErrorHandler(xerr);
  Display* dpy = XOpenDisplay(NULL);
  if (!dpy) { fprintf(stderr, "no display\n"); return 1; }

  int attribs[] = {
    GLX_RGBA, GLX_DOUBLEBUFFER, True,
    GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8,
    GLX_DEPTH_SIZE, 24, None
  };
  XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attribs);
  if (!vi) { fprintf(stderr, "no visual\n"); XCloseDisplay(dpy); return 1; }

  Window root = RootWindow(dpy, vi->screen);
  Colormap cmap = XCreateColormap(dpy, root, vi->visual, AllocNone);
  XSetWindowAttributes swa = {0};
  swa.colormap = cmap;
  Window win = XCreateWindow(dpy, root, 0, 0, 256, 256, 0,
                             vi->depth, InputOutput, vi->visual,
                             CWColormap, &swa);
  GLXContext ctx = glXCreateContext(dpy, vi, NULL, True);
  glXMakeCurrent(dpy, win, ctx);

  GLuint vs   = compile(GL_VERTEX_SHADER, VS);
  GLuint fs   = compile(GL_FRAGMENT_SHADER, FS);
  GLuint prog = glCreateProgram();
  glAttachShader(prog, vs);
  glAttachShader(prog, fs);
  glLinkProgram(prog);

  float quad[] = { -1,-1, 1,-1, -1,1, 1,1 };
  GLuint vao, vbo;
  glGenVertexArrays(1, &vao);
  glGenBuffers(1, &vbo);
  glBindVertexArray(vao);
  glBindBuffer(GL_ARRAY_BUFFER, vbo);
  glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
  glEnableVertexAttribArray(0);
  glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, 0);

  GLuint tex, fbo;
  glGenTextures(1, &tex);
  glBindTexture(GL_TEXTURE_2D, tex);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, 256, 256, 0, GL_RGBA, GL_FLOAT, NULL);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
  glGenFramebuffers(1, &fbo);
  glBindFramebuffer(GL_FRAMEBUFFER, fbo);
  glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);

  glViewport(0, 0, 256, 256);
  glClearColor(0, 0, 0, 1);
  glClear(GL_COLOR_BUFFER_BIT);
  glUseProgram(prog);
  glUniform1f(glGetUniformLocation(prog, "u_clearcoat_roughness"), 0.0f);
  glUniform1f(glGetUniformLocation(prog, "u_clearcoat"), 1.0f);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

  glBindFramebuffer(GL_READ_FRAMEBUFFER, fbo);
  glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
  glBlitFramebuffer(0, 0, 256, 256, 0, 0, 256, 256,
                    GL_COLOR_BUFFER_BIT, GL_NEAREST);
  glXSwapBuffers(dpy, win);

  glXMakeCurrent(dpy, None, NULL);
  glXDestroyContext(dpy, ctx);
  XDestroyWindow(dpy, win);
  XCloseDisplay(dpy);
  return 0;
}