// SOURCE: https://github.com/mrdoob/three.js/issues/32698
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <X11/Xlib.h>
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>

#ifndef GLX_CONTEXT_MAJOR_VERSION_ARB
#define GLX_CONTEXT_MAJOR_VERSION_ARB 0x2091
#define GLX_CONTEXT_MINOR_VERSION_ARB 0x2092
#define GLX_CONTEXT_PROFILE_MASK_ARB  0x9126
#define GLX_CONTEXT_CORE_PROFILE_BIT_ARB 0x00000001
#endif

typedef GLXContext (*glXCreateContextAttribsARBProc)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

#define W 512
#define H 512
#define SM 1024

static void midn(float*m){memset(m,0,64);m[0]=m[5]=m[10]=m[15]=1;}
static void mmul(float*o,const float*a,const float*b){float r[16];for(int i=0;i<4;i++)for(int j=0;j<4;j++){float s=0;for(int k=0;k<4;k++)s+=a[k*4+j]*b[i*4+k];r[i*4+j]=s;}memcpy(o,r,64);}
static void mpersp(float*m,float fov,float a,float n,float f){midn(m);float t=1.0f/tanf(fov*0.5f);m[0]=t/a;m[5]=t;m[10]=(f+n)/(n-f);m[11]=-1;m[14]=2*f*n/(n-f);m[15]=0;}
static void mortho(float*m,float l,float r,float b,float t,float n,float f){midn(m);m[0]=2/(r-l);m[5]=2/(t-b);m[10]=-2/(f-n);m[12]=-(r+l)/(r-l);m[13]=-(t+b)/(t-b);m[14]=-(f+n)/(f-n);}
static void mlook(float*m,float ex,float ey,float ez,float cx,float cy,float cz,float ux,float uy,float uz){
  float fx=cx-ex,fy=cy-ey,fz=cz-ez;float fl=sqrtf(fx*fx+fy*fy+fz*fz);fx/=fl;fy/=fl;fz/=fl;
  float sx=fy*uz-fz*uy,sy=fz*ux-fx*uz,sz=fx*uy-fy*ux;float sl=sqrtf(sx*sx+sy*sy+sz*sz);sx/=sl;sy/=sl;sz/=sl;
  float u2x=sy*fz-sz*fy,u2y=sz*fx-sx*fz,u2z=sx*fy-sy*fx;
  midn(m);m[0]=sx;m[4]=sy;m[8]=sz;m[1]=u2x;m[5]=u2y;m[9]=u2z;m[2]=-fx;m[6]=-fy;m[10]=-fz;
  m[12]=-(sx*ex+sy*ey+sz*ez);m[13]=-(u2x*ex+u2y*ey+u2z*ez);m[14]=fx*ex+fy*ey+fz*ez;
}

static const char* VS_D = "#version 330 core\nlayout(location=0)in vec3 p;uniform mat4 uMVP;void main(){gl_Position=uMVP*vec4(p,1);}\n";
static const char* FS_D = "#version 330 core\nvoid main(){}\n";
static const char* VS_M =
 "#version 330 core\n"
 "layout(location=0)in vec3 p;layout(location=1)in vec3 n;\n"
 "uniform mat4 uMVP;uniform mat4 uLightMVP;\n"
 "out vec3 vN;out vec4 vL;\n"
 "void main(){gl_Position=uMVP*vec4(p,1);vN=n;vL=uLightMVP*vec4(p,1);}\n";
static const char* FS_M =
 "#version 330 core\n"
 "in vec3 vN;in vec4 vL;uniform sampler2D uShadow;uniform vec3 uLightDir;\n"
 "out vec4 frag;\n"
 "void main(){\n"
 " vec3 c=vL.xyz/vL.w*0.5+0.5;\n"
 " float d=texture(uShadow,c.xy).r;\n"
 " float s=(c.z>d)?0.25:1.0;\n"
 " float l=max(dot(normalize(vN),normalize(uLightDir)),0.0);\n"
 " frag=vec4(vec3(l*s+0.05),1);\n"
 "}\n";

