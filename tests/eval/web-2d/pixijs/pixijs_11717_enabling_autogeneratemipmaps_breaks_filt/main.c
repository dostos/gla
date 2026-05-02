// SOURCE: https://github.com/pixijs/pixijs/issues/11717
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef GLXContext (*glXCreateContextAttribsARBProc)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

static const char *VS =
  "#version 330 core\n"
  "layout(location=0) in vec2 p;\n"
  "out vec2 uv;\n"
  "void main(){uv=p*0.5+0.5;gl_Position=vec4(p,0,1);}\n";

static const char *FS_FILL =
  "#version 330 core\n"
  "in vec2 uv;\n"
  "out vec4 o;\n"
  "void main(){o=vec4(uv,0.2,1);}\n";

static const char *FS_FILTER =
  "#version 330 core\n"
  "in vec2 uv;\n"
  "out vec4 o;\n"
  "uniform sampler2D tex;\n"
  // Filter samples at LOD=2 — mimics a filter that reads a downscaled mip level
  // while autoGenerateMipmaps has allocated mipmap storage but glGenerateMipmap
  // was never called after rendering into level 0.
  "void main(){o=textureLod(tex,uv,2.0);}\n";

static GLuint compile_shader(GLenum t, const char *s){
  GLuint sh=glCreateShader(t);
  glShaderSource(sh,1,&s,NULL);
  glCompileShader(sh);
  GLint ok; glGetShaderiv(sh,GL_COMPILE_STATUS,&ok);
  if(!ok){ char buf[1024]; glGetShaderInfoLog(sh,sizeof(buf),NULL,buf); fprintf(stderr,"shader: %s\n",buf); exit(1); }
  return sh;
}

static GLuint link_prog(GLuint v, GLuint f){
  GLuint p=glCreateProgram();
  glAttachShader(p,v); glAttachShader(p,f);
  glLinkProgram(p);
  GLint ok; glGetProgramiv(p,GL_LINK_STATUS,&ok);
  if(!ok){ char buf[1024]; glGetProgramInfoLog(p,sizeof(buf),NULL,buf); fprintf(stderr,"link: %s\n",buf); exit(1); }
  return p;
}

int main(void){
  Display *dpy=XOpenDisplay(NULL);
  if(!dpy){ fprintf(stderr,"no display\n"); return 1; }

  int fbattrs[]={ GLX_X_RENDERABLE,True, GLX_RENDER_TYPE,GLX_RGBA_BIT,
                  GLX_RED_SIZE,8, GLX_GREEN_SIZE,8, GLX_BLUE_SIZE,8,
                  GLX_ALPHA_SIZE,8, GLX_DEPTH_SIZE,24, GLX_DOUBLEBUFFER,True, None };
  int nfb=0;
  GLXFBConfig *fbs=glXChooseFBConfig(dpy, DefaultScreen(dpy), fbattrs, &nfb);
  if(!fbs || !nfb){ fprintf(stderr,"no fbconfig\n"); return 1; }
  GLXFBConfig fb=fbs[0];
  XVisualInfo *vi=glXGetVisualFromFBConfig(dpy, fb);

  Window root=RootWindow(dpy, vi->screen);
  XSetWindowAttributes swa={0};
  swa.colormap=XCreateColormap(dpy, root, vi->visual, AllocNone);
  swa.event_mask=StructureNotifyMask;
  Window win=XCreateWindow(dpy, root, 0,0, 512,512, 0, vi->depth, InputOutput,
                           vi->visual, CWColormap|CWEventMask, &swa);
  XMapWindow(dpy, win);

  glXCreateContextAttribsARBProc glXCreateContextAttribsARB =
    (glXCreateContextAttribsARBProc)glXGetProcAddressARB((const GLubyte*)"glXCreateContextAttribsARB");
  int ctxattrs[]={ GLX_CONTEXT_MAJOR_VERSION_ARB, 3, GLX_CONTEXT_MINOR_VERSION_ARB, 3,
                   GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB, None };
  GLXContext ctx=glXCreateContextAttribsARB(dpy, fb, NULL, True, ctxattrs);
  if(!ctx){ fprintf(stderr,"no ctx\n"); return 1; }
  glXMakeCurrent(dpy, win, ctx);

  float quad[]={-1,-1, 1,-1, -1,1, 1,1};
  GLuint vao,vbo;
  glGenVertexArrays(1,&vao); glBindVertexArray(vao);
  glGenBuffers(1,&vbo); glBindBuffer(GL_ARRAY_BUFFER,vbo);
  glBufferData(GL_ARRAY_BUFFER,sizeof(quad),quad,GL_STATIC_DRAW);
  glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,2*sizeof(float),0);
  glEnableVertexAttribArray(0);

  GLuint vs=compile_shader(GL_VERTEX_SHADER,VS);
  GLuint fill=link_prog(vs,compile_shader(GL_FRAGMENT_SHADER,FS_FILL));
  GLuint filt=link_prog(vs,compile_shader(GL_FRAGMENT_SHADER,FS_FILTER));

  // Filter render-target texture: 4 mip levels allocated; only level 0 will be written.
  // Mimics PixiJS TexturePool with autoGenerateMipmaps=true leaking into the filter
  // pool — storage is reserved for mipmaps, but glGenerateMipmap is never called.
  GLuint rt;
  glGenTextures(1,&rt);
  glBindTexture(GL_TEXTURE_2D,rt);
  int sz=256;
  for(int lvl=0; lvl<4; lvl++){
    glTexImage2D(GL_TEXTURE_2D, lvl, GL_RGBA8, sz, sz, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    sz/=2;
  }
  glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_BASE_LEVEL,0);
  glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAX_LEVEL,3);
  glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR_MIPMAP_LINEAR);
  glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);

  GLuint fbo;
  glGenFramebuffers(1,&fbo);
  glBindFramebuffer(GL_FRAMEBUFFER,fbo);
  glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,rt,0);
  if(glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE){
    fprintf(stderr,"fbo incomplete\n"); return 1;
  }

  // Pass 1: render the "scene" (bunny stand-in) into LEVEL 0 only.
  glViewport(0,0,256,256);
  glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
  glUseProgram(fill);
  glDrawArrays(GL_TRIANGLE_STRIP,0,4);

  // glGenerateMipmap(GL_TEXTURE_2D) is intentionally NOT called here.
  // Levels 1..3 remain uninitialized — this is the bug.

  // Pass 2: "filter" samples the texture at LOD 2 → reads uninitialized mip.
  glBindFramebuffer(GL_FRAMEBUFFER,0);
  glViewport(0,0,512,512);
  glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
  glUseProgram(filt);
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D,rt);
  glUniform1i(glGetUniformLocation(filt,"tex"),0);
  glDrawArrays(GL_TRIANGLE_STRIP,0,4);

  glXSwapBuffers(dpy,win);

  unsigned char px[4];
  glReadPixels(256,256,1,1,GL_RGBA,GL_UNSIGNED_BYTE,px);
  printf("center pixel: %u %u %u %u\n",px[0],px[1],px[2],px[3]);

  glXMakeCurrent(dpy,None,NULL);
  glXDestroyContext(dpy,ctx);
  XDestroyWindow(dpy,win);
  XFree(vi); XFree(fbs);
  XCloseDisplay(dpy);
  return 0;
}