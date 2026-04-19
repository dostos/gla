// SOURCE: https://github.com/mrdoob/three.js/issues/32985
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef GLuint (*PFNCREATESHADER)(GLenum);
typedef void (*PFNSHADERSOURCE)(GLuint,GLsizei,const char* const*,const GLint*);
typedef void (*PFNCOMPILESHADER)(GLuint);
typedef GLuint (*PFNCREATEPROGRAM)(void);
typedef void (*PFNATTACHSHADER)(GLuint,GLuint);
typedef void (*PFNLINKPROGRAM)(GLuint);
typedef void (*PFNUSEPROGRAM)(GLuint);
typedef GLint (*PFNGETUNIFORMLOCATION)(GLuint,const char*);
typedef void (*PFNUNIFORM1I)(GLint,GLint);
typedef void (*PFNUNIFORM1F)(GLint,GLfloat);
typedef void (*PFNGENBUFFERS)(GLsizei,GLuint*);
typedef void (*PFNBINDBUFFER)(GLenum,GLuint);
typedef void (*PFNBUFFERDATA)(GLenum,GLsizeiptr,const void*,GLenum);
typedef void (*PFNGENVERTEXARRAYS)(GLsizei,GLuint*);
typedef void (*PFNBINDVERTEXARRAY)(GLuint);
typedef void (*PFNENABLEVERTEXATTRIBARRAY)(GLuint);
typedef void (*PFNVERTEXATTRIBPOINTER)(GLuint,GLint,GLenum,GLboolean,GLsizei,const void*);
typedef void (*PFNGENFRAMEBUFFERS)(GLsizei,GLuint*);
typedef void (*PFNBINDFRAMEBUFFER)(GLenum,GLuint);
typedef void (*PFNFRAMEBUFFERTEXTURE2D)(GLenum,GLenum,GLenum,GLuint,GLint);
typedef void (*PFNACTIVETEXTURE)(GLenum);

#define V_SCENE "#version 330 core\nlayout(location=0) in vec2 p;out vec2 uv;void main(){uv=p*0.5+0.5;gl_Position=vec4(p,0,1);}"
#define F_SCENE "#version 330 core\nin vec2 uv;out vec4 o;void main(){o=vec4(uv.x,uv.y,0.6,1.0);}"
#define V_QUAD  "#version 330 core\nlayout(location=0) in vec2 p;out vec2 uv;void main(){uv=p*0.5+0.5;gl_Position=vec4(p,0,1);}"
#define F_BLUR  "#version 330 core\nin vec2 uv;out vec4 o;uniform sampler2D src;void main(){vec4 s=vec4(0);for(int x=-2;x<=2;x++)for(int y=-2;y<=2;y++)s+=texture(src,uv+vec2(x,y)/256.0);o=s/25.0;}"
#define F_COPY  "#version 330 core\nin vec2 uv;out vec4 o;uniform sampler2D src;void main(){o=texture(src,uv);}"

static void* GLP(const char* n){ return glXGetProcAddress((const GLubyte*)n); }