static const float CUBE[]={
 1,-1,-1,1,0,0, 1,1,-1,1,0,0, 1,1,1,1,0,0,  1,-1,-1,1,0,0, 1,1,1,1,0,0, 1,-1,1,1,0,0,
 -1,-1,-1,-1,0,0, -1,1,1,-1,0,0, -1,1,-1,-1,0,0,  -1,-1,-1,-1,0,0, -1,-1,1,-1,0,0, -1,1,1,-1,0,0,
 -1,1,-1,0,1,0, -1,1,1,0,1,0, 1,1,1,0,1,0,  -1,1,-1,0,1,0, 1,1,1,0,1,0, 1,1,-1,0,1,0,
 -1,-1,-1,0,-1,0, 1,-1,1,0,-1,0, -1,-1,1,0,-1,0,  -1,-1,-1,0,-1,0, 1,-1,-1,0,-1,0, 1,-1,1,0,-1,0,
 -1,-1,1,0,0,1, 1,-1,1,0,0,1, 1,1,1,0,0,1,  -1,-1,1,0,0,1, 1,1,1,0,0,1, -1,1,1,0,0,1,
 -1,-1,-1,0,0,-1, 1,1,-1,0,0,-1, 1,-1,-1,0,0,-1,  -1,-1,-1,0,0,-1, -1,1,-1,0,0,-1, 1,1,-1,0,0,-1
};

static GLuint compile(GLenum t,const char*s){GLuint id=glCreateShader(t);glShaderSource(id,1,&s,0);glCompileShader(id);GLint ok;glGetShaderiv(id,GL_COMPILE_STATUS,&ok);if(!ok){char l[1024];glGetShaderInfoLog(id,1024,0,l);fprintf(stderr,"shader:%s\n",l);exit(1);}return id;}
static GLuint program(const char*vs,const char*fs){GLuint p=glCreateProgram();glAttachShader(p,compile(GL_VERTEX_SHADER,vs));glAttachShader(p,compile(GL_FRAGMENT_SHADER,fs));glLinkProgram(p);return p;}

