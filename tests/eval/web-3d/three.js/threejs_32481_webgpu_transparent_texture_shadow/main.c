// SOURCE: https://github.com/mrdoob/three.js/issues/32481
// Minimal repro of a shadow-casting mesh whose color comes from an alpha-texture.
//
// We render two passes into an FBO:
//   pass 1 (shadow map): caster depth
//   pass 2 (lit scene):  receiver sampled with that shadow map

#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char* VS_SHADOW =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "layout(location=1) in vec2 aUV;\n"
    "out vec2 vUV;\n"
    "void main(){ vUV=aUV; gl_Position=vec4(aPos,0.0,1.0);} ";

static const char* FS_SHADOW =
    "#version 330 core\n"
    "in vec2 vUV;\n"
    "void main(){ }\n";

static const char* VS_QUAD =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "layout(location=1) in vec2 aUV;\n"
    "out vec2 vUV;\n"
    "void main(){ vUV=aUV; gl_Position=vec4(aPos,0.0,1.0);} ";

static const char* FS_LIT =
    "#version 330 core\n"
    "in vec2 vUV; out vec4 frag; uniform sampler2D uShadow;\n"
    "void main(){\n"
    "  float s = texture(uShadow, vUV).r;\n"
    "  vec3 base = vec3(1.0);\n"
    "  frag = vec4(base * (s > 0.5 ? 0.2 : 1.0), 1.0);\n"
    "}\n";

static GLuint compile(GLenum k, const char* s){
    GLuint sh=glCreateShader(k); glShaderSource(sh,1,&s,NULL); glCompileShader(sh);
    GLint ok; glGetShaderiv(sh,GL_COMPILE_STATUS,&ok);
    if(!ok){ char log[1024]; glGetShaderInfoLog(sh,1024,NULL,log); fprintf(stderr,"%s\n",log);} return sh;
}
static GLuint link(GLuint v, GLuint f){
    GLuint p=glCreateProgram(); glAttachShader(p,v); glAttachShader(p,f); glLinkProgram(p); return p;
}

int main(void){
    Display* dpy = XOpenDisplay(NULL); if(!dpy) return 1;
    int attr[] = { GLX_RGBA, GLX_DEPTH_SIZE,24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy,0,attr);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy,root,vi->visual,AllocNone);
    Window win = XCreateWindow(dpy,root,0,0,256,256,0,vi->depth,InputOutput,vi->visual,CWColormap,&swa);
    XMapWindow(dpy,win);
    GLXContext ctx = glXCreateContext(dpy,vi,NULL,GL_TRUE);
    glXMakeCurrent(dpy,win,ctx);

    // Quad: caster occupies x in [-0.5,0.5]; UVs let alpha texture create a
    // round silhouette. The receiver is a fullscreen quad showing the shadow.
    float verts[] = {
        -0.5f,-0.5f, 0.0f,0.0f,
         0.5f,-0.5f, 1.0f,0.0f,
         0.5f, 0.5f, 1.0f,1.0f,
        -0.5f, 0.5f, 0.0f,1.0f,
    };
    GLuint vbo,vao; glGenVertexArrays(1,&vao); glGenBuffers(1,&vbo);
    glBindVertexArray(vao); glBindBuffer(GL_ARRAY_BUFFER,vbo);
    glBufferData(GL_ARRAY_BUFFER,sizeof(verts),verts,GL_STATIC_DRAW);
    glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,16,(void*)0); glEnableVertexAttribArray(0);
    glVertexAttribPointer(1,2,GL_FLOAT,GL_FALSE,16,(void*)8); glEnableVertexAttribArray(1);

    // Build an alpha texture: 1.0 alpha inside circle, 0.0 outside.
    const int N=64; unsigned char* px=(unsigned char*)malloc(N*N*4);
    for(int y=0;y<N;y++) for(int x=0;x<N;x++){
        float dx=(x-N/2)/(float)(N/2), dy=(y-N/2)/(float)(N/2);
        unsigned char a = (dx*dx+dy*dy < 1.0f) ? 255 : 0;
        int i=(y*N+x)*4; px[i]=255; px[i+1]=255; px[i+2]=255; px[i+3]=a;
    }
    GLuint tex; glGenTextures(1,&tex); glBindTexture(GL_TEXTURE_2D,tex);
    glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,N,N,0,GL_RGBA,GL_UNSIGNED_BYTE,px);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
    free(px);

    // Shadow FBO: a single-channel target acting as the shadow map mask.
    GLuint shadowTex, fbo;
    glGenTextures(1,&shadowTex); glBindTexture(GL_TEXTURE_2D,shadowTex);
    glTexImage2D(GL_TEXTURE_2D,0,GL_R8,256,256,0,GL_RED,GL_UNSIGNED_BYTE,NULL);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
    glGenFramebuffers(1,&fbo); glBindFramebuffer(GL_FRAMEBUFFER,fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,shadowTex,0);

    GLuint shadowProg = link(compile(GL_VERTEX_SHADER,VS_SHADOW), compile(GL_FRAGMENT_SHADER,FS_SHADOW));
    GLuint litProg    = link(compile(GL_VERTEX_SHADER,VS_QUAD),   compile(GL_FRAGMENT_SHADER,FS_LIT));

    // Pass 1: render caster into shadow map.
    glViewport(0,0,256,256);
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(shadowProg);
    glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D,tex);
    glDrawArrays(GL_TRIANGLE_FAN,0,4);

    // Pass 2: render receiver to default framebuffer using the shadow texture.
    glBindFramebuffer(GL_FRAMEBUFFER,0);
    glViewport(0,0,256,256);
    glClearColor(0.1f,0.1f,0.1f,1); glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(litProg);
    glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D,shadowTex);
    glUniform1i(glGetUniformLocation(litProg,"uShadow"),0);
    glDrawArrays(GL_TRIANGLE_FAN,0,4);

    glXSwapBuffers(dpy,win);
    glXMakeCurrent(dpy,None,NULL); glXDestroyContext(dpy,ctx); XCloseDisplay(dpy);
    return 0;
}