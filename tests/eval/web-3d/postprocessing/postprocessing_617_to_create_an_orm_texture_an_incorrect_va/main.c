// SOURCE: https://github.com/pmndrs/postprocessing/issues/617
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const int W = 64, H = 64;

static const char* VS =
"#version 330 core\n"
"layout(location=0) in vec2 aPos;\n"
"out vec2 vMetalnessMapUv;\n"
"void main(){ vMetalnessMapUv = aPos*0.5+0.5; gl_Position = vec4(aPos,0,1); }\n";

static const char* FS =
"#version 330 core\n"
"in vec2 vMetalnessMapUv;\n"
"uniform sampler2D metalnessMap;\n"
"uniform float roughness;\n"
"uniform float metalness;\n"
"layout(location=0) out vec4 out_ORM;\n"
"void main(){\n"
"  float roughnessFactor = roughness;\n"
"  float metalnessFactor = metalness;\n"
"  vec4 texelRoughness = texture(metalnessMap, vMetalnessMapUv);\n"
"  vec4 texelMetalness = texture(metalnessMap, vMetalnessMapUv);\n"
"  roughnessFactor *= texelRoughness.g;\n"
"  metalnessFactor *= texelMetalness.b;\n"
"  out_ORM = vec4(0.0, 0.0, 0.0, 1.0);\n"
"  out_ORM.y = roughnessFactor;\n"
"  out_ORM.z = metalness;\n"
"}\n";

static GLuint compile(GLenum type, const char* src){
  GLuint s = glCreateShader(type);
  glShaderSource(s, 1, &src, NULL);
  glCompileShader(s);
  GLint ok; glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
  if (!ok){ char log[1024]; glGetShaderInfoLog(s, 1024, NULL, log); fprintf(stderr, "shader: %s\n", log); exit(1); }
  return s;
}

static GLuint link_prog(GLuint vs, GLuint fs){
  GLuint p = glCreateProgram();
  glAttachShader(p, vs); glAttachShader(p, fs);
  glLinkProgram(p);
  GLint ok; glGetProgramiv(p, GL_LINK_STATUS, &ok);
  if (!ok){ char log[1024]; glGetProgramInfoLog(p, 1024, NULL, log); fprintf(stderr, "link: %s\n", log); exit(1); }
  return p;
}

int main(){
  Display* dpy = XOpenDisplay(NULL);
  if (!dpy){ fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
  int screen = DefaultScreen(dpy);
  int vis_attribs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
  XVisualInfo* vi = glXChooseVisual(dpy, screen, vis_attribs);
  Colormap cmap = XCreateColormap(dpy, RootWindow(dpy, screen), vi->visual, AllocNone);
  XSetWindowAttributes swa = {0}; swa.colormap = cmap; swa.event_mask = StructureNotifyMask;
  Window win = XCreateWindow(dpy, RootWindow(dpy, screen), 0, 0, W, H, 0, vi->depth,
                             InputOutput, vi->visual, CWColormap|CWEventMask, &swa);
  XMapWindow(dpy, win);
  GLXContext ctx_legacy = glXCreateContext(dpy, vi, NULL, True);
  glXMakeCurrent(dpy, win, ctx_legacy);

  PFNGLXCREATECONTEXTATTRIBSARBPROC glXCreateContextAttribsARB =
    (PFNGLXCREATECONTEXTATTRIBSARBPROC)glXGetProcAddressARB((const GLubyte*)"glXCreateContextAttribsARB");
  int fbc_attribs[] = { GLX_RENDER_TYPE, GLX_RGBA_BIT, GLX_DOUBLEBUFFER, True, None };
  int fbc_n = 0;
  GLXFBConfig* fbc = glXChooseFBConfig(dpy, screen, fbc_attribs, &fbc_n);
  int ctx_attribs[] = {
    GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
    GLX_CONTEXT_MINOR_VERSION_ARB, 3,
    GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
    None
  };
  GLXContext ctx = glXCreateContextAttribsARB(dpy, fbc[0], NULL, True, ctx_attribs);
  glXMakeCurrent(dpy, 0, 0);
  glXDestroyContext(dpy, ctx_legacy);
  glXMakeCurrent(dpy, win, ctx);

  GLuint vao; glGenVertexArrays(1, &vao); glBindVertexArray(vao);
  float quad[] = { -1.0f,-1.0f, 1.0f,-1.0f, -1.0f,1.0f, 1.0f,1.0f };
  GLuint vbo; glGenBuffers(1, &vbo);
  glBindBuffer(GL_ARRAY_BUFFER, vbo);
  glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
  glEnableVertexAttribArray(0);
  glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);

  // ORM-packed texture: R=occlusion, G=roughness, B=metalness
  GLuint tex; glGenTextures(1, &tex);
  glBindTexture(GL_TEXTURE_2D, tex);
  unsigned char* pixels = (unsigned char*)malloc((size_t)W*H*4);
  for (int i = 0; i < W*H; i++){
    pixels[4*i+0] = 255;  // occlusion
    pixels[4*i+1] = 180;  // roughness ~= 0.706
    pixels[4*i+2] = 128;  // metalness ~= 0.502
    pixels[4*i+3] = 255;
  }
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, W, H, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
  free(pixels);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

  GLuint vs = compile(GL_VERTEX_SHADER, VS);
  GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
  GLuint prog = link_prog(vs, fs);
  glUseProgram(prog);
  glUniform1i(glGetUniformLocation(prog, "metalnessMap"), 0);
  glUniform1f(glGetUniformLocation(prog, "roughness"), 1.0f);
  glUniform1f(glGetUniformLocation(prog, "metalness"), 1.0f);

  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, tex);

  glViewport(0, 0, W, H);
  glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
  glClear(GL_COLOR_BUFFER_BIT);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

  unsigned char center[4];
  glReadPixels(W/2, H/2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, center);
  printf("ORM center pixel rgba=%d,%d,%d,%d\n", center[0], center[1], center[2], center[3]);

  glXSwapBuffers(dpy, win);

  glXMakeCurrent(dpy, 0, 0);
  glXDestroyContext(dpy, ctx);
  XDestroyWindow(dpy, win);
  XCloseDisplay(dpy);
  return 0;
}