int main(void){
  Display*dpy=XOpenDisplay(0); if(!dpy){fprintf(stderr,"XOpenDisplay failed\n");return 1;}
  int screen=DefaultScreen(dpy);
  int fbattr[]={GLX_X_RENDERABLE,True,GLX_DRAWABLE_TYPE,GLX_WINDOW_BIT,GLX_RENDER_TYPE,GLX_RGBA_BIT,
    GLX_RED_SIZE,8,GLX_GREEN_SIZE,8,GLX_BLUE_SIZE,8,GLX_DEPTH_SIZE,24,GLX_DOUBLEBUFFER,True,None};
  int nfb=0; GLXFBConfig*fbc=glXChooseFBConfig(dpy,screen,fbattr,&nfb);
  if(!fbc||!nfb){fprintf(stderr,"no FBConfig\n");return 1;}
  GLXFBConfig fbconfig=fbc[0]; XFree(fbc);
  XVisualInfo*vi=glXGetVisualFromFBConfig(dpy,fbconfig);
  XSetWindowAttributes sa; memset(&sa,0,sizeof sa);
  sa.colormap=XCreateColormap(dpy,RootWindow(dpy,vi->screen),vi->visual,AllocNone);
  Window win=XCreateWindow(dpy,RootWindow(dpy,vi->screen),0,0,W,H,0,vi->depth,InputOutput,vi->visual,CWColormap,&sa);
  XMapWindow(dpy,win);
  glXCreateContextAttribsARBProc mkctx=(glXCreateContextAttribsARBProc)glXGetProcAddressARB((const GLubyte*)"glXCreateContextAttribsARB");
  int cattr[]={GLX_CONTEXT_MAJOR_VERSION_ARB,3,GLX_CONTEXT_MINOR_VERSION_ARB,3,GLX_CONTEXT_PROFILE_MASK_ARB,GLX_CONTEXT_CORE_PROFILE_BIT_ARB,None};
  GLXContext ctx=mkctx(dpy,fbconfig,0,True,cattr);
  if(!ctx){fprintf(stderr,"context failed\n");return 1;}
  glXMakeCurrent(dpy,win,ctx);

  GLuint vao,vbo;
  glGenVertexArrays(1,&vao); glBindVertexArray(vao);
  glGenBuffers(1,&vbo); glBindBuffer(GL_ARRAY_BUFFER,vbo);
  glBufferData(GL_ARRAY_BUFFER,sizeof CUBE,CUBE,GL_STATIC_DRAW);
  glVertexAttribPointer(0,3,GL_FLOAT,0,24,0); glEnableVertexAttribArray(0);
  glVertexAttribPointer(1,3,GL_FLOAT,0,24,(void*)12); glEnableVertexAttribArray(1);

  GLuint pD=program(VS_D,FS_D), pM=program(VS_M,FS_M);

  GLuint sTex,sFbo;
  glGenTextures(1,&sTex); glBindTexture(GL_TEXTURE_2D,sTex);
  glTexImage2D(GL_TEXTURE_2D,0,GL_DEPTH_COMPONENT24,SM,SM,0,GL_DEPTH_COMPONENT,GL_FLOAT,0);
  glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
  glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
  glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
  glGenFramebuffers(1,&sFbo); glBindFramebuffer(GL_FRAMEBUFFER,sFbo);
  glFramebufferTexture2D(GL_FRAMEBUFFER,GL_DEPTH_ATTACHMENT,GL_TEXTURE_2D,sTex,0);
  glDrawBuffer(GL_NONE); glReadBuffer(GL_NONE);
  glBindFramebuffer(GL_FRAMEBUFFER,0);

  float lv[16],lp[16],lmvp[16];
  mlook(lv, 2.0f,4.0f,3.0f, 0,0,0, 0,1,0);
  mortho(lp,-2.5f,2.5f,-2.5f,2.5f, 1.0f, 12.0f);
  mmul(lmvp,lp,lv);

  float cv[16],cp[16],cmvp[16];
  mlook(cv, 3.5f,2.2f,3.5f, 0,0,0, 0,1,0);
  mpersp(cp, 1.0f, (float)W/(float)H, 0.1f, 30.0f);
  mmul(cmvp,cp,cv);

  glEnable(GL_DEPTH_TEST);
  glEnable(GL_CULL_FACE);
  glFrontFace(GL_CCW);

  // ---- SHADOW PASS ----
  glBindFramebuffer(GL_FRAMEBUFFER,sFbo);
  glViewport(0,0,SM,SM);
  glClear(GL_DEPTH_BUFFER_BIT);
  glCullFace(GL_BACK);
  glUseProgram(pD);
  glUniformMatrix4fv(glGetUniformLocation(pD,"uMVP"),1,0,lmvp);
  glBindVertexArray(vao);
  glDrawArrays(GL_TRIANGLES,0,36);

  // ---- MAIN PASS ----
  glBindFramebuffer(GL_FRAMEBUFFER,0);
  glViewport(0,0,W,H);
  glClearColor(0.1f,0.1f,0.15f,1.0f);
  glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
  glCullFace(GL_BACK);
  glUseProgram(pM);
  glUniformMatrix4fv(glGetUniformLocation(pM,"uMVP"),1,0,cmvp);
  glUniformMatrix4fv(glGetUniformLocation(pM,"uLightMVP"),1,0,lmvp);
  glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D,sTex);
  glUniform1i(glGetUniformLocation(pM,"uShadow"),0);
  float ll=sqrtf(2*2+4*4+3*3);
  glUniform3f(glGetUniformLocation(pM,"uLightDir"),2.0f/ll,4.0f/ll,3.0f/ll);
  glDrawArrays(GL_TRIANGLES,0,36);

  glXSwapBuffers(dpy,win);
  glFinish();

  // Probe a patch on the lit top face (centered near upper third of screen).
  unsigned char buf[32*32*4];
  glReadPixels(W/2-16, 3*H/5-16, 32, 32, GL_RGBA, GL_UNSIGNED_BYTE, buf);
  int bright=0, dark=0;
  for(int i=0;i<32*32;i++){ int v=buf[i*4]; if(v>160)bright++; else if(v<80)dark++; }
  printf("lit-face probe: bright=%d dark=%d\n", bright, dark);

  glXMakeCurrent(dpy,None,NULL);
  glXDestroyContext(dpy,ctx);
  XDestroyWindow(dpy,win);
  XFreeColormap(dpy,sa.colormap);
  XCloseDisplay(dpy);
  return 0;
}