int main(void){
    Display* dpy=XOpenDisplay(NULL);
    if(!dpy){fprintf(stderr,"no display\n");return 1;}
    int attr[]={GLX_RGBA,GLX_DEPTH_SIZE,24,GLX_DOUBLEBUFFER,None};
    XVisualInfo* vi=glXChooseVisual(dpy,DefaultScreen(dpy),attr);
    GLXContext ctx=glXCreateContext(dpy,vi,NULL,True);
    Window root=DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    swa.colormap=XCreateColormap(dpy,root,vi->visual,AllocNone);
    swa.event_mask=ExposureMask;
    Window win=XCreateWindow(dpy,root,0,0,256,256,0,vi->depth,InputOutput,vi->visual,CWColormap|CWEventMask,&swa);
    XMapWindow(dpy,win);
    glXMakeCurrent(dpy,win,ctx);

    PFNCREATESHADER glCreateShader=GLP("glCreateShader");
    PFNSHADERSOURCE glShaderSource=GLP("glShaderSource");
    PFNCOMPILESHADER glCompileShader=GLP("glCompileShader");
    PFNCREATEPROGRAM glCreateProgram=GLP("glCreateProgram");
    PFNATTACHSHADER glAttachShader=GLP("glAttachShader");
    PFNLINKPROGRAM glLinkProgram=GLP("glLinkProgram");
    PFNUSEPROGRAM glUseProgram=GLP("glUseProgram");
    PFNGETUNIFORMLOCATION glGetUniformLocation=GLP("glGetUniformLocation");
    PFNUNIFORM1I glUniform1i=GLP("glUniform1i");
    PFNGENBUFFERS glGenBuffers=GLP("glGenBuffers");
    PFNBINDBUFFER glBindBuffer=GLP("glBindBuffer");
    PFNBUFFERDATA glBufferData=GLP("glBufferData");
    PFNGENVERTEXARRAYS glGenVertexArrays=GLP("glGenVertexArrays");
    PFNBINDVERTEXARRAY glBindVertexArray=GLP("glBindVertexArray");
    PFNENABLEVERTEXATTRIBARRAY glEnableVertexAttribArray=GLP("glEnableVertexAttribArray");
    PFNVERTEXATTRIBPOINTER glVertexAttribPointer=GLP("glVertexAttribPointer");
    PFNGENFRAMEBUFFERS glGenFramebuffers=GLP("glGenFramebuffers");
    PFNBINDFRAMEBUFFER glBindFramebuffer=GLP("glBindFramebuffer");
    PFNFRAMEBUFFERTEXTURE2D glFramebufferTexture2D=GLP("glFramebufferTexture2D");
    PFNACTIVETEXTURE glActiveTexture=GLP("glActiveTexture");

    #define MK(kind,src) ({GLuint s=glCreateShader(kind);const char*p=src;glShaderSource(s,1,&p,NULL);glCompileShader(s);s;})
    GLuint prog_scene=glCreateProgram();
    glAttachShader(prog_scene,MK(GL_VERTEX_SHADER,V_SCENE));
    glAttachShader(prog_scene,MK(GL_FRAGMENT_SHADER,F_SCENE));
    glLinkProgram(prog_scene);
    GLuint prog_blur=glCreateProgram();
    glAttachShader(prog_blur,MK(GL_VERTEX_SHADER,V_QUAD));
    glAttachShader(prog_blur,MK(GL_FRAGMENT_SHADER,F_BLUR));
    glLinkProgram(prog_blur);
    GLuint prog_copy=glCreateProgram();
    glAttachShader(prog_copy,MK(GL_VERTEX_SHADER,V_QUAD));
    glAttachShader(prog_copy,MK(GL_FRAGMENT_SHADER,F_COPY));
    glLinkProgram(prog_copy);

    float quad[]={-1,-1, 1,-1, -1,1, 1,1};
    GLuint vbo,vao;
    glGenBuffers(1,&vbo);
    glBindBuffer(GL_ARRAY_BUFFER,vbo);
    glBufferData(GL_ARRAY_BUFFER,sizeof(quad),quad,GL_STATIC_DRAW);
    glGenVertexArrays(1,&vao);
    glBindVertexArray(vao);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,0,0);

    GLuint reflector_tex; glGenTextures(1,&reflector_tex);
    glBindTexture(GL_TEXTURE_2D,reflector_tex);
    glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,256,256,0,GL_RGBA,GL_UNSIGNED_BYTE,NULL);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
    GLuint reflector_fbo; glGenFramebuffers(1,&reflector_fbo);
    glBindFramebuffer(GL_FRAMEBUFFER,reflector_fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,reflector_tex,0);

    GLuint blur_tex; glGenTextures(1,&blur_tex);
    glBindTexture(GL_TEXTURE_2D,blur_tex);
    glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,256,256,0,GL_RGBA,GL_UNSIGNED_BYTE,NULL);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
    GLuint blur_fbo; glGenFramebuffers(1,&blur_fbo);
    glBindFramebuffer(GL_FRAMEBUFFER,blur_fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,blur_tex,0);

    glViewport(0,0,256,256);

    glBindFramebuffer(GL_FRAMEBUFFER,blur_fbo);
    glClearColor(0,0,0,1);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(prog_blur);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D,reflector_tex);
    glUniform1i(glGetUniformLocation(prog_blur,"src"),0);
    glDrawArrays(GL_TRIANGLE_STRIP,0,4);

    glBindFramebuffer(GL_FRAMEBUFFER,reflector_fbo);
    glClearColor(0,0,0,1);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(prog_scene);
    glDrawArrays(GL_TRIANGLE_STRIP,0,4);

    glBindFramebuffer(GL_FRAMEBUFFER,0);
    glClearColor(0.2,0.2,0.2,1);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(prog_copy);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D,blur_tex);
    glUniform1i(glGetUniformLocation(prog_copy,"src"),0);
    glDrawArrays(GL_TRIANGLE_STRIP,0,4);

    glXSwapBuffers(dpy,win);
    return 0;